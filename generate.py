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
member_id = 28197551

print('--- MEMBRESÍAS ACTIVAS ---')
r = requests.get(f'{BASE}/api/v2/host/members/{member_id}/bought-memberships/active', headers=headers, params={'page': 0, 'pageSize': 10})
print('Status:', r.status_code)
print(r.text[:2000])

print('\n--- RESERVAS ---')
r2 = requests.get(f'{BASE}/api/v2/host/members/{member_id}/sessions', headers=headers, params={'page': 0, 'pageSize': 5})
print('Status:', r2.status_code)
print(r2.text[:2000])

os.makedirs('output', exist_ok=True)
with open('output/index.html', 'w') as f:
    f.write('<html><body><h1>Debug</h1></body></html>')
print('Listo')
