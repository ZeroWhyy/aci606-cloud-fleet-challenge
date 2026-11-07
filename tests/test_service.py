from concurrent.futures import ThreadPoolExecutor
import json
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

SAMPLE = {'robot_id': 'TEST-01', 'timestamp': 1780000000., 'x': 1.2, 'y': 3.4, 'speed': .72,
          'battery': 81., 'motor_temp': 49., 'vibration': .42, 'motor_current': 3.8, 'obstacle_distance': 1.3}

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_url='sqlite:///' + str(tmp_path / 'fleet.db'))) as c:
        yield c


def test_contract_and_prediction_does_not_insert(client):
    assert client.get('/health').json()['database'] == 'ok'
    result = client.post('/predict', json=SAMPLE)
    assert result.status_code == 200
    value = result.json()
    assert set(value) == {'robot_id', 'predicted_status', 'confidence', 'model_version', 'inference_ms'}
    assert value['predicted_status'] in {'NORMAL', 'WARNING', 'CRITICAL'}
    assert 0 <= value['confidence'] <= 1 and value['inference_ms'] >= 0
    assert client.get('/robots').json() == []
    assert client.get('/metrics').json()['prediction_requests'] == 1
    assert client.get('/dashboard').status_code == 200


def test_over_100_records_survive_new_app_instance(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'persistent.db')
    with TestClient(create_app(db_url=url)) as before:
        for i in range(125):
            assert before.post('/telemetry', json={**SAMPLE, 'timestamp': SAMPLE['timestamp'] + i}).status_code == 200
        original = before.get('/robots/TEST-01/history').json()
        assert len(original) == 125
    # New engine, model and metrics; no shared in-memory telemetry state.
    with TestClient(create_app(db_url=url)) as after:
        assert after.get('/robots/TEST-01/history').json() == original
        assert after.get('/robots').json()[0]['history_count'] == 125
        assert after.get('/metrics').json()['telemetry_requests'] == 0
        assert len(after.get('/robots/TEST-01/history?limit=10').json()) == 10


def test_latest_is_event_time_not_arrival_time(client):
    for stamp in [100, 90, 110, 95]:
        assert client.post('/telemetry', json={**SAMPLE, 'timestamp': stamp}).status_code == 200
    assert client.get('/robots').json()[0]['timestamp'] == 110
    history = client.get('/robots/TEST-01/history').json()
    assert [x['timestamp'] for x in history] == [90, 95, 100, 110]
    assert [x['timestamp'] for x in client.get('/robots/TEST-01/history?limit=2').json()] == [100, 110]


def test_ingestion_acknowledges_a_committed_database_record(client):
    assert client.get('/metrics').json()['telemetry_records'] == 0
    response = client.post('/telemetry', json=SAMPLE)
    assert response.status_code == 200
    acknowledgment = response.json()
    assert acknowledgment['stored'] is True
    assert acknowledgment['record_id'] > 0
    rows = client.get('/robots/TEST-01/history').json()
    assert len(rows) == 1
    assert rows[0]['id'] == acknowledgment['record_id']
    assert rows[0]['battery'] == SAMPLE['battery']
    assert rows[0]['predicted_status'] == acknowledgment['predicted_status']
    assert client.get('/metrics').json()['telemetry_records'] == 1

@pytest.mark.parametrize('route', ['/predict', '/telemetry'])
@pytest.mark.parametrize('change', [
    {'battery': -1}, {'battery': 101}, {'speed': -1}, {'vibration': -1},
    {'motor_current': -1}, {'obstacle_distance': -1}, {'timestamp': -1},
    {'motor_temp': -300}, {'robot_id': ''}, {'robot_id': '<script>'}, {'unknown': 1},
    {'x': float('nan')}, {'motor_temp': float('inf')}, {'battery': float('-inf')},
])
def test_invalid_values_are_4xx_and_service_survives(client, route, change):
    # Raw JSON also tests permissive parsers receiving NaN or Infinity tokens.
    response = client.post(route, content=json.dumps({**SAMPLE, **change}), headers={'Content-Type': 'application/json'})
    assert 400 <= response.status_code < 500
    assert client.get('/health').status_code == 200
    assert client.get('/robots').json() == []
    assert client.get('/metrics').json()['errors'] >= 1

@pytest.mark.parametrize('field', list(SAMPLE))
def test_missing_fields(client, field):
    payload = {key: value for key, value in SAMPLE.items() if key != field}
    assert client.post('/predict', json=payload).status_code == 422
    assert client.post('/telemetry', json=payload).status_code == 422


def test_concurrent_predictions_and_ingestion(client):
    def run(i):
        return client.post('/predict' if i % 2 else '/telemetry', json={**SAMPLE, 'timestamp': SAMPLE['timestamp'] + i})
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(run, range(48)))
    assert all(r.status_code == 200 for r in responses)
    assert len(client.get('/robots/TEST-01/history').json()) == 24
    metrics = client.get('/metrics').json()
    assert metrics['prediction_requests'] == 24
    assert metrics['telemetry_requests'] == 24
    assert metrics['errors'] == 0
    assert metrics['prediction_p95_ms'] >= metrics['prediction_p50_ms']


def test_unknown_history_and_bad_limit(client):
    assert client.get('/robots/MISSING/history').status_code == 404
    assert client.get('/robots/TEST-01/history?limit=0').status_code == 422
    assert client.get('/robots/TEST-01/history?limit=5001').status_code == 422
    assert client.get('/health').status_code == 200
