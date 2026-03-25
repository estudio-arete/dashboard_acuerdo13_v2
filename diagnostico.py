import requests, json, os, time
from datetime import datetime, timezone

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

def api_get(token, path, params=None):
    time.sleep(0.2)
    r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, params=params or {})
    if r.status_code not in [200, 201]: return {}
    return r.json()

print('🔐 Autenticando...')
token = get_token()
print('✅ Token OK\n')

# ── 1. Estructura completa de un member ──────────────────────────────────────
print('='*60)
print('1. ESTRUCTURA COMPLETA DE UN MEMBER')
print('='*60)
data = api_get(token, '/api/v2/host/members', {'page': 0, 'pageSize': 5})
members = data.get('payload', [])
if members:
    m = members[0]
    print(f'Campos disponibles en member: {sorted(m.keys())}')
    print(f'\nEjemplo (primer member):')
    print(f'  firstName: {m.get("firstName")}')
    print(f'  lastName: {m.get("lastName")}')
    print(f'  firstSeen: {m.get("firstSeen")}')
    print(f'  lastSeen: {m.get("lastSeen")}')
    print(f'  visits: {m.get("visits")}')
    print(f'  customerTags: {[t["name"] for t in m.get("customerTags", [])]}')
    print(f'  customerFields: {m.get("customerFields")}')

# ── 2. Estructura de membresías activas ──────────────────────────────────────
print('\n' + '='*60)
print('2. MEMBRESÍAS ACTIVAS — CAMPOS COMPLETOS')
print('='*60)

# Find a member with active memberships
found = False
for m in members[:20]:
    mid = m['id']
    mems = api_get(token, f'/api/v2/host/members/{mid}/bought-memberships/active', {'page': 0, 'pageSize': 5})
    payload = mems.get('payload', [])
    if payload:
        print(f'\nMember: {m.get("firstName")} {m.get("lastName")}')
        print(f'Todos los campos de bought-membership: {sorted(payload[0].keys())}')
        mem = payload[0]
        print(f'\nCampos clave:')
        print(f'  type: {mem.get("type")}')
        print(f'  autoRenewing: {mem.get("autoRenewing")}')
        print(f'  paymentMethod: {mem.get("paymentMethod")}')
        print(f'  paymentMethodType: {mem.get("paymentMethodType")}')
        print(f'  price: {mem.get("price")}')
        print(f'  amount: {mem.get("amount")}')
        print(f'  monthlyPrice: {mem.get("monthlyPrice")}')
        print(f'  usedSessions: {mem.get("usedSessions")}')
        print(f'  usageLimitForSessions: {mem.get("usageLimitForSessions")}')
        print(f'  startDate: {mem.get("startDate")}')
        print(f'  endDate: {mem.get("endDate")}')
        print(f'  membership.id: {mem.get("membership", {}).get("id")}')
        print(f'  membership.name: {mem.get("membership", {}).get("name")}')
        print(f'  membership.price: {mem.get("membership", {}).get("price")}')
        print(f'  membership.monthlyPrice: {mem.get("membership", {}).get("monthlyPrice")}')
        print(f'  membership.amount: {mem.get("membership", {}).get("amount")}')
        print(f'  declinedRenewal: {mem.get("declinedRenewal")}')
        print(f'\nJSON completo primera membresía:')
        print(json.dumps(payload[0], indent=2, ensure_ascii=False)[:800])
        found = True
        break

# ── 3. Catálogo de membresías con precios ────────────────────────────────────
print('\n' + '='*60)
print('3. CATÁLOGO DE MEMBRESÍAS — PRECIOS')
print('='*60)
cat = api_get(token, '/api/v2/host/memberships', {'page': 0, 'pageSize': 20})
for m in cat.get('payload', [])[:8]:
    print(f'  {m.get("name")} → precio:{m.get("price")} monthlyPrice:{m.get("monthlyPrice")} amount:{m.get("amount")} campos:{sorted(m.keys())}')

# ── 4. Sessions de un member — checkedIn ─────────────────────────────────────
print('\n' + '='*60)
print('4. SESSIONS — CAMPO checkedIn')
print('='*60)
for m in members[:10]:
    mid = m['id']
    sessions = api_get(token, f'/api/v2/host/members/{mid}/sessions', {'page': 0, 'pageSize': 5})
    payload = sessions.get('payload', [])
    if payload:
        s = payload[0]
        print(f'\nMember: {m.get("firstName")} {m.get("lastName")}')
        print(f'  Campos de session booking: {sorted(s.keys())}')
        print(f'  checkedIn: {s.get("checkedIn")}')
        print(f'  paymentMethod: {s.get("paymentMethod")}')
        print(f'  session.startsAt: {s.get("session", {}).get("startsAt")}')
        print(f'  session.teacher: {s.get("session", {}).get("teacher")}')
        break

# ── 5. Nuevo endpoint members con filtros ────────────────────────────────────
print('\n' + '='*60)
print('5. ENDPOINT POST MEMBERS CON FILTROS')
print('='*60)
r = requests.post(f'{BASE}/api/v2/host/members',
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    json={'page': 0, 'pageSize': 3, 'hasActiveMembership': True},
    params={'page': 0, 'pageSize': 3}
)
print(f'Status: {r.status_code}')
if r.status_code == 200:
    d = r.json()
    print(f'Total con hasActiveMembership:True: {d.get("pagination", {}).get("totalCount")}')
    if d.get('payload'):
        print(f'Campos disponibles: {sorted(d["payload"][0].keys())}')

# Try without body
r2 = requests.post(f'{BASE}/api/v2/host/members',
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    json={'page': 0, 'pageSize': 3}
)
print(f'\nPOST sin filtros status: {r2.status_code}')
if r2.status_code == 200:
    d2 = r2.json()
    print(f'Total: {d2.get("pagination", {}).get("totalCount")}')
    if d2.get('payload'):
        print(f'Campos disponibles en POST: {sorted(d2["payload"][0].keys())}')

print('\n✅ Diagnóstico completo')
