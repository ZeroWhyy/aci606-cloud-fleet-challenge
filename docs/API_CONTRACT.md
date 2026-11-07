# Contrato de la API

| Método y ruta | Resultado |
|---|---|
| GET /health | Estado real de base de datos y modelo; 503 si falla la base |
| POST /telemetry | Valida, predice y guarda una muestra; accepted=true, stored=true y record_id después del commit |
| GET /robots | Una muestra por robot: mayor timestamp y desempate por id |
| GET /robots/{robot_id}/history | Historial completo, en orden de timestamp e id; 404 si no existe |
| POST /predict | Inferencia sin insertar telemetría |
| GET /metrics | Solicitudes, errores, latencias, uptime y totales persistentes |
| GET /dashboard | Panel de operación |
| GET /docs | Swagger interactivo |

Entrada de `/telemetry` y `/predict`:

```json
{"robot_id":"R03","timestamp":1780000000.0,"x":4.21,"y":7.82,"speed":0.63,"battery":71.0,"motor_temp":48.2,"vibration":0.43,"motor_current":3.7,"obstacle_distance":0.42}
```

Respuesta exacta de `/predict` (ejemplo de formato, no resultado de una medición):

```json
{"robot_id":"R03","predicted_status":"WARNING","confidence":0.87,"model_version":"v1","inference_ms":12.4}
```

Clases permitidas: NORMAL, WARNING, CRITICAL. La batería debe estar en [0,100]; speed, vibration, motor_current, obstacle_distance y timestamp deben ser no negativos. motor_temp debe ser >= -273.15. Todos los valores numéricos deben ser finitos. `robot_id` admite entre 1 y 20 caracteres alfanuméricos y los separadores `_ . : -`, comenzando por un alfanumérico. Los campos faltantes, desconocidos o inválidos producen 422; los errores de validación no reflejan los valores NaN/Infinity en la respuesta.

Los elementos de `/robots` agregan predicted_status, confidence, model_version, inference_ms, history_count, last_received_at y connected. `connected` significa recepción en los últimos 30 segundos, no conexión TCP permanente.

`/history?limit=120` entrega las 120 últimas muestras, ordenadas de antigua a reciente. `limit` es opcional (1 a 5000). Sin `limit` se entregan TODAS las muestras; no existe un tope de almacenamiento de 100 o 5000.

`average_prediction_latency_ms` mide la duración de peticiones a `/predict` en el servidor, incluidas inválidas. `average_inference_ms` mide solo la ejecución interna del modelo, tanto para ingesta como para predicción. p50/p95 usan una ventana de las últimas 2048 peticiones. El cliente remoto también mide red y arranque en frío, por eso tendrá otros valores. `/metrics` cuenta su propia petición al terminar: su resultado no incluye aún esa consulta en curso.

La confirmación de POST /telemetry incluye record_id, el ID de la fila que devolvió PostgreSQL mediante INSERT RETURNING; la respuesta se envía tras confirmar la transacción. El mismo ID aparece como id en el historial. No cambia el contrato exacto de POST /predict.
