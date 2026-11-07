"""Evaluate a deployed API against another fleet seed, without training on it."""
import argparse
import json
from pathlib import Path
import random
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from simulator.core import make_robot, step_robot
from ml.features import LABELS

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api', required=True)
    p.add_argument('--seed', type=int, default=20261106)
    p.add_argument('--robots', type=int, default=8)
    p.add_argument('--steps', type=int, default=40)
    p.add_argument('--output', default='test-results/unseen_fleet.json')
    args = p.parse_args()
    if min(args.robots, args.steps) < 1:
        p.error('robots and steps must be positive')
    base = args.api.rstrip('/')
    requests.get(base + '/health', timeout=120).raise_for_status()
    rng = random.Random(args.seed)
    robots = [make_robot(i + 1, rng) for i in range(args.robots)]
    truth, predicted, elapsed, versions = [], [], [], set()
    with requests.Session() as session:
        for _ in range(args.steps):
            for robot in robots:
                sample, actual = step_robot(robot, rng)
                sample['robot_id'] = 'UNSEEN-' + robot.robot_id
                start = time.perf_counter()
                response = session.post(base + '/predict', json=sample, timeout=120)
                elapsed.append((time.perf_counter() - start) * 1000)
                response.raise_for_status()
                result = response.json()
                versions.add(result['model_version'])
                truth.append(actual); predicted.append(result['predicted_status'])
    elapsed.sort()
    result = {'api': base, 'seed': args.seed, 'samples': len(truth), 'model_versions': sorted(versions),
              'f1_macro': f1_score(truth, predicted, labels=LABELS, average='macro', zero_division=0),
              'class_distribution': {label: truth.count(label) for label in LABELS},
              'matrix_labels': LABELS, 'confusion_matrix': confusion_matrix(truth, predicted, labels=LABELS).tolist(),
              'classification_report': classification_report(truth, predicted, labels=LABELS, output_dict=True, zero_division=0),
              'client_p50_ms': elapsed[int(.50 * (len(elapsed) - 1))],
              'client_p95_ms': elapsed[int(.95 * (len(elapsed) - 1))]}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
