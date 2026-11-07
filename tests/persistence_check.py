"""Capture a robot history before a manual restart and verify it afterwards."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid
import requests

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api', required=True)
    p.add_argument('--phase', choices=['before', 'after'], required=True)
    p.add_argument('--state', default='test-results/persistence.json')
    args = p.parse_args()
    base = args.api.rstrip('/')
    state = Path(args.state)
    r = requests.get(base + '/health', timeout=120); r.raise_for_status()
    if args.phase == 'before':
        robot = 'PST-' + uuid.uuid4().hex[:12]
        stamp = time.time()
        for i in range(125):
            sample = {'robot_id': robot, 'timestamp': stamp + i, 'x': 1., 'y': 2., 'speed': .8,
                      'battery': 80. - i * .05, 'motor_temp': 49., 'vibration': .4,
                      'motor_current': 3.8, 'obstacle_distance': 1.3}
            response = requests.post(base + '/telemetry', json=sample, timeout=120); response.raise_for_status()
        r = requests.get(base + '/robots/' + robot + '/history', timeout=120); r.raise_for_status()
        history = r.json()
        assert len(history) == 125, 'Expected complete history, including rows beyond 100'
        value = {'api': base, 'robot_id': robot, 'records_before': len(history), 'sha256_before': digest(history),
                 'captured_at': time.time(), 'verified_after_restart': False}
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(f'BEFORE: {robot}, 125 persisted records. Now restart the web service (Render > Manual Deploy > Restart service).')
        print('After restarting, run this command again with --phase after and the same --state file.')
    else:
        value = json.loads(state.read_text(encoding='utf-8'))
        assert base == value['api'], 'Use the same API URL before and after restarting'
        r = requests.get(base + '/robots/' + value['robot_id'] + '/history', timeout=120); r.raise_for_status()
        history = r.json()
        assert len(history) == value['records_before'], 'History length changed'
        assert digest(history) == value['sha256_before'], 'History contents changed'
        value.update(verified_after_restart=True, verified_at=time.time(), records_after=len(history), sha256_after=digest(history))
        state.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print(f'PASS: all {len(history)} records are identical. This check assumes you actually restarted between phases.')

if __name__ == '__main__':
    main()
