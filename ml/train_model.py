"""Reproducible grouped train/validation/test experiment without fleet leakage."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from ml.features import FEATURES, LABELS


def score(y, predictions):
    return float(f1_score(y, predictions, labels=LABELS, average='macro', zero_division=0))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', default='data/training.csv')
    p.add_argument('--seed', type=int, default=606)
    p.add_argument('--version', default='v1')
    args = p.parse_args()
    source = Path(args.data)
    if not source.exists():
        raise SystemExit('Missing data. Run: python ml/generate_fleets.py')
    df = pd.read_csv(source)
    required = FEATURES + ['fleet_id', 'status']
    if any(c not in df for c in required):
        raise SystemExit('CSV needs fleet_id, status and sensor features. Use ml/generate_fleets.py.')
    if df[required].isna().any().any() or not np.isfinite(df[FEATURES].to_numpy()).all():
        raise SystemExit('Dataset contains missing or nonfinite values')
    if set(df.status) != set(LABELS) or df.fleet_id.nunique() < 10:
        raise SystemExit('Need all three target classes and at least 10 independent fleets')
    development, test = next(GroupShuffleSplit(n_splits=1, test_size=.20, random_state=args.seed)
                             .split(df, groups=df.fleet_id))
    dev = df.iloc[development]
    train_rel, valid_rel = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=args.seed + 1)
                               .split(dev, groups=dev.fleet_id))
    splits = {'train': development[train_rel], 'validation': development[valid_rel], 'test': test}
    fleets = {name: sorted(df.iloc[indices].fleet_id.unique().tolist()) for name, indices in splits.items()}
    for a, b in [('train', 'validation'), ('train', 'test'), ('validation', 'test')]:
        assert not (set(fleets[a]) & set(fleets[b]))
    for name, indices in splits.items():
        if set(df.iloc[indices].status) != set(LABELS):
            raise SystemExit(f'{name} lacks a target class; generate more fleets')
    candidates = {
        'LogisticRegression': Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
            ('classifier', LogisticRegression(C=2., class_weight='balanced', max_iter=2000, random_state=args.seed)),
        ]),
        'RandomForest': Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('classifier', RandomForestClassifier(n_estimators=150, max_depth=14, min_samples_leaf=2,
                                                  class_weight='balanced_subsample', n_jobs=1, random_state=args.seed)),
        ]),
    }
    X, y = df[FEATURES], df.status
    tr, va, te = splits['train'], splits['validation'], splits['test']
    comparison = []
    for name, pipeline in candidates.items():
        start = time.perf_counter()
        pipeline.fit(X.iloc[tr], y.iloc[tr])
        comparison.append({'model': name, 'validation_f1_macro': score(y.iloc[va], pipeline.predict(X.iloc[va])),
                           'training_seconds': round(time.perf_counter() - start, 4)})
    # Validation chooses the winner; reserved test fleets never choose a model.
    best = max(comparison, key=lambda row: row['validation_f1_macro'])['model']
    final = clone(candidates[best]).fit(X.iloc[development], y.iloc[development])
    predicted = final.predict(X.iloc[te])
    baseline = DummyClassifier(strategy='most_frequent').fit(X.iloc[development], y.iloc[development])
    baseline_f1 = score(y.iloc[te], baseline.predict(X.iloc[te]))
    test_f1 = score(y.iloc[te], predicted)
    matrix = confusion_matrix(y.iloc[te], predicted, labels=LABELS)
    models, report_dir = ROOT / 'models', ROOT / 'reports'
    models.mkdir(exist_ok=True)
    report_dir.mkdir(exist_ok=True)
    joblib.dump(final, models / 'model.joblib', compress=3)
    model_sha = hashlib.sha256((models / 'model.joblib').read_bytes()).hexdigest()
    metadata = {
        'model_version': args.version, 'selected_model': best, 'features': FEATURES, 'labels': LABELS,
        'seed': args.seed, 'data_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'model_sha256': model_sha, 'python': platform.python_version(),
        'versions': {'scikit_learn': sklearn.__version__, 'numpy': np.__version__,
                     'pandas': pd.__version__, 'joblib': joblib.__version__},
        'rows': len(df), 'fleets': int(df.fleet_id.nunique()),
        'split_rows': {name: len(indices) for name, indices in splits.items()},
        'split_fleets': fleets,
        'class_distribution': {label: int((df.status == label).sum()) for label in LABELS},
        'split_class_distribution': {name: {label: int((df.iloc[indices].status == label).sum())
                                           for label in LABELS} for name, indices in splits.items()},
        'comparison': comparison, 'test_f1_macro': test_f1, 'baseline_test_f1_macro': baseline_f1,
        'confusion_matrix_labels': LABELS, 'test_confusion_matrix': matrix.tolist(),
        'classification_report': classification_report(y.iloc[te], predicted, labels=LABELS, output_dict=True, zero_division=0),
        'selection_rule': 'Highest validation macro F1; refit winner on train+validation; evaluate test once.',
    }
    (models / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    (report_dir / 'metrics.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    pd.DataFrame(comparison).to_csv(report_dir / 'model_comparison.csv', index=False)
    df[FEATURES].describe().to_csv(report_dir / 'descriptive_statistics.csv')
    assignments = df[['fleet_id', 'robot_id', 'timestamp']].copy()
    for name, indices in splits.items():
        assignments.loc[indices, 'split'] = name
    assignments.to_csv(report_dir / 'split_assignments.csv', index=False)

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    colors = ['#20a67a', '#eab047', '#d95a5a']
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(LABELS, [metadata['class_distribution'][k] for k in LABELS], color=colors)
    ax.bar_label(bars, padding=4)
    ax.set(title=f"Distribución de clases | {metadata['fleets']} flotas simuladas", ylabel='Muestras')
    ax.set_ylim(0, max(metadata['class_distribution'].values()) * 1.16)
    fig.tight_layout()
    fig.savefig(report_dir / 'class_distribution.png', dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 5))
    ConfusionMatrixDisplay(matrix, display_labels=LABELS).plot(ax=ax, cmap='Blues', colorbar=False)
    ax.set(title=f'{best} | flotas de prueba no vistas', xlabel='Clase predicha', ylabel='Clase real')
    fig.tight_layout()
    fig.savefig(report_dir / 'confusion_matrix.png', dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(11, 6))
    for ax, feature in zip(axes.flat, FEATURES):
        for label, color in zip(LABELS, colors):
            ax.hist(df.loc[df.status == label, feature], bins=25, density=True, alpha=.4, label=label, color=color)
        ax.set_title(feature)
        ax.set_ylabel('Densidad')
    axes[0, 0].legend(fontsize=8)
    fig.suptitle('EDA descriptivo: sensores por condición')
    fig.tight_layout()
    fig.savefig(report_dir / 'sensor_distributions.png', dpi=160)
    plt.close(fig)

    split_table = '\n'.join(f'| {name} | {len(fleets[name])} | {len(indices)} |' for name, indices in splits.items())
    comparison_table = '\n'.join(f"| {row['model']} | {row['validation_f1_macro']:.4f} | {row['training_seconds']:.3f} |" for row in comparison)
    report = f'''# Evidencia del modelo - Cloud Fleet

## Datos y exploración

Dataset sintético: {len(df):,} muestras, {metadata['fleets']} flotas, generadas con el simulador original sin modificar sus ecuaciones.
La etiqueta procede de la salud interna del simulador, que NO se entrega al modelo.
Semilla base: {args.seed}. Las semillas de flota se incrementan en 1009.
Distribución: {metadata['class_distribution']}.

![Clases](class_distribution.png)
![Sensores](sensor_distributions.png)

La vibración y la temperatura aumentan al deteriorarse la salud según el simulador.
La batería también depende del tiempo de ejecución; no debe interpretarse como causa de una avería.
Los histogramas son descriptivos; no se usaron para reajustar modelos tras consultar el test.

## Separación sin fuga entre flotas

Dos GroupShuffleSplit con semillas {args.seed} y {args.seed + 1}; reparto 60/20/20 por flota.
Ninguna flota aparece en dos particiones. Las proporciones de clases no son idénticas porque se separan grupos completos.

| Partición | Flotas | Filas |
|---|---:|---:|
{split_table}

Se excluyen fleet_id, robot_id, timestamp, x e y para evitar memorizar identidades, tiempo o posición.
Variables usadas: {', '.join(FEATURES)}.
El preprocesamiento se ajusta dentro de cada Pipeline, después de separar los datos.

## Comparación y selección

| Clasificador | F1 macro de validación | Entrenamiento (s, este entorno) |
|---|---:|---:|
{comparison_table}

Se elige **{best}** por el mayor F1 macro de validación.
Regresión logística: modelo lineal con estandarización; pequeño y rápido.
Random Forest: aprende interacciones y umbrales no lineales; consume más memoria e inferencia.
Ambos ponderan las clases para dar atención a las menos frecuentes.
Se reentrena solo el ganador con entrenamiento + validación y se evalúa una vez en prueba.

## Resultado reservado de prueba

- F1 macro del ganador: **{test_f1:.4f}**.
- F1 macro de la línea base de clase mayoritaria: **{baseline_f1:.4f}**.
- Matriz: etiquetas NORMAL, WARNING, CRITICAL; filas reales y columnas predichas.

![Matriz de confusión](confusion_matrix.png)

F1 macro promedia el F1 de las tres clases por igual; evita que una clase abundante oculte malos resultados en las otras.
Los números por clase están en metrics.json. La probabilidad máxima es una confianza del modelo, no una probabilidad calibrada ni una garantía.

## Reproducibilidad y límites

Pipeline: models/model.joblib. Versión: {args.version}; scikit-learn {sklearn.__version__}.
Hash del dataset: {metadata['data_sha256']}.
Hash del modelo: {model_sha}.
Asignación exacta: split_assignments.csv y metrics.json. Dependencias fijadas en requirements.txt.

Estos resultados corresponden a flotas sintéticas no vistas del mismo generador.
No prueban funcionamiento en robots físicos ni anticipan el F1 de la flota privada del docente.
El EDA muestra todo el dataset con fin documental; la selección usa solo validación.
El servicio no se reentrena con la telemetría que recibe.
'''
    (report_dir / 'ML_REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps({'selected': best, 'validation_comparison': comparison, 'test_f1_macro': test_f1,
                      'baseline_f1_macro': baseline_f1, 'fleets': {k: len(v) for k, v in fleets.items()}}, indent=2))

if __name__ == '__main__':
    main()
