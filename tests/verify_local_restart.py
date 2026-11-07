"""Prove complete history survives an actual restart of a local Uvicorn process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import requests

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='reports/local_restart_test.json')
    args = parser.parse_args()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    def history_hash(rows):
        return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, DATABASE_URL='sqlite:///' + str(Path(temporary) / 'fleet.db'))
        env.pop('RENDER', None)
        process = None
        def start():
            proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(200):
                if proc.poll() is not None:
                    raise RuntimeError('Uvicorn stopped during startup')
                try:
                    if requests.get(base + '/health', timeout=1).status_code == 200:
                        return proc
                except requests.RequestException:
                    pass
                time.sleep(.1)
            proc.terminate(); proc.wait(timeout=10)
            raise RuntimeError('Uvicorn startup timed out')
        def stop(proc):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
        try:
            process = start(); pid_before = process.pid
            for i in range(125):
                sample = {'robot_id': 'RESTART-TEST', 'timestamp': 1780000000. + i, 'x': 1., 'y': 2., 'speed': .8,
                          'battery': 80., 'motor_temp': 49., 'vibration': .4, 'motor_current': 3.8, 'obstacle_distance': 1.3}
                r = requests.post(base + '/telemetry', json=sample, timeout=10); r.raise_for_status()
            r = requests.get(base + '/robots/RESTART-TEST/history', timeout=10); r.raise_for_status()
            before = r.json(); assert len(before) == 125
            stop(process); process = None
            process = start(); pid_after = process.pid
            r = requests.get(base + '/robots/RESTART-TEST/history', timeout=10); r.raise_for_status()
            after = r.json()
            assert len(after) == 125 and history_hash(before) == history_hash(after)
            assert pid_before != pid_after
            report = {'passed': True, 'scope': 'local SQLite; actual Uvicorn OS process restart; not Neon/Render',
                      'rows_before': len(before), 'rows_after': len(after),
                      'sha256_before': history_hash(before), 'sha256_after': history_hash(after),
                      'different_processes': pid_before != pid_after}
            out = ROOT / args.output; out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(report, indent=2))
        finally:
            if process is not None:
                stop(process)

if __name__ == '__main__':
    main()
