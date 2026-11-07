"""End-to-end check for a local or public Cloud Fleet service."""
from __future__ import annotations
import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import requests

SAMPLE = {'robot_id': 'TEST-01', 'timestamp': 1780000000., 'x': 1.2, 'y': 3.4, 'speed': .72,
          'battery': 81., 'motor_temp': 49., 'vibration': .42, 'motor_current': 3.8, 'obstacle_distance': 1.3}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api', default='http://127.0.0.1:8000')
    p.add_argument('--final', action='store_true', help='Require inference, >100 rows, robustness and concurrency')
    p.add_argument('--timeout', type=float, default=120, help='Allows the free service to wake up')
    p.add_argument('--output', help='Optional JSON evidence file')
    args = p.parse_args()
    base = args.api.rstrip('/')
    report = {'api': base, 'final': args.final, 'checks': [], 'passed': False}
    sample = {**SAMPLE, 'robot_id': 'SMK-' + uuid.uuid4().hex[:12], 'timestamp': time.time()}
    def check(name, passed, **details):
        report['checks'].append({'name': name, 'passed': bool(passed), **details})
        print(f"{'OK' if passed else 'FAIL'}  {name}")
        if not passed:
            raise AssertionError(name)
    def req(method, path, **kwargs):
        return requests.request(method, base + path, timeout=args.timeout, **kwargs)
    try:
        r = req('GET', '/health'); check('health', r.status_code == 200 and r.json().get('status') == 'ok')
        r = req('POST', '/telemetry', json=sample); check('persistent ingestion', r.status_code == 200 and r.json().get('accepted'))
        r = req('GET', '/robots'); check('robot list', r.status_code == 200 and any(x['robot_id'] == sample['robot_id'] for x in r.json()))
        r = req('GET', '/robots/' + sample['robot_id'] + '/history'); check('history', r.status_code == 200 and len(r.json()) == 1)
        r = req('GET', '/metrics'); check('metrics', r.status_code == 200 and all(k in r.json() for k in ['telemetry_requests', 'prediction_requests', 'errors', 'average_prediction_latency_ms', 'uptime_seconds']))
        r = req('GET', '/dashboard'); check('dashboard', r.status_code == 200 and '<canvas' in r.text)
        if args.final:
            r = req('POST', '/predict', json=sample)
            value = r.json()
            required = {'robot_id', 'predicted_status', 'confidence', 'model_version', 'inference_ms'}
            check('prediction contract', r.status_code == 200 and set(value) == required
                  and value['robot_id'] == sample['robot_id'] and value['predicted_status'] in {'NORMAL', 'WARNING', 'CRITICAL'}
                  and 0 <= value['confidence'] <= 1 and value['inference_ms'] >= 0 and bool(value['model_version']))
            for i in range(1, 125):
                r = req('POST', '/telemetry', json={**sample, 'timestamp': sample['timestamp'] + i})
                if r.status_code != 200:
                    check(f'ingestion {i}', False, status=r.status_code)
            r = req('GET', '/robots/' + sample['robot_id'] + '/history')
            check('complete history exceeds 100 rows', r.status_code == 200 and len(r.json()) == 125, rows=len(r.json()))
            cases = [{k: v for k, v in sample.items() if k != 'battery'}, {**sample, 'battery': -1},
                     {**sample, 'speed': -1}, {**sample, 'battery': 101}, {**sample, 'x': float('nan')},
                     {**sample, 'motor_temp': float('inf')}]
            for path in ['/predict', '/telemetry']:
                for i, payload in enumerate(cases):
                    r = req('POST', path, data=json.dumps(payload), headers={'Content-Type': 'application/json'})
                    check(f'{path} invalid case {i + 1} is 4xx', 400 <= r.status_code < 500, status=r.status_code)
            def predict(_):
                start = time.perf_counter()
                r = req('POST', '/predict', json=sample)
                return r.status_code, (time.perf_counter() - start) * 1000
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(predict, range(40)))
            latencies = sorted(x[1] for x in results)
            check('40 concurrent predictions / 8 clients', all(status == 200 for status, _ in results),
                  requests=40, workers=8, client_p50_ms=round(latencies[19], 3), client_p95_ms=round(latencies[37], 3))
            r = req('GET', '/health'); check('service healthy after invalid data and load', r.status_code == 200)
        report['passed'] = True
    except (requests.RequestException, AssertionError, ValueError, KeyError, TypeError) as exc:
        report['error'] = str(exc)
        print('FAILED:', exc)
    if args.output:
        from pathlib import Path
        out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if report['passed'] else 1)

if __name__ == '__main__':
    main()
