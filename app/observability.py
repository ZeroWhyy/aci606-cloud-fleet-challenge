"""Thread-safe, per-process operational metrics (reset on service restart)."""
from collections import Counter, deque
from threading import Lock
import time
import numpy as np

class Metrics:
    def __init__(self):
        self.started = time.monotonic()
        self.lock = Lock()
        self.requests = Counter()
        self.errors = Counter()
        self.status_codes = Counter()
        self.durations = {}
        self.duration_sums = Counter()
        self.inferences = 0
        self.inference_sum = 0.

    def record_request(self, route, status, milliseconds):
        with self.lock:
            self.requests[route] += 1
            self.duration_sums[route] += milliseconds
            self.status_codes[str(status)] += 1
            self.durations.setdefault(route, deque(maxlen=2048)).append(milliseconds)
            if status >= 400:
                self.errors[route] += 1

    def record_inference(self, milliseconds):
        with self.lock:
            self.inferences += 1
            self.inference_sum += milliseconds

    def snapshot(self):
        with self.lock:
            count = self.requests['POST /predict']
            recent = list(self.durations.get('POST /predict', []))
            return {
                'scope': 'this_process_since_startup',
                'uptime_seconds': round(time.monotonic() - self.started, 3),
                'requests_received': sum(self.requests.values()),
                'telemetry_requests': self.requests['POST /telemetry'],
                'prediction_requests': count,
                'errors': sum(self.errors.values()),
                'errors_by_route': dict(self.errors),
                'requests_by_route': dict(self.requests),
                'status_codes': dict(self.status_codes),
                'average_prediction_latency_ms': round(self.duration_sums['POST /predict'] / count, 4) if count else 0.,
                'prediction_p50_ms': round(float(np.percentile(recent, 50)), 4) if recent else 0.,
                'prediction_p95_ms': round(float(np.percentile(recent, 95)), 4) if recent else 0.,
                'percentile_window': 'last_2048_prediction_requests_including_errors',
                'model_inferences': self.inferences,
                'average_inference_ms': round(self.inference_sum / self.inferences, 4) if self.inferences else 0.,
            }
