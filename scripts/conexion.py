"""HTTP connection shared by the client and the round-trip check."""
from pathlib import Path
import time
from urllib.parse import urlsplit
import requests
HERE = Path(__file__).resolve().parent

def get_api_url(value=None, interactive=False):
    path = HERE / 'API_URL.txt'
    if not value and path.exists():
        value = path.read_text(encoding='utf-8-sig').strip()
    if (not value or 'PEGA_AQUI' in value) and interactive:
        value = input('Pega la URL base de Render (https://...onrender.com): ').strip()
        if value: path.write_text(value + '\n', encoding='utf-8')
    if not value or 'PEGA_AQUI' in value:
        raise ValueError('Configura API_URL.txt o pasa --api https://TU-SERVICIO.onrender.com')
    url = value.strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
        raise ValueError('La URL debe ser http(s)://host, sin credenciales.')
    if parts.path not in ('', '/') or parts.query or parts.fragment:
        raise ValueError('Usa la URL base, sin /dashboard, /docs ni /health.')
    return url

def wait_for_api(session, base, seconds=180):
    deadline = time.monotonic() + seconds
    print('Conectando con la API; si está suspendida puede tardar en despertar...', flush=True)
    last = 'sin respuesta'
    while time.monotonic() < deadline:
        try:
            response = session.get(base + '/health', timeout=min(30, max(1, deadline-time.monotonic())))
            if response.status_code == 200:
                value = response.json()
                if value.get('status') == 'ok':
                    print('API conectada. Base:', value.get('storage'), '| Modelo:', value.get('model_version'), flush=True)
                    return value
            last = 'HTTP ' + str(response.status_code)
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError('La API no está lista: ' + last)
