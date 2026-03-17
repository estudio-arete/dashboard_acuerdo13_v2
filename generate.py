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

# GET con paginación
print('Probando GET /host/members con paginación...')
r = requests.get(f'{BASE}/api/v2/host/members', headers=headers, params={'page': 0, 'pageSize': 10})
print('Status:', r.status_code)
print('Respuesta:', r.text[:2000])

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><pre>' + r.text[:5000] + '</pre></body></html>')

print('Listo')
