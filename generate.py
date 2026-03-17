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

print('Autenticando...')
token = get_token()
print('Token obtenido')

headers = {'Authorization': f'Bearer {token}'}

# Probar POST /host/members/list
print('Probando POST /host/members/list...')
r = requests.post(f'{BASE}/api/v2/host/members/list', headers=headers, json={})
print('Status:', r.status_code)
print('Respuesta:', r.text[:1000])

# Probar GET con detalle del error
print('\nProbando GET /host/members...')
r2 = requests.get(f'{BASE}/api/v2/host/members', headers=headers)
print('Status:', r2.status_code)
print('Respuesta:', r2.text[:1000])

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><h1>Debug</h1></body></html>')

print('Listo')
