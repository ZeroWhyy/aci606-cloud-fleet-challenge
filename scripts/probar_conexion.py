"""Verify HTTP ingestion -> PostgreSQL -> HTTP history with a unique robot."""
import argparse
import json
from pathlib import Path
import time
import uuid
import requests
from conexion import get_api_url, wait_for_api

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api')
    p.add_argument('--output', default='resultado_conexion.json')
    args = p.parse_args()
    base = get_api_url(args.api, interactive=True)
    robot_id = 'CHK-' + uuid.uuid4().hex[:12]
    with requests.Session() as session:
        health = wait_for_api(session, base)
        if health.get('storage') != 'postgresql':
            raise SystemExit('La prueba exige PostgreSQL. Configura DATABASE_URL en Render.')
        url = base + '/robots/' + robot_id + '/history'
        before = session.get(url, timeout=30)
        assert before.status_code == 404, 'El robot ya existe; vuelve a ejecutar.'
        sent, ids = [], []
        for i in range(3):
            sample = {'robot_id': robot_id, 'timestamp': time.time() + i, 'x': 1.2+i, 'y': 3.4,
                      'speed': .72, 'battery': 81.-i, 'motor_temp': 49.+i, 'vibration': .42,
                      'motor_current': 3.8, 'obstacle_distance': 1.3}
            response = session.post(base + '/telemetry', json=sample, timeout=30)
            response.raise_for_status(); result = response.json()
            assert result.get('stored') is True and result['record_id'] > 0, 'No se confirmó la escritura'
            sent.append(sample); ids.append(result['record_id'])
            print(f"POST /telemetry -> PostgreSQL id={result['record_id']}", flush=True)
        response = session.get(url, timeout=30); response.raise_for_status()
        rows = response.json()
        assert len(rows) == 3 and [r['id'] for r in rows] == ids
        for sample, row in zip(sent, rows):
            for key, value in sample.items(): assert row[key] == value, f'Difiere {key}'
        response = session.post(base + '/predict', json=sent[-1], timeout=30); response.raise_for_status()
        prediction = response.json()
        response = session.get(url, timeout=30); response.raise_for_status()
        assert len(response.json()) == 3, '/predict no debe insertar muestras'
        result = {'passed': True, 'api': base, 'storage': health['storage'], 'robot_id': robot_id,
                  'records_before': 0, 'records_after': 3, 'record_ids': ids,
                  'read_back_values_identical': True, 'predict_did_not_insert': True,
                  'prediction': prediction,
                  'sql_to_verify': "SELECT id, robot_id, battery, predicted_status FROM telemetry WHERE robot_id = '"+robot_id+"' ORDER BY timestamp, id;"}
        out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print('PASS: 0 antes -> 3 enviados -> 3 recuperados, con ids y valores idénticos.', flush=True)
        print('Comprueba en Neon > SQL Editor con esta consulta:', flush=True)
        print(result['sql_to_verify'], flush=True)
        print('Evidencia: ' + str(out), flush=True)

if __name__ == '__main__': main()
