import requests, json, os

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
BASE = 'https://api.momence.com'

def get_token():
    r = requests.post(f'{BASE}/api/v2/auth/token', data={
        'grant_type': 'password', 'username': EMAIL, 'password': PASSWORD,
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET
    })
    r.raise_for_status()
    return r.json()['access_token']

token = get_token()
headers = {'Authorization': f'Bearer {token}'}

# Traer un member específico (Maribel Vergara, id 28197551)
member_id = 28197551

print('--- MEMBRESÍAS ACTIVAS ---')
r = requests.get(f'{BASE}/api/v2/host/members/{member_id}/bought-memberships', headers=headers, params={'page': 0, 'pageSize': 10})
print('Status:', r.status_code)
print(r.text[:2000])

print('\n--- RESERVAS FUTURAS ---')
r2 = requests.get(f'{BASE}/api/v2/host/members/{member_id}/session-bookings', headers=headers, params={'page': 0, 'pageSize': 5})
print('Status:', r2.status_code)
print(r2.text[:2000])

print('\n--- NOTAS ---')
r3 = requests.get(f'{BASE}/api/v2/host/members/{member_id}/notes', headers=headers, params={'page': 0, 'pageSize': 5})
print('Status:', r3.status_code)
print(r3.text[:1000])

print('\n--- TAGS DISPONIBLES ---')
r4 = requests.get(f'{BASE}/api/v2/host/tags', headers=headers, params={'page': 0, 'pageSize': 50})
print('Status:', r4.status_code)
print(r4.text[:2000])

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><h1>Debug API</h1></body></html>')
print('Listo')
