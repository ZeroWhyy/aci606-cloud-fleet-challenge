"""Load a versioned sklearn Pipeline once; share training's feature order."""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from ml.features import FEATURES, LABELS

class Predictor:
    def __init__(self, path: Path):
        if not path.is_file():
            raise RuntimeError('Missing model.joblib. Run python ml/generate_fleets.py then python ml/train_model.py.')
        self.metadata = json.loads(path.with_name('metadata.json').read_text(encoding='utf-8'))
        if self.metadata['features'] != FEATURES:
            raise RuntimeError('Training and API feature definitions differ')
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.metadata['model_sha256']:
            raise RuntimeError('Model checksum differs from metadata.json; deploy the matching pair')
        self.pipeline = joblib.load(path)
        if set(self.pipeline.classes_) != set(LABELS):
            raise RuntimeError('The model must predict all three target classes')
        self.version = self.metadata['model_version']

    def predict(self, sample: dict) -> dict:
        start = time.perf_counter()
        frame = pd.DataFrame([[sample[f] for f in FEATURES]], columns=FEATURES)
        probabilities = self.pipeline.predict_proba(frame)[0]
        winner = int(np.argmax(probabilities))
        return {'predicted_status': str(self.pipeline.classes_[winner]),
                'confidence': float(probabilities[winner]), 'model_version': self.version,
                'inference_ms': round((time.perf_counter() - start) * 1000, 4)}
