import requests
import json
import os

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

def get(token, path):
    r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'})
    r.raise_for_status()
    return r.json()

def post(token, path, body=None):
    r = requests.post(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, json=body or {})
    r.raise_for_status()
    return r.json()

print('Autenticando...')
token = get_token()
print('Token obtenido')

# GET sin parámetros
print('Probando GET /host/members...')
members_get = get(token, '/api/v2/host/members')
print('GET respuesta:', json.dumps(members_get, indent=2, ensure_ascii=False)[:500])

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><h1>arete OK</h1><pre>' + json.dumps(members_get, indent=2, ensure_ascii=False)[:2000] + '</pre></body></html>')

print('Listo')
