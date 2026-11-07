# Arquitectura de comunicación

1. El cliente genera una muestra nueva con las ecuaciones originales del simulador.
2. Envía JSON a POST /telemetry de la URL de Render.
3. Pydantic valida la muestra. El Pipeline de models/model.joblib produce la condición y confianza.
4. SQLAlchemy usa DATABASE_URL para abrir una conexión psycopg a PostgreSQL de Neon.
5. INSERT ... RETURNING id crea una fila. La transacción termina con COMMIT antes de responder.
6. La respuesta devuelve stored=true, record_id y la predicción.
7. GET /robots, /history y /metrics consultan PostgreSQL. El dashboard solo consulta la API.

La base nueva no contiene telemetría. No se carga un CSV, no se genera una flota dentro del servidor y no se reemplazan los datos operativos por datos de entrenamiento. Los scripts de ml/ sirven solo para el experimento de entrenamiento opcional y separado.

POST /predict acepta una muestra y devuelve inferencia sin insertar. POST /telemetry sí inserta y guarda la predicción junto con la muestra. El modelo se carga al iniciar, no se entrena por cada petición.

DATABASE_URL es obligatoria. En Render se exige PostgreSQL. SQLite únicamente se permite si se configura de forma explícita para práctica o tests locales. pool_pre_ping=True permite detectar conexiones inactivas; el pool tiene tamaño acotado y se desactivan las sentencias preparadas automáticas para usar el pool transaccional de Neon.

Las muestras quedan en la tabla telemetry, con índice por robot, timestamp e id. No se eliminan al superar 100. La última muestra se elige por timestamp, no por orden de llegada. El dashboard muestra una ventana de 120 para dibujar, pero el historial sin limit devuelve todo.

Los contadores y el uptime viven por proceso y se reinician junto a la API. La telemetría, predicciones y versiones se guardan en PostgreSQL y permanecen. Se usa un único worker para mantener coherentes las métricas de este ejercicio.

La prueba scripts/probar_conexion.py envía muestras únicas y compara IDs y valores al recuperarlas. Imprime una consulta para comprobar esas mismas filas de manera independiente en el SQL Editor de Neon.
