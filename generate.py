import requests
import json
import os
from datetime import datetime

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
BASE = 'https://api.momence.com'

def get_token():
    r = requests.post(f'{BASE}/api/v2/auth/token', data={
        'grant_type': 'password',
        'username': EMAIL,
        'password': PASSWORD,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    })
    r.raise_for_status()
    return r.json()['access_token']

def api(token, path, params=None):
    r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, params=params or {})
    r.raise_for_status()
    return r.json()

print('Autenticando...')
token = get_token()
print('Token obtenido correctamente')

members = api(token, '/api/v2/host/members', {'limit': 10})
print(f'Respuesta members: {json.dumps(members, indent=2, ensure_ascii=False)[:1000]}')

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><h1>arete OK</h1><p>API conectada correctamente</p></body></html>')

print('Listo')
