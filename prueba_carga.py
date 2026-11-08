"""Prueba acotada de concurrencia: 40 predicciones, 8 clientes simultaneos."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time

import requests

API = "https://aci606-cloud-fleet-challenge-6opj.onrender.com"
SOLICITUDES = 40
CLIENTES = 8
local = threading.local()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=API)
    parser.add_argument("--output", default="resultado_carga.json")
    args = parser.parse_args()
    base = args.api.rstrip("/")
    print("Comprobando que la API este despierta...", flush=True)
    try:
        r = requests.get(base + "/health", timeout=120)
        r.raise_for_status()
        assert r.json().get("status") == "ok", "La API no esta lista"
    except (requests.RequestException, ValueError, AssertionError) as exc:
        print("No se pudo iniciar la prueba:", exc)
        return 1

    def predict(index):
        if not hasattr(local, "session"):
            local.session = requests.Session()
        sample = dict(robot_id="CARGA-%02d" % index, timestamp=time.time(),
                      x=1.0, y=2.0, speed=0.8, battery=80.0,
                      motor_temp=49.0, vibration=0.4,
                      motor_current=3.8, obstacle_distance=1.3)
        start = time.perf_counter()
        status, valid, error = None, False, None
        try:
            response = local.session.post(base + "/predict", json=sample, timeout=30)
            status = response.status_code
            if status == 200:
                value = response.json()
                valid = (set(value) == {"robot_id", "predicted_status", "confidence",
                                        "model_version", "inference_ms"}
                         and value["robot_id"] == sample["robot_id"]
                         and value["predicted_status"] in {"NORMAL", "WARNING", "CRITICAL"}
                         and 0 <= value["confidence"] <= 1
                         and value["inference_ms"] >= 0
                         and bool(value["model_version"]))
                if not valid:
                    error = "Respuesta fuera del contrato"
            else:
                error = "HTTP %s" % status
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        return dict(solicitud=index, http_status=status, contrato_valido=valid,
                    latencia_cliente_ms=round((time.perf_counter() - start) * 1000, 3),
                    error=error)

    print("Enviando %d predicciones con %d clientes simultaneos..." %
          (SOLICITUDES, CLIENTES), flush=True)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CLIENTES) as pool:
        results = list(pool.map(predict, range(1, SOLICITUDES + 1)))
    duration = time.perf_counter() - started
    healthy = False
    try:
        r = requests.get(base + "/health", timeout=120)
        healthy = r.status_code == 200 and r.json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        pass
    successes = sum(row["http_status"] == 200 and row["contrato_valido"] for row in results)
    latencies = sorted(row["latencia_cliente_ms"] for row in results)
    p50 = latencies[math.ceil(0.50 * len(latencies)) - 1]
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
    approved = successes == SOLICITUDES and healthy
    report = dict(api=base, fecha_utc=datetime.now(timezone.utc).isoformat(),
                  solicitudes=SOLICITUDES, clientes_simultaneos=CLIENTES,
                  respuestas_correctas=successes, errores=SOLICITUDES - successes,
                  codigos_http=dict(Counter(str(row["http_status"]) for row in results)),
                  p50_cliente_ms=p50, p95_cliente_ms=p95,
                  duracion_carga_segundos=round(duration, 3),
                  servicio_activo_despues=healthy, aprobado=approved,
                  alcance="Carga acotada; incluye apertura de conexiones; no mide la capacidad maxima.",
                  resultados=results)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nRESULTADO: %s" % ("APROBADO" if approved else "REVISAR"))
    print("Predicciones correctas: %d/%d" % (successes, SOLICITUDES))
    print("Errores: %d" % (SOLICITUDES - successes))
    print("Latencia cliente p50: %.2f ms | p95: %.2f ms" % (p50, p95))
    print("Servicio activo despues: %s" % ("SI" if healthy else "NO"))
    print("Evidencia guardada en:", path.resolve())
    print("Las predicciones de esta prueba no insertan telemetria.")
    return 0 if approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
