# Cloud Fleet Challenge - ACI606

Servicio de monitoreo de una flota virtual de robots. Recibe telemetría por HTTP, predice la condición de cada robot y guarda las muestras con sus predicciones en PostgreSQL. El dashboard permite consultar el estado y el historial desde un navegador.

## Servicio público

| Acceso | URL |
|---|---|
| API: URL base para clientes y pruebas | https://aci606-cloud-fleet-challenge-6opj.onrender.com |
| Dashboard | https://aci606-cloud-fleet-challenge-6opj.onrender.com/dashboard |
| Estado del servicio y de la base | https://aci606-cloud-fleet-challenge-6opj.onrender.com/health |
| Documentación interactiva de la API | https://aci606-cloud-fleet-challenge-6opj.onrender.com/docs |
| Métricas operativas | https://aci606-cloud-fleet-challenge-6opj.onrender.com/metrics |

Los comandos `--api` reciben la URL base, sin `/dashboard`. El servicio y el modelo se ejecutan en Render; el simulador puede ejecutarse desde otro equipo. Se comprobó el acceso al dashboard desde un celular y desde el equipo de otra persona.

## Arquitectura y persistencia

| Componente | Función |
|---|---|
| Simulador Python | Genera muestras nuevas y las envía a `POST /telemetry` |
| FastAPI y Uvicorn en Render | Validan los datos, ejecutan el modelo y atienden las consultas |
| Modelo `models/model.joblib` | Clasifica la condición en `NORMAL`, `WARNING` o `CRITICAL` |
| PostgreSQL en Neon | Conserva la telemetría y las predicciones en la tabla `telemetry` |
| Dashboard | Consulta la API y muestra sensores, batería, predicción, confianza e historial |
| GitHub | Versiona el código, el modelo y la configuración del despliegue |

Cada muestra aceptada por `/telemetry` se inserta y confirma en PostgreSQL antes de responder con su `record_id`. Se guardan los sensores, la posición, las marcas de tiempo y la predicción con su confianza, versión y tiempo de inferencia. `/robots` y los historiales consultan esa base.

La tabla se crea al iniciar el servicio si todavía no existe. El historial completo se conserva sin un límite fijo de 100 muestras por robot. Los datos operativos están en Neon, separados del sistema de archivos de Render, y sobreviven al reinicio de la API.

`POST /predict` calcula una predicción sin insertar telemetría. El modelo se carga al arrancar y permanece disponible para las solicitudes. Los datos de entrenamiento se usan para construir el modelo; el panel muestra las muestras recibidas por la API.

## Ejecutar el simulador desde Windows

Se requiere Python. Desde la raíz del repositorio, crear el entorno e instalar la dependencia del cliente:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install requests==2.34.2
```

Si el entorno ya está preparado, ejecutar directamente:

```powershell
.\.venv\Scripts\python.exe simulator\fleet_simulator.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --robots 6 --timeout 120
```

Abrir el dashboard mientras el simulador está enviando muestras. `Ctrl + C` detiene los envíos; las muestras confirmadas permanecen en la base. Un robot deja de aparecer conectado cuando pasan aproximadamente 30 segundos sin recibir telemetría, pero su historial sigue disponible.

En Linux o macOS se puede preparar un entorno con `python3 -m venv .venv`, instalar `requests==2.34.2` con `.venv/bin/python` y usar ese mismo intérprete para ejecutar el simulador.

## Contrato de la API

| Método y ruta | Función |
|---|---|
| `GET /health` | Estado del servicio, conexión a PostgreSQL y versión del modelo |
| `POST /telemetry` | Validar, predecir y almacenar una muestra |
| `GET /robots` | Última muestra, predicción y cantidad de registros de cada robot |
| `GET /robots/{id}/history` | Historial completo del robot, sin recorte por defecto |
| `POST /predict` | Obtener la condición predicha de una muestra |
| `GET /metrics` | Contadores, latencias, uptime y totales persistidos |
| `GET /dashboard` | Panel del operador |
| `GET /docs` | Interfaz para consultar y probar los endpoints |

Ejemplo de entrada válida para `/predict` o `/telemetry`:

```json
{
  "robot_id": "R01",
  "timestamp": 1780000000.0,
  "x": 1.0,
  "y": 2.0,
  "speed": 0.8,
  "battery": 80.0,
  "motor_temp": 49.0,
  "vibration": 0.4,
  "motor_current": 3.8,
  "obstacle_distance": 1.3
}
```

La respuesta de `/predict` contiene exactamente `robot_id`, `predicted_status`, `confidence`, `model_version` e `inference_ms`. La confianza está entre 0 y 1 y el tiempo de inferencia se expresa en milisegundos. Los campos faltantes, valores fuera de rango y números no finitos se rechazan con una respuesta `4xx`.

## Pruebas sobre la URL pública

Los siguientes comandos se ejecutan desde la raíz del proyecto con `requests` instalado. El simulador y las pruebas son clientes del servicio remoto.

### Contrato, validación y funcionamiento general

```powershell
.\.venv\Scripts\python.exe tests\smoke_test.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --final --output test-results\smoke_publico.json
```

Verifica las rutas, el contrato de `/predict`, un historial de 125 muestras, el rechazo de entradas inválidas y solicitudes concurrentes. Introduce datos de prueba con identificadores propios. Las respuestas `422` generadas a propósito cuentan como errores HTTP en `/metrics`.

### Reinicio y conservación exacta del historial

Antes de reiniciar:

```powershell
.\.venv\Scripts\python.exe tests\persistence_check.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --phase before
```

El script crea un robot de prueba con 125 registros y guarda la cantidad y el SHA-256 de su historial en `test-results/persistence.json`.

En Render, abrir el servicio y seleccionar **Manual Deploy > Restart service**. Esperar a que `/health` vuelva a responder correctamente. Después ejecutar:

```powershell
.\.venv\Scripts\python.exe tests\persistence_check.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --phase after
```

Usar la misma carpeta y conservar `test-results/persistence.json` entre ambas fases. El resultado esperado es `PASS`: misma cantidad y mismo contenido. El script compara los registros; el reinicio se realiza en Render y debe acompañarse de su confirmación o evento de despliegue. El uptime permite comprobar el nuevo arranque.

### Carga y latencias desde el cliente

```powershell
.\.venv\Scripts\python.exe prueba_carga.py
```

Envía 40 solicitudes a `/predict` con un máximo de 8 clientes simultáneos. Verifica las respuestas y que el servicio siga activo; muestra p50 y p95 y guarda `resultado_carga.json`. Esta prueba utiliza predicciones sin almacenar muestras nuevas.

Es una prueba acotada de concurrencia; no establece la capacidad máxima del servicio. Las latencias se miden desde el cliente e incluyen la red y la apertura de conexiones. Difieren del tiempo interno de inferencia del modelo.

### Comprobar el recorrido de los datos

```powershell
.\.venv\Scripts\python.exe scripts\probar_conexion.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --output test-results\conexion_publica.json
```

Comprueba que se crean y recuperan las mismas muestras y que `/predict` no inserta telemetría. Las consultas de `neon/verificar_datos.sql` permiten inspeccionar la tabla desde Neon.

## Modelo de aprendizaje automático

El entrenamiento utiliza 14.400 muestras sintéticas de 40 flotas generadas con el simulador. Las etiquetas proceden de su estado interno de salud. Las variables usadas por el modelo son `speed`, `battery`, `motor_temp`, `vibration`, `motor_current` y `obstacle_distance`.

La separación usa `GroupShuffleSplit` por `fleet_id`, con 24 flotas de entrenamiento, 8 de validación y 8 de prueba. Ninguna flota aparece en dos particiones. El preprocesamiento se ajusta dentro de cada pipeline y se excluyen los identificadores, el tiempo y la posición de las variables predictoras.

| Clasificador | F1 macro de validación |
|---|---:|
| Regresión logística | 0,9223 |
| Random Forest | 0,9159 |

Se seleccionó regresión logística por el resultado de validación. Tras ajustar el ganador con entrenamiento y validación, obtuvo **F1 macro 0,9417** en el conjunto reservado, frente a **0,1718** de la línea base de clase mayoritaria.

El pipeline versionado está en `models/model.joblib`; `models/metadata.json` registra características, particiones, versiones, métricas y hashes. El EDA, las distribuciones, la comparación y la matriz de confusión están en [reports/ML_REPORT.md](reports/ML_REPORT.md) y en los demás archivos de `reports/`.

Para reproducir el entrenamiento, instalar las dependencias completas y ejecutar:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe ml\generate_fleets.py --fleets 40 --robots 6 --steps 60 --seed 606
.\.venv\Scripts\python.exe ml\train_model.py --seed 606 --version v1
```

Estos comandos regeneran los datos, el modelo y los informes locales. El despliegue utiliza el modelo ya versionado. La telemetría recibida por la API no reentrena el modelo.

Una evaluación adicional del modelo desplegado puede ejecutarse con las dependencias completas instaladas:

```powershell
.\.venv\Scripts\python.exe ml\evaluate_fleet.py --api https://aci606-cloud-fleet-challenge-6opj.onrender.com --seed 20261108 --robots 8 --steps 40 --output test-results\flota_no_vista.json
```

Genera muestras con otra semilla e identificadores nuevos y consulta el modelo remoto. El resultado depende de la flota utilizada; no anticipa el resultado de la evaluación privada del docente.

## Resultados de los ensayos

| Comprobación | Resultado observado |
|---|---|
| Smoke test remoto completo | Aprobado; contrato y rutas operativas |
| Entradas inválidas | 12 casos rechazados con `422`; servicio activo después |
| Persistencia tras un reinicio real de Render | 125 registros del robot de prueba idénticos antes y después; SHA-256 coincidente |
| Flota operativa | Los seis robots conservaron todas sus muestras anteriores al reinicio y superaron 100 registros por robot |
| Concurrencia desde el PC del cliente | 40/40 predicciones correctas, 8 clientes simultáneos, cero errores |
| Latencia de esa prueba de carga | p50: 208,78 ms; p95: 551,89 ms |
| Flota sintética adicional consultando la API | 320 predicciones, semilla 20261108; F1 macro 0,9342 frente a 0,0932 de la línea base mayoritaria aprendida en entrenamiento y validación |
| Acceso desde otros dispositivos | Dashboard abierto desde un celular y desde el equipo de otra persona |

Son resultados de ensayos concretos. Las latencias varían con la red y la carga; la calidad depende de la distribución de la flota. Los informes `reports/POSTGRES_VERIFICATION.json` y `reports/postgres_smoke.json` corresponden a verificaciones locales anteriores con PostgreSQL y están separados de las pruebas remotas descritas aquí.

## Despliegue en Render y Neon

1. Crear una base PostgreSQL en Neon y obtener su cadena de conexión desde **Connect**. Se puede usar conexión con pooling, conservando sus parámetros TLS.
2. Crear un **Web Service** de Python en Render, conectado a este repositorio y a la rama `main`.
3. Dejar vacío **Root Directory**, porque `app/`, `models/` y `requirements.txt` están en la raíz.
4. Configurar los siguientes comandos y variables de entorno.
5. Desplegar y comprobar `/health`, `/docs` y `/dashboard`. Activar el despliegue automático desde `main`.

| Configuración de Render | Valor |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |
| Python | `3.12.12` |
| `PYTHON_VERSION` | `3.12.12` |
| `MODEL_PATH` | `models/model.joblib` |
| `DATABASE_URL` | Cadena privada de conexión a PostgreSQL de Neon |

`render.yaml` describe la configuración del servicio. La API adapta las URL `postgresql://` de Neon al driver psycopg 3. SQLAlchemy usa `pool_pre_ping=True` para comprobar las conexiones antes de reutilizarlas.

La cadena real de conexión se configura en el entorno de Render. `.env.example` contiene únicamente el formato de referencia y `.gitignore` excluye `.env` y el entorno virtual.

En el plan gratuito, Render puede suspender el servicio tras 15 minutos sin tráfico y el siguiente acceso puede tardar alrededor de un minuto. Antes de una demostración, abrir `/health` y esperar la respuesta. Un reinicio vuelve a cargar el modelo; PostgreSQL conserva los datos. El uptime y los contadores HTTP pertenecen al proceso y comienzan de nuevo con cada arranque.

## Organización del repositorio

| Ruta | Contenido |
|---|---|
| `app/` | API, persistencia, carga del modelo y observabilidad |
| `dashboard/` | Panel web |
| `simulator/` | Generación y envío de telemetría |
| `ml/` | Generación de flotas, entrenamiento y evaluación |
| `models/` | Pipeline y metadatos versionados |
| `reports/` | EDA, métricas, gráficos y verificaciones |
| `tests/` | Pruebas del servicio y de persistencia |
| `scripts/` | Comprobaciones de conexión |
| `neon/` | Consultas SQL de verificación |
| `docs/` | Arquitectura y contrato de la API |
| `prueba_carga.py` | Prueba remota de concurrencia |

La implementación se integró desde `feature/plataforma-cloud` mediante el pull request #1 y su merge a `main`. La actualización del README y la prueba de carga se incorporan como cambios posteriores.

Para ejecutar las pruebas automatizadas locales con las dependencias de desarrollo:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Referencias

- [Starter del docente](https://github.com/DrOscarL/aci606-cloud-fleet-challenge).
- Pauta del Ejercicio 4, ACI606 Cloud Computing.
- [FastAPI en Render](https://render.com/docs/deploy-fastapi).
- [Planes gratuitos de Render](https://render.com/docs/free).
- [SQLAlchemy con Neon](https://neon.com/docs/guides/sqlalchemy).
- [GroupShuffleSplit de scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html).

Implementación preparada con asistencia de Codex y verificada mediante los ensayos descritos.
