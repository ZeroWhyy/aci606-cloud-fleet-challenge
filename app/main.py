from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import time
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from app.db import database_url, make_engine, metadata, telemetry
from app.model import Predictor
from app.observability import Metrics

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
logger = logging.getLogger('cloud_fleet')
Status = Literal['NORMAL', 'WARNING', 'CRITICAL']

class Telemetry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    robot_id: str = Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')
    timestamp: float = Field(ge=0)
    x: float
    y: float
    speed: float = Field(ge=0)
    battery: float = Field(ge=0, le=100)
    motor_temp: float = Field(ge=-273.15)
    vibration: float = Field(ge=0)
    motor_current: float = Field(ge=0)
    obstacle_distance: float = Field(ge=0)

class PredictionResponse(BaseModel):
    robot_id: str
    predicted_status: Status
    confidence: float = Field(ge=0, le=1)
    model_version: str
    inference_ms: float = Field(ge=0)


def create_app(db_url: str | None = None, model_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api):
        path = Path(model_path or os.getenv('MODEL_PATH', str(ROOT / 'models/model.joblib')))
        if not path.is_absolute():
            path = ROOT / path
        api.state.predictor = Predictor(path)
        engine = make_engine(db_url or database_url())
        if os.getenv('RENDER') and engine.dialect.name != 'postgresql':
            engine.dispose()
            raise RuntimeError('Cloud deployment requires PostgreSQL; SQLite is local only.')
        try:
            metadata.create_all(engine)
            api.state.engine = engine
            api.state.metrics = Metrics()
            yield
        finally:
            engine.dispose()

    api = FastAPI(title='ACI606 Cloud Fleet', version='1.1.0', lifespan=lifespan,
                  description='Persistencia, clasificación de condición y operación de flotas.')

    @api.middleware('http')
    async def measure(request: Request, call_next):
        start, status = time.perf_counter(), 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            if hasattr(request.app.state, 'metrics'):
                route = request.scope.get('route')
                # Route templates avoid creating a metric key for every robot identifier.
                path = getattr(route, 'path', 'unmatched')
                request.app.state.metrics.record_request(
                    f'{request.method} {path}', status, (time.perf_counter() - start) * 1000)

    @api.exception_handler(RequestValidationError)
    async def invalid_data(_, exc):
        # Do not echo NaN/Infinity back into a strict JSON response (that would cause a 500).
        detail = [{'loc': e['loc'], 'msg': e['msg'], 'type': e['type']} for e in exc.errors()]
        return JSONResponse(status_code=422, content={'detail': detail})

    @api.exception_handler(SQLAlchemyError)
    async def database_failure(_, exc):
        logger.warning('Database unavailable: %s', type(exc).__name__)
        return JSONResponse(status_code=503, content={'detail': 'Database temporarily unavailable; retry later.'})

    def infer(sample):
        prediction = api.state.predictor.predict(sample)
        api.state.metrics.record_inference(prediction['inference_ms'])
        return prediction

    @api.get('/', include_in_schema=False)
    def home():
        return RedirectResponse('/dashboard')

    @api.get('/health')
    def health():
        with api.state.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'status': 'ok', 'service': 'aci606-cloud-fleet', 'version': api.version,
                'database': 'ok', 'storage': api.state.engine.dialect.name,
                'model_version': api.state.predictor.version,
                'utc': datetime.now(timezone.utc).isoformat()}

    @api.post('/telemetry')
    def ingest_telemetry(sample: Telemetry):
        values = sample.model_dump()
        prediction = infer(values)
        # A transaction is committed BEFORE success is returned to the client.
        with api.state.engine.begin() as connection:
            record_id = connection.execute(
                telemetry.insert().values(**values, received_at=time.time(), **prediction)
                .returning(telemetry.c.id)
            ).scalar_one()
        return {'accepted': True, 'robot_id': sample.robot_id,
                'stored': True, 'record_id': record_id,
                'server_time': datetime.now(timezone.utc).isoformat(), **prediction}

    @api.get('/robots')
    def list_robots():
        ranked = select(
            telemetry,
            func.row_number().over(partition_by=telemetry.c.robot_id,
                                   order_by=(telemetry.c.timestamp.desc(), telemetry.c.id.desc())).label('row_number'),
            func.count().over(partition_by=telemetry.c.robot_id).label('history_count'),
            func.max(telemetry.c.received_at).over(partition_by=telemetry.c.robot_id).label('last_received_at'),
        ).subquery()
        with api.state.engine.connect() as connection:
            rows = connection.execute(select(ranked).where(ranked.c.row_number == 1).order_by(ranked.c.robot_id)).mappings().all()
        result = []
        now = time.time()
        for row in rows:
            item = {k: v for k, v in row.items() if k not in ('row_number', 'id')}
            item['connected'] = now - item['last_received_at'] < 30
            result.append(item)
        return result

    @api.get('/robots/{robot_id}/history')
    def robot_history(robot_id: str, limit: int | None = Query(default=None, ge=1, le=5000)):
        # No limit by default: the required contract returns the COMPLETE history.
        query = select(telemetry).where(telemetry.c.robot_id == robot_id)
        if limit:
            query = query.order_by(telemetry.c.timestamp.desc(), telemetry.c.id.desc()).limit(limit)
        else:
            query = query.order_by(telemetry.c.timestamp, telemetry.c.id)
        with api.state.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        if not rows:
            raise HTTPException(status_code=404, detail='Robot not found')
        result = [dict(row) for row in rows]
        return result[::-1] if limit else result

    @api.post('/predict', response_model=PredictionResponse)
    def predict(sample: Telemetry):
        return {'robot_id': sample.robot_id, **infer(sample.model_dump())}

    @api.get('/metrics')
    def metrics():
        snapshot = api.state.metrics.snapshot()
        with api.state.engine.connect() as connection:
            records, robots = connection.execute(select(func.count(), func.count(func.distinct(telemetry.c.robot_id))).select_from(telemetry)).one()
        snapshot.update(telemetry_records=records, robots_stored=robots,
                        persistence=api.state.engine.dialect.name, prediction_service='READY',
                        model_version=api.state.predictor.version)
        return snapshot

    @api.get('/dashboard', response_class=HTMLResponse)
    def dashboard():
        return (ROOT / 'dashboard/index.html').read_text(encoding='utf-8')

    return api

app = create_app()
