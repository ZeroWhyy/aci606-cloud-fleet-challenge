# ACI606 - Cloud Fleet: API con escritura en PostgreSQL

**URL pública: PENDIENTE.** Reemplaza esta línea con la URL real de Render después del despliegue.

Este repositorio contiene el SERVIDOR. El cliente de robots se ejecuta aparte y envía muestras nuevas por HTTP. Cada muestra aceptada se confirma en PostgreSQL antes de devolver su `record_id`. El panel consulta esa misma base a través de la API.

## Cómo se comunican las partes

| Parte | Acción |
|---|---|
| Cliente / simulador | Genera una muestra NUEVA y llama POST /telemetry en Render |
| API en Render | Valida, ejecuta el modelo, hace INSERT y COMMIT en PostgreSQL de Neon |
| Respuesta de la API | Devuelve accepted=true, stored=true y el record_id que asignó PostgreSQL |
| Historial / panel | Hace SELECT en PostgreSQL y devuelve los registros persistidos |
| Modelo ML | Lee model.joblib para predecir; no usa un CSV como base operativa |

**No hay telemetría precargada.** Una base nueva empieza vacía. `data/training.csv` no se incluye en la entrega de despliegue. Los datos sintéticos de entrenamiento se generan únicamente si ejecutas los scripts ML opcionales.

## 1. Subir los archivos a tu GitHub

1. Extrae `Cloud_Fleet_Completo.zip`. Debes ver directamente `app`, `dashboard`, `models`, `requirements.txt` y `render.yaml`.
2. Haz un fork del [starter del profesor](https://github.com/DrOscarL/aci606-cloud-fleet-challenge), o abre tu copia si ya existe.
3. Crea una rama llamada `feature/plataforma-cloud` desde `main`.
4. En esa rama entra a **Add file > Upload files**. Arrastra el CONTENIDO del ZIP extraído, conservando las carpetas. No subas el ZIP comprimido ni una carpeta contenedora adicional.
5. Confirma los cambios, por ejemplo con el mensaje `Implement persistent API, inference and live telemetry`.
6. Abre un pull request desde esa rama hacia `main` de TU repositorio y usa **Create a merge commit / Merge pull request**. Así la rama y el merge quedan en tu historial real.

En `main`, verifica `app/main.py`, `app/db.py`, `models/model.joblib` y `models/metadata.json`. El modelo debe estar en Git: es pequeño y ya está entrenado. No se requiere importar un bundle.

Si GitHub no reemplaza un archivo por estar idéntico, es normal; si muestra un error de carga, resuélvelo antes de desplegar. Con el ZIP completo son menos de 100 archivos y ninguno se acerca al límite por archivo del navegador.

## 2. Crear la base en Neon

1. Entra a https://console.neon.tech y crea un proyecto.
2. Abre **Connect** y copia la conexión PostgreSQL completa, empezando por `postgresql://`.
3. Conserva `sslmode=require` y los demás parámetros que Neon entregue. Puedes usar la conexión con pooling.
4. La contraseña va SOLO en la variable `DATABASE_URL` de Render; no en GitHub, ni en el cliente.

No se importa un CSV. Al arrancar, la API crea automáticamente la tabla `telemetry` vacía. `neon/verificar_datos.sql` contiene consultas para comprobar las muestras después de enviarlas.

## 3. Conectar Render con GitHub y Neon

En https://dashboard.render.com selecciona **New > Web Service**, conecta TU repositorio y configura:

| Campo | Valor |
|---|---|
| Runtime | Python 3 |
| Branch | main |
| Root Directory | Vacío; app/ y requirements.txt deben estar en la raíz |
| Build Command | pip install -r requirements.txt |
| Start Command | uvicorn app.main:app --host 0.0.0.0 --port $PORT |
| Health Check Path | /health |
| Plan | Free, si está disponible |
| Auto Deploy | Activado para main |

Variables de entorno:

| Clave | Valor |
|---|---|
| PYTHON_VERSION | 3.12.12 |
| MODEL_PATH | models/model.joblib |
| DATABASE_URL | La cadena REAL y COMPLETA de Neon |

La API acepta la URL original de Neon y selecciona psycopg 3 automáticamente. Si falta `DATABASE_URL`, el arranque falla con un mensaje claro: ya no se cambia silenciosamente a una base local. En Render se exige PostgreSQL.

Despliega y espera a que aparezca activo. Abre `https://TU-SERVICIO.onrender.com/health`. Debe devolver `status: ok`, `database: ok`, `storage: postgresql` y `version: 1.1.0`. Después abre `/dashboard`. Al inicio estará vacío hasta recibir muestras.

## 4. Ejecutar el cliente y enviar datos nuevos

Descarga y extrae el archivo separado `Cloud_Fleet_Cliente.zip` en tu PC.

1. Abre `API_URL.txt` con Bloc de notas y pega solo tu URL BASE de Render, sin `/dashboard` ni `/health`.
2. Ejecuta `INICIAR_CLIENTE_WINDOWS.bat`. Requiere Python 3.10 o superior; prepara un entorno con requests.
3. El cliente genera muestras nuevas y las envía a la API. Cada respuesta debe mostrar `guardado id=... estado=...`.
4. Abre el dashboard de tu URL de Render y comprueba que aumenta el número de muestras.

También puedes usar una terminal dentro de la carpeta del cliente:

```bash
python -m pip install -r requirements.txt
python cliente.py --api https://TU-SERVICIO.onrender.com --robots 6
```

El simulador original del profesor sigue siendo compatible; desde este repositorio funciona así:

```bash
python simulator/fleet_simulator.py --api https://TU-SERVICIO.onrender.com --robots 6 --timeout 120
```

No necesitas subir el cliente a Render. Mientras envía datos debe estar ejecutándose en tu PC o Codespaces. Al detenerlo dejan de llegar muestras, pero las confirmadas permanecen en Neon.

## 5. Demostrar escritura y lectura de los mismos datos

En la carpeta del cliente ejecuta `PROBAR_CONEXION_WINDOWS.bat`, o:

```bash
python probar_conexion.py --api https://TU-SERVICIO.onrender.com
```

La prueba exige PostgreSQL, crea un robot único, confirma que antes no existe, envía tres muestras por POST, recibe sus IDs y recupera las tres por GET. Compara cada valor y cada ID, y verifica que `/predict` calcula sin insertar telemetría. Guarda `resultado_conexion.json` e imprime una consulta SQL con el robot `CHK-...` real.

Copia esa consulta en **Neon > SQL Editor**. Deben aparecer los mismos tres IDs que mostró el cliente. Esta es la comprobación visible de cliente -> API -> Neon -> API -> cliente.

El script también está en este repositorio:

```bash
python scripts/probar_conexion.py --api https://TU-SERVICIO.onrender.com --output test-results/conexion_publica.json
```

## 6. Prueba final y reinicio remoto

Desde Codespaces o una terminal con las dependencias del servidor:

```bash
python tests/smoke_test.py --api https://TU-SERVICIO.onrender.com --final --output test-results/smoke_publico.json
python tests/persistence_check.py --api https://TU-SERVICIO.onrender.com --phase before
```

El primer comando exige inferencia, historial de 125 muestras, rechazo de entradas inválidas y concurrencia. El segundo guarda cantidad y hash de 125 registros de un robot único.

Reinicia el servicio en Render con **Restart service**, espera que `/health` responda y ejecuta:

```bash
python tests/persistence_check.py --api https://TU-SERVICIO.onrender.com --phase after
```

Debe indicar PASS y conservar el historial. Mantén el archivo local `test-results/persistence.json` entre ambas fases. Guarda evidencia real del reinicio y del resultado. Abre el panel desde otro dispositivo y revisa `/metrics` y los logs de Render.

## 7. Dejar el repositorio listo para entregar

Cambia la URL pendiente del README por la real. Agrega evidencia remota y haz un commit significativo adicional. No incluyas la cadena de conexión de Neon. La plantilla `ENTREGA_CHECKLIST.md` marca la parte remota como pendiente hasta que la ejecutes.

El código fue preparado con asistencia de Codex. La rama, el commit de carga, el merge y los cambios de configuración de tu repositorio se crean realmente al seguir estos pasos; no se adjunta un historial de estudiante inventado.

## Rutas y significado

| Ruta | Función |
|---|---|
| GET /health | Verifica conexión a la base y estado del modelo |
| POST /telemetry | Recibe y GUARDA una muestra nueva, con predicción y versión |
| GET /robots | Lee de la base la última muestra por robot |
| GET /robots/{id}/history | Lee el historial COMPLETO de la base; sin tope de 100 |
| POST /predict | Predice una muestra recibida; no la almacena |
| GET /metrics | Solicitudes, errores, latencias, uptime y número de registros en PostgreSQL |
| GET /dashboard | Panel con datos consultados a la API |
| GET /docs | Documentación interactiva |

## Modelo y reproducción opcional

El Pipeline `models/model.joblib` se carga una vez al arrancar. El entrenamiento usó 14.400 muestras de 40 flotas y GroupShuffleSplit por fleet_id (24/8/8 flotas para train/validation/test). Se compararon regresión logística (F1 macro validación 0,9223) y Random Forest (0,9159). Ganó regresión logística, con F1 macro reservado 0,9417 frente a 0,1718 de la línea base mayoritaria.

Los informes de EDA, comparación y matriz están en `reports/`. Son resultados de entrenamiento sintético, separados de la telemetría operativa. Para reproducirlos, opcionalmente:

```bash
python ml/generate_fleets.py --fleets 40 --robots 6 --steps 60 --seed 606
python ml/train_model.py --seed 606 --version v1
```

Estos comandos NO se ejecutan durante el despliegue ni cuando la API recibe peticiones. La API no importa el CSV a PostgreSQL y no lo consulta para mostrar robots.

## Verificación del paquete

Se ejecutan pruebas de contrato y una comprobación con PostgreSQL real local. El detalle del ensayo está en `reports/POSTGRES_VERIFICATION.json`: base inicialmente vacía, muestras nuevas por HTTP, lectura independiente por SQL y persistencia tras reiniciar la API. No es una cuenta Neon ni un servicio Render ya desplegado; esa comprobación remota se realiza con tu URL y los pasos anteriores.

Pruebas automatizadas:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Fuentes: pauta adjunta, starter del docente, [Render FastAPI](https://render.com/docs/deploy-fastapi), [Neon SQLAlchemy](https://neon.com/docs/guides/sqlalchemy) y [GitHub: subir archivos](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).
