"""Telemetry is written to DATABASE_URL. No CSV or preloaded samples are read."""
from __future__ import annotations
import os
from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table, create_engine

metadata = MetaData()
telemetry = Table(
    'telemetry', metadata,
    Column('id', Integer, primary_key=True),
    Column('robot_id', String(20), nullable=False),
    Column('timestamp', Float, nullable=False),
    *[Column(name, Float, nullable=False) for name in [
        'x', 'y', 'speed', 'battery', 'motor_temp', 'vibration', 'motor_current', 'obstacle_distance']],
    Column('received_at', Float, nullable=False),
    Column('predicted_status', String(10), nullable=False),
    Column('confidence', Float, nullable=False),
    Column('model_version', String(100), nullable=False),
    Column('inference_ms', Float, nullable=False),
)
Index('ix_telemetry_robot_time', telemetry.c.robot_id, telemetry.c.timestamp, telemetry.c.id)


def database_url() -> str:
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError(
            'DATABASE_URL is required. Set your Neon PostgreSQL URL in Render. '
            'For explicit local practice only, use DATABASE_URL=sqlite:///./fleet.db.'
        )
    for prefix in ('postgresql://', 'postgres://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg://' + url[len(prefix):]
    return url


def make_engine(url: str):
    kwargs = {'pool_pre_ping': True}
    if url.startswith('sqlite'):
        kwargs['connect_args'] = {'check_same_thread': False, 'timeout': 30}
    else:
        kwargs.update(pool_size=5, max_overflow=5, pool_recycle=240,
                      connect_args={'connect_timeout': 20, 'prepare_threshold': None})
    engine = create_engine(url, **kwargs)
    return engine
