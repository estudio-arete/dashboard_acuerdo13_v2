import requests
import json
import os
import time
from datetime import datetime, timezone

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
BASE = 'https://api.momence.com'
HOST_ID = 45937
MOMENCE_PROFILE_BASE = f'https://momence.com/dashboard/{HOST_ID}/customers'
TODAY = datetime.now(timezone.utc)
TODAY_STR = TODAY.strftime('%d/%m/%Y %H:%M')
TODAY_DATE = TODAY.date()

def get_token():
    r = requests.post(f'{BASE}/api/v2/auth/token', data={
        'grant_type': 'password', 'username': EMAIL, 'password': PASSWORD,
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET
    })
    r.raise_for_status()
    return r.json()['access_token']

def api_get(token, path, params=None):
    time.sleep(0.15)
    r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, params=params or {})
    if r.status_code == 429:
        time.sleep(3)
        r = requests.get(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, params=params or {})
    if r.status_code not in [200, 201]:
        return {}
    return r.json()

def api_post(token, path, body=None):
    time.sleep(0.15)
    try:
        r = requests.post(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'}, json=body or {})
        return r.status_code in [200, 201]
    except:
        return False

def api_delete(token, path):
    time.sleep(0.15)
    try:
        r = requests.delete(f'{BASE}{path}', headers={'Authorization': f'Bearer {token}'})
        return r.status_code in [200, 204]
    except:
        return False

def days_since(iso_str):
    if not iso_str: return None
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return max(0, (TODAY - dt).days)
    except: return None

def fetch_all_members(token):
    members, page = [], 0
    while True:
        data = api_get(token, '/api/v2/host/members', {'page': page, 'pageSize': 100})
        batch = data.get('payload', [])
        members.extend(batch)
        total = data.get('pagination', {}).get('totalCount', 0)
        if page % 5 == 0: print(f'  {len(members)}/{total} members...')
        if len(members) >= total or not batch: break
        page += 1
    return members

def fetch_all_tags(token):
    data = api_get(token, '/api/v2/host/tags', {'page': 0, 'pageSize': 100})
    return {t['name']: t['id'] for t in data.get('payload', [])}

def fetch_active_memberships(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/bought-memberships/active', {'page': 0, 'pageSize': 10})
    return data.get('payload', [])

def fetch_future_sessions(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/sessions', {'page': 0, 'pageSize': 10})
    sessions = data.get('payload', [])
    future = []
    for s in sessions:
        starts = s.get('session', {}).get('startsAt', '')
        if starts:
            try:
                dt = datetime.fromisoformat(starts.replace('Z', '+00:00'))
                if dt > TODAY: future.append({'dt': dt, 'session': s})
            except: pass
    future.sort(key=lambda x: x['dt'])
    return future

def fetch_last_note(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/notes', {'page': 0, 'pageSize': 3})
    notes = data.get('payload', [])
    return notes[0].get('content', '') if notes else ''

def assign_tag(token, mid, tag_id):
    return api_post(token, f'/api/v2/host/members/{mid}/tags', {'tagId': tag_id})

def remove_tag(token, mid, tag_id):
    return api_delete(token, f'/api/v2/host/members/{mid}/tags/{tag_id}')

def process_member(token, member, tag_ids):
    mid = member['id']
    tag_names = [t['name'] for t in member.get('customerTags', [])]
    tag_id_map = {t['name']: t['id'] for t in member.get('customerTags', [])}

    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    visits = member.get('visits', {}).get('totalVisits', 0)
    if not (set(tag_names) & RELEVANT) and visits < 3:
        return None

    active_mems = fetch_active_memberships(token, mid)
    future_sessions = fetch_future_sessions(token, mid)
    last_note = fetch_last_note(token, mid)

    # Auto tag logic
    is_manual_cash = 'MANUAL' in tag_names or 'CASH' in tag_names
    has_active = len(active_mems) > 0
    has_future = len(future_sessions) > 0
    days_inactive = days_since(member.get('lastSeen', '')) or 0
    is_intro_mem = any('intro' in m.get('membership', {}).get('name', '').lower() or
                       'prueba' in m.get('membership', {}).get('name', '').lower()
                       for m in active_mems)

    add_tags, remove_tags = [], []

    if (has_active and not is_intro_mem) or (has_future and not has_active) or (not has_active and not has_future and days_inactive <= 30):
        if 'Member' not in tag_names: add_tags.append('Member')
        if 'FORMER MEMBER' in tag_names: remove_tags.append('FORMER MEMBER')
        if 'member potencial' in tag_names and not is_intro_mem: remove_tags.append('member potencial')
    elif is_intro_mem or (not has_active and not has_future and days_inactive <= 30):
        if 'member potencial' not in tag_names: add_tags.append('member potencial')
    elif not has_active and not has_future and days_inactive > 30 and 'DUCK' not in tag_names and 'INFLU' not in tag_names:
        if 'FORMER MEMBER' not in tag_names: add_tags.append('FORMER MEMBER')
        if 'Member' in tag_names: remove_tags.append('Member')

    for tag_name in add_tags:
        tid = tag_ids.get(tag_name)
        if tid:
            if assign_tag(token, mid, tid): tag_names.append(tag_name)

    for tag_name in remove_tags:
        tid = tag_id_map.get(tag_name)
        if tid:
            if remove_tag(token, mid, tid):
                if tag_name in tag_names: tag_names.remove(tag_name)

    # Next class
    next_class, next_class_days = None, None
    if future_sessions:
        nc = future_sessions[0]
        dt = nc['dt']
        name = nc['session'].get('session', {}).get('name', '')
        next_class = dt.strftime('%d/%m %H:%M') + ' · ' + name.split('·')[0].strip()
        next_class_days = (dt.date() - TODAY_DATE).days

    # Membership summary
    membership_summary, renewal_days = '', None
    if active_mems:
        m = active_mems[0]
        mem_name = m.get('membership', {}).get('name', '')
        used = m.get('usedSessions', 0)
        total_limit = m.get('usageLimitForSessions')
        end_date = m.get('endDate', '')
        parts = [mem_name]
        if total_limit:
            left = total_limit - used
            parts.append(f'{left} clases restantes')
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                renewal_days = (dt.date() - TODAY_DATE).days
                parts.append(f'renueva en {renewal_days}d')
            except: pass
        membership_summary = ' · '.join(parts)

    return {
        'id': mid,
        'name': f"{member.get('firstName','')} {member.get('lastName','')}".strip(),
        'email': member.get('email', ''),
        'phone': member.get('phoneNumber', ''),
        'tags': tag_names,
        'visits': visits,
        'last_seen': member.get('lastSeen', ''),
        'days_inactive': days_inactive,
        'has_active': has_active,
        'has_future': has_future,
        'membership_summary': membership_summary,
        'renewal_days': renewal_days,
        'next_class': next_class,
        'next_class_days': next_class_days,
        'last_note': last_note,
        'momence_url': f'{MOMENCE_PROFILE_BASE}/{mid}',
        'added_tags': add_tags,
        'is_manual_cash': is_manual_cash,
    }

def build_tasks(members_data):
    tasks_today, tasks_week = [], []
    seen = set()

    for m in members_data:
        if not m: continue
        tags = m['tags']
        nc_days = m['next_class_days']
        email = m['email']

        # Sin PM + renovación próxima
        has_pm = 'PM' in tags or m['is_manual_cash']
        if not has_pm and m['has_active'] and m['renewal_days'] is not None and m['renewal_days'] <= 7:
            key = f"{email}_sin_metodo_pago"
            if key not in seen:
                seen.add(key)
                item = {'type':'sin_metodo_pago','name':m['name'],'email':email,
                        'detail':m['membership_summary'],'action':'Conseguir método de pago antes de la renovación',
                        'nc':m['next_class'],'nc_days':nc_days,'momence_url':m['momence_url'],'priority':2,'sd':nc_days if nc_days is not None else 99}
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Pack expirando
        if not m['has_active'] and m['has_future'] and nc_days is not None and nc_days <= 14:
            key = f"{email}_pack_expirando"
            if key not in seen:
                seen.add(key)
                item = {'type':'pack_expirando','name':m['name'],'email':email,
                        'detail':f"Última clase en {nc_days if nc_days > 0 else 'hoy'}d · {m['next_class']}",
                        'action':'Ofrecer renovación de pack — hablar en clase',
                        'nc':m['next_class'],'nc_days':nc_days,'momence_url':m['momence_url'],'priority':3,'sd':nc_days or 0}
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Intro journey
        if 'member potencial' in tags or 'introjourney' in tags:
            v = m['visits']
            if v >= 1:
                key = f"{email}_intro_journey"
                if key not in seen:
                    seen.add(key)
                    is_conv = v >= 2
                    item = {'type':'intro_journey','name':m['name'],'email':email,
                            'detail':f"Intro Journey · {v} visita{'s' if v!=1 else ''} · {m['membership_summary']}",
                            'action':'Convertir a member — hablar después de la clase' if is_conv else 'Seguimiento — preguntar cómo va',
                            'nc':m['next_class'],'nc_days':nc_days,'momence_url':m['momence_url'],
                            'priority':2 if is_conv else 4,'sd':nc_days if nc_days is not None else 99}
                    if nc_days == 0: tasks_today.append(item)
                    else: tasks_week.append(item)

    tasks_today.sort(key=lambda x: x['priority'])
    tasks_week.sort(key=lambda x: (x.get('sd',99), x['priority']))
    return tasks_today, tasks_week

def generate_html(members_data, tasks_today, tasks_week, stats):
    mj = json.dumps([m for m in members_data if m], ensure_ascii=False)
    tj = json.dumps(tasks_today, ensure_ascii=False)
    wj = json.dumps(tasks_week, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>aretē · gestión</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;color:#222323;background:#f5f5f5;min-height:100vh}}
.app{{padding:1rem;max-width:1100px;margin:0 auto}}
.topbar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;padding:0.75rem 1rem;border-radius:8px;background:#222323;color:#fff;flex-wrap:wrap;gap:8px}}
.brand{{font-size:16px;font-weight:500;letter-spacing:0.04em}}
.brand em{{font-weight:400;color:#847366;font-size:12px;margin-left:8px;font-style:normal}}
.update-info{{font-size:10px;color:#847366}}
.topbar-actions{{display:flex;gap:6px}}
.btn{{font-size:11px;padding:5px 10px;border:1px solid rgba(255,255,255,0.2);border-radius:6px;background:transparent;color:#fff;cursor:pointer}}
.btn:hover{{background:rgba(255,255,255,0.1)}}
.btn.primary{{background:#8e352d;border-color:#8e352d}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:1rem}}
.metric{{background:#fff;border-radius:8px;padding:0.65rem;text-align:center;border:1px solid #eee}}
.metric .n{{font-size:22px;font-weight:500;line-height:1.2}}
.metric .l{{font-size:10px;color:#847366;margin-top:2px;line-height:1.3}}
.red .n{{color:#a32d2d}}.amber .n{{color:#854f0b}}.green .n{{color:#3b6d11}}.blue .n{{color:#185fa5}}
.prog-wrap{{background:#fff;border-radius:8px;padding:0.75rem 1rem;margin-bottom:1rem;border:1px solid #eee}}
.prog-bar{{height:5px;background:#f0f0f0;border-radius:3px;overflow:hidden;margin-top:6px}}
.prog-fill{{height:100%;background:#639922;border-radius:3px;transition:width 0.5s}}
.prog-labels{{display:flex;justify-content:space-between;font-size:10px;color:#847366;margin-top:3px}}
.tabs-wrap{{background:#fff;border-radius:8px;border:1px solid #eee;overflow:hidden}}
.tabs{{display:flex;border-bottom:1px solid #eee;overflow-x:auto}}
.tab{{font-size:12px;padding:9px 14px;cursor:pointer;color:#847366;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;background:#fff}}
.tab.active{{color:#222323;font-weight:500;border-bottom-color:#8e352d}}
.tab:hover{{color:#222323}}
.tab-content{{display:none;padding:1rem}}
.tab-content.active{{display:block}}
.badge{{font-size:10px;background:#fcebeb;color:#a32d2d;padding:1px 5px;border-radius:100px;margin-left:3px}}
.badge.w{{background:#faeeda;color:#854f0b}}.badge.i{{background:#e6f1fb;color:#185fa5}}.badge.g{{background:#eaf3de;color:#3b6d11}}
.section-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem}}
.section-title{{font-size:13px;font-weight:500}}
.section-count{{font-size:11px;color:#847366}}
.filter-bar{{display:flex;gap:5px;margin-bottom:0.75rem;flex-wrap:wrap}}
.fb{{font-size:11px;padding:3px 9px;border:1px solid #eee;border-radius:100px;cursor:pointer;background:#fff;color:#847366}}
.fb.active{{background:#222323;color:#fff;border-color:#222323}}
.task-list{{display:flex;flex-direction:column;gap:5px;margin-bottom:1rem}}
.task{{display:flex;gap:10px;padding:10px 12px;border:1px solid #eee;border-radius:8px;background:#fff}}
.task.done{{opacity:0.4}}.task.done .tname{{text-decoration:line-through}}
.task.urg{{border-left:3px solid #e24b4a;background:#fffafa}}
.task.warn{{border-left:3px solid #ef9f27;background:#fffdf5}}
.task.info{{border-left:3px solid #378add;background:#f5f9ff}}
.task-chk{{flex-shrink:0;margin-top:2px}}
.task-chk input{{width:15px;height:15px;cursor:pointer;accent-color:#8e352d}}
.task-body{{flex:1;min-width:0}}
.task-top{{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:3px}}
.tname{{font-size:13px;font-weight:500}}
.tname a{{color:#222323;text-decoration:none}}
.tname a:hover{{color:#8e352d;text-decoration:underline}}
.tpill{{font-size:10px;padding:1px 6px;border-radius:100px;white-space:nowrap}}
.tp1{{background:#fcebeb;color:#a32d2d}}.tp2{{background:#faeeda;color:#854f0b}}
.tp3{{background:#e6f1fb;color:#185fa5}}.tp4{{background:#eeedfe;color:#3c3489}}
.tp5{{background:#f5f5f5;color:#847366}}
.tdetail{{font-size:11px;color:#847366;margin-bottom:3px}}
.taction{{font-size:12px;font-weight:500}}
.taction.r{{color:#a32d2d}}.taction.a{{color:#854f0b}}.taction.b{{color:#185fa5}}
.tmeta{{display:flex;align-items:center;gap:8px;margin-top:5px;flex-wrap:wrap}}
.tclass{{font-size:10px;color:#847366;padding:2px 7px;border:1px solid #eee;border-radius:100px;background:#f9f9f9}}
.tnote input{{font-size:11px;padding:3px 7px;border:1px solid #eee;border-radius:6px;background:#fff;color:#222323;width:180px}}
.tnote input:focus{{outline:none;border-color:#aaa}}
.toolbar{{display:flex;align-items:center;gap:6px;margin-bottom:0.75rem;flex-wrap:wrap}}
.search{{font-size:12px;padding:5px 9px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#222323;width:200px}}
.search:focus{{outline:none;border-color:#aaa}}
.tbl-wrap{{overflow-x:auto;border:1px solid #eee;border-radius:8px;max-height:500px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;min-width:700px}}
th{{font-size:10px;font-weight:500;color:#847366;text-align:left;padding:7px 9px;background:#f9f9f9;border-bottom:1px solid #eee;white-space:nowrap;position:sticky;top:0;z-index:1}}
td{{font-size:12px;padding:7px 9px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#fafafa}}
.pill{{display:inline-block;font-size:10px;padding:2px 7px;border-radius:100px;font-weight:500;white-space:nowrap;margin:1px}}
.p-ok{{background:#eaf3de;color:#3b6d11}}.p-warn{{background:#faeeda;color:#854f0b}}
.p-danger{{background:#fcebeb;color:#a32d2d}}.p-info{{background:#e6f1fb;color:#185fa5}}
.p-grey{{background:#f5f5f5;color:#847366}}.p-dark{{background:#222323;color:#fff}}
.p-purple{{background:#eeedfe;color:#3c3489}}
td input[type=text]{{font-size:11px;padding:2px 6px;border:1px solid transparent;border-radius:4px;background:transparent;color:#222323;width:100%;min-width:110px}}
td input[type=text]:hover{{border-color:#eee}}
td input[type=text]:focus{{outline:none;border-color:#ccc;background:#fff}}
td input[type=checkbox]{{width:13px;height:13px;cursor:pointer;accent-color:#8e352d}}
.member-link{{color:#222323;text-decoration:none;font-weight:500}}
.member-link:hover{{color:#8e352d;text-decoration:underline}}
.briefing-box{{background:#f9f9f9;border-radius:8px;padding:1rem;font-size:12px;line-height:1.9;white-space:pre-wrap;border:1px solid #eee;min-height:220px;margin-bottom:0.75rem;font-family:'Courier New',monospace;color:#222323}}
.save-bar{{display:flex;gap:8px;padding:0.75rem 1rem;border-top:1px solid #eee;background:#fafafa}}
.save-bar .btn{{background:#fff;color:#222323;border:1px solid #ddd}}
.save-bar .btn.primary{{background:#222323;color:#fff;border-color:#222323}}
.toast{{position:fixed;bottom:1.5rem;right:1.5rem;background:#222323;color:#fff;padding:10px 18px;border-radius:8px;font-size:12px;opacity:0;transition:opacity 0.3s;pointer-events:none;z-index:999;box-shadow:0 4px 12px rgba(0,0,0,0.15)}}
.toast.show{{opacity:1}}
.empty{{padding:2.5rem;text-align:center;color:#847366;font-size:12px}}
@media(max-width:650px){{.metrics{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class="app">
  <div class="topbar">
    <div>
      <div class="brand">aretē <em>· sistema de gestión</em></div>
      <div class="update-info">Última actualización: {TODAY_STR} UTC · Se actualiza automáticamente 6 veces al día</div>
    </div>
    <div class="topbar-actions">
      <button class="btn" onclick="document.getElementById('notes-in').click()">📂 Cargar notas</button>
      <input type="file" id="notes-in" accept=".json" style="display:none" onchange="importNotes(event)">
      <button class="btn primary" onclick="saveNotes()">💾 Guardar notas</button>
    </div>
  </div>

  <div class="metrics">
    <div class="metric green"><div class="n">{stats['active_members']}</div><div class="l">Members activos</div></div>
    <div class="metric red"><div class="n" id="m-hoy">—</div><div class="l">Tareas hoy</div></div>
    <div class="metric amber"><div class="n" id="m-semana">—</div><div class="l">Esta semana</div></div>
    <div class="metric red"><div class="n">{stats['no_payment_method']}</div><div class="l">Sin método pago</div></div>
    <div class="metric blue"><div class="n">{stats['intro_count']}</div><div class="l">Intro Journey</div></div>
    <div class="metric amber"><div class="n">{stats['potenciales']}</div><div class="l">Potenciales</div></div>
  </div>

  <div class="prog-wrap">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:11px;font-weight:500">Objetivo 300 members</span>
      <span style="font-size:11px;color:#847366">{stats['active_members']} / 300 — {min(100,round(stats['active_members']/3))}%</span>
    </div>
    <div class="prog-bar"><div class="prog-fill" style="width:{min(100,round(stats['active_members']/3))}%"></div></div>
    <div class="prog-labels"><span>0</span><span>300</span></div>
  </div>

  <div class="tabs-wrap">
    <div class="tabs">
      <div class="tab active" onclick="showTab('hoy')">🔴 Hoy<span class="badge" id="b-hoy">—</span></div>
      <div class="tab" onclick="showTab('semana')">🟡 Semana<span class="badge w" id="b-semana">—</span></div>
      <div class="tab" onclick="showTab('members')">Members<span class="badge g">{stats['active_members']}</span></div>
      <div class="tab" onclick="showTab('intro')">Intro<span class="badge i">{stats['intro_count']}</span></div>
      <div class="tab" onclick="showTab('potenciales')">Potenciales<span class="badge w">{stats['potenciales']}</span></div>
      <div class="tab" onclick="showTab('briefing')">Briefing</div>
    </div>

    <div id="tab-hoy" class="tab-content active">
      <div class="section-hdr">
        <div class="section-title">Obligatorio hoy — una tarea por persona</div>
        <div class="section-count" id="hoy-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="filterList('today','',this)">Todos</button>
        <button class="fb" onclick="filterList('today','sin_metodo_pago',this)">⚠️ Sin método</button>
        <button class="fb" onclick="filterList('today','pack_expirando',this)">📦 Packs hoy</button>
        <button class="fb" onclick="filterList('today','intro_journey',this)">🎯 Intro</button>
      </div>
      <div class="task-list" id="list-hoy"></div>
    </div>

    <div id="tab-semana" class="tab-content">
      <div class="section-hdr">
        <div class="section-title">Esta semana — ordenado por fecha de próxima clase</div>
        <div class="section-count" id="semana-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="filterList('week','',this)">Todos</button>
        <button class="fb" onclick="filterList('week','sin_metodo_pago',this)">⚠️ Sin método</button>
        <button class="fb" onclick="filterList('week','pack_expirando',this)">📦 Packs</button>
        <button class="fb" onclick="filterList('week','intro_journey',this)">🎯 Intro</button>
      </div>
      <div class="task-list" id="list-semana"></div>
    </div>

    <div id="tab-members" class="tab-content">
      <div class="toolbar">
        <input class="search" placeholder="Buscar nombre, email..." oninput="filterTbl('tbl-members',this.value)">
        <select style="font-size:12px;padding:5px 8px;border:1px solid #ddd;border-radius:6px;background:#fff" onchange="filterByTag(this.value)">
          <option value="">Todos</option>
          <option value="Member">Member</option>
          <option value="FORMER MEMBER">Former Member</option>
          <option value="member potencial">Potencial</option>
          <option value="introjourney">Intro Journey</option>
          <option value="DUCK">DUCK</option>
          <option value="MANUAL">Manual</option>
          <option value="CASH">Cash</option>
        </select>
      </div>
      <div class="tbl-wrap">
        <table id="tbl-members">
          <thead><tr><th>Nombre</th><th>Tags</th><th>Membresía</th><th>Última visita</th><th>Próxima clase</th><th>Visitas</th><th>Última nota Momence</th><th>Contactado</th><th>Nota equipo</th></tr></thead>
          <tbody id="body-members"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-intro" class="tab-content">
      <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-intro',this.value)"></div>
      <div class="tbl-wrap">
        <table id="tbl-intro">
          <thead><tr><th>Nombre</th><th>Email</th><th>Visitas</th><th>Estado</th><th>Próxima clase</th><th>Membresía</th><th>Contactado</th><th>Notas</th></tr></thead>
          <tbody id="body-intro"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-potenciales" class="tab-content">
      <div class="toolbar">
        <input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-pot',this.value)">
        <span style="font-size:11px;color:#847366">Vinieron pero no han convertido en más de 30 días</span>
      </div>
      <div class="tbl-wrap">
        <table id="tbl-pot">
          <thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Última visita</th><th>Visitas</th><th>Días inactivo</th><th>Contactado</th><th>Notas</th></tr></thead>
          <tbody id="body-pot"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-briefing" class="tab-content">
      <div class="briefing-box" id="briefing-text"></div>
      <button class="btn primary" style="width:100%;margin-top:0" onclick="copyBriefing()">Copiar briefing</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const NOTES={{}};
const MEMBERS={mj};
const TASKS_TODAY={tj};
const TASKS_WEEK={wj};
let fT='',fW='';

function n(k){{return NOTES[k]||{{}};}}
function setN(k,f,v){{if(!NOTES[k])NOTES[k]={{}};NOTES[k][f]=v;}}
function esc(s){{return String(s||'').replace(/\\\\/g,'\\\\\\\\').replace(/'/g,"\\\\'").replace(/"/g,'&quot;');}}
function nf(k,f,ph){{const v=(n(k)[f]||'').replace(/"/g,'&quot;');return`<input type="text" placeholder="${{ph||'Nota...'}}" value="${{v}}" onchange="setN('${{esc(k)}}','${{f}}',this.value)">`;}}
function ck(k,f){{return`<input type="checkbox" ${{n(k)[f]?'checked':''}} onchange="setN('${{esc(k)}}','${{f}}',this.checked)">`;}}
function pl(t,c){{return`<span class="pill ${{c}}">${{t}}</span>`;}}
function filterTbl(id,q){{document.querySelectorAll(`#${{id}} tbody tr`).forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none');}}
function toast(m){{const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2500);}}

function showTab(t){{
  ['hoy','semana','members','intro','potenciales','briefing'].forEach((n,i)=>{{
    document.querySelectorAll('.tab')[i]?.classList.toggle('active',n===t);
  }});
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  const el=document.getElementById('tab-'+t);
  if(el)el.classList.add('active');
  if(t==='briefing')renderBriefing();
}}

const TM={{
  sin_metodo_pago:{{label:'⚠️ Sin método',pill:'tp2',cls:'warn',acls:'a'}},
  pack_expirando:{{label:'📦 Pack acaba',pill:'tp3',cls:'info',acls:'b'}},
  intro_journey:{{label:'🎯 Intro Journey',pill:'tp4',cls:'info',acls:'b'}},
  pago_critico:{{label:'💳 Pago crítico',pill:'tp1',cls:'urg',acls:'r'}},
}};

function taskHTML(t){{
  const key=t.email+'_'+t.type;
  const done=n(key).done||false;
  const note=(n(key).note||'').replace(/"/g,'&quot;');
  const m=TM[t.type]||{{label:'',pill:'tp5',cls:'',acls:''}};
  const nc=t.nc?`<span class="tclass">📅 ${{t.nc}}</span>`:'';
  const sk=esc(key);
  const nameEl=t.momence_url?`<a href="${{t.momence_url}}" target="_blank">${{t.name}}</a>`:t.name;
  return`<div class="task ${{m.cls}} ${{done?'done':''}}" id="tk_${{key.replace(/[^a-z0-9]/gi,'_')}}">
    <div class="task-chk"><input type="checkbox" ${{done?'checked':''}} onchange="toggleDone('${{sk}}',this.checked)"></div>
    <div class="task-body">
      <div class="task-top"><span class="tname">${{nameEl}}</span><span class="tpill ${{m.pill}}">${{m.label}}</span></div>
      <div class="tdetail">${{t.detail}}</div>
      <div class="taction ${{m.acls}}">${{t.action}}</div>
      <div class="tmeta">${{nc}}<div class="tnote"><input type="text" placeholder="Nota rápida..." value="${{note}}" onchange="setN('${{sk}}','note',this.value)"></div></div>
    </div>
  </div>`;
}}

function toggleDone(key,checked){{
  setN(key,'done',checked);
  const el=document.getElementById('tk_'+key.replace(/[^a-z0-9]/gi,'_'));
  if(el)el.classList.toggle('done',checked);
  updateCounts();
}}

function updateCounts(){{
  const td=TASKS_TODAY.filter(t=>n(t.email+'_'+t.type).done).length;
  const tw=TASKS_WEEK.filter(t=>n(t.email+'_'+t.type).done).length;
  document.getElementById('hoy-count').textContent=`${{td}} / ${{TASKS_TODAY.length}} completadas`;
  document.getElementById('semana-count').textContent=`${{tw}} / ${{TASKS_WEEK.length}} completadas`;
  document.getElementById('m-hoy').textContent=TASKS_TODAY.length-td||'0';
  document.getElementById('m-semana').textContent=TASKS_WEEK.length-tw||'0';
  document.getElementById('b-hoy').textContent=TASKS_TODAY.length-td;
  document.getElementById('b-semana').textContent=TASKS_WEEK.length-tw;
}}

function filterList(which,type,btn){{
  if(which==='today')fT=type; else fW=type;
  if(btn){{btn.closest('.filter-bar').querySelectorAll('.fb').forEach(b=>b.classList.remove('active'));btn.classList.add('active');}}
  const tasks=which==='today'?TASKS_TODAY:TASKS_WEEK;
  const filtered=type?tasks.filter(t=>t.type===type):tasks;
  const cid=which==='today'?'list-hoy':'list-semana';
  document.getElementById(cid).innerHTML=filtered.length?filtered.map(taskHTML).join(''):'<div class="empty">Sin tareas en esta categoría</div>';
}}

const TAG_COLORS={{'Member':'p-dark','FORMER MEMBER':'p-grey','member potencial':'p-ok','introjourney':'p-info','DUCK':'p-warn','PAGO FALLIDO':'p-danger','PM':'p-ok','MANUAL':'p-warn','CASH':'p-warn','ENG':'p-info','INFLU':'p-grey','NO CANCELAR!':'p-danger'}};
const SHOW_TAGS=['Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PM','PAGO FALLIDO','NO CANCELAR!','ENG'];

function renderMembers(){{
  const ms=MEMBERS.filter(m=>m.tags.some(t=>['Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH'].includes(t)));
  document.getElementById('body-members').innerHTML=ms.length?ms.map(m=>{{
    const tags=m.tags.filter(t=>SHOW_TAGS.includes(t)).map(t=>`<span class="pill ${{TAG_COLORS[t]||'p-grey'}}">${{t}}</span>`).join('');
    const ls=m.last_seen?new Date(m.last_seen).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit'}}):'—';
    const dc=m.days_inactive;
    const dcColor=dc>21?'#a32d2d':dc>14?'#854f0b':'#3b6d11';
    const noteVal=(n(m.email).note||'').replace(/"/g,'&quot;');
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="max-width:160px">${{tags}}</td>
      <td style="font-size:11px;max-width:180px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px;color:${{dcColor}}">${{ls}}<div style="font-size:10px">${{dc}}d inactivo</div></td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="text-align:center;font-weight:500">${{m.visits}}</td>
      <td style="font-size:10px;color:#847366;font-style:italic;max-width:140px">${{m.last_note?'"'+m.last_note.slice(0,60)+(m.last_note.length>60?'…':'')+'"':'—'}}</td>
      <td style="text-align:center">${{ck(m.email,'contactado')}}</td>
      <td><input type="text" placeholder="Nota equipo..." value="${{noteVal}}" onchange="setN('${{esc(m.email)}}','note',this.value)" style="min-width:130px"></td>
    </tr>`;
  }}).join(''):'<tr><td colspan="9" class="empty">Sin datos</td></tr>';
}}

function filterByTag(tag){{
  document.querySelectorAll('#tbl-members tbody tr').forEach(tr=>{{
    tr.style.display=!tag||tr.textContent.includes(tag)?'':'none';
  }});
}}

function renderIntro(){{
  const intros=MEMBERS.filter(m=>m.tags.includes('introjourney')||m.tags.includes('member potencial'));
  document.getElementById('body-intro').innerHTML=intros.length?intros.sort((a,b)=>b.visits-a.visits).map(m=>{{
    const v=m.visits;
    const [estado,ecls]=v>=3?['Clase 3 — CONVERTIR HOY','p-danger']:v===2?['Clase 2 — preparar conversión','p-warn']:v===1?['Clase 1 — seguimiento','p-info']:['Aún no ha venido','p-grey'];
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="font-size:11px;color:#847366">${{m.email}}</td>
      <td style="text-align:center;font-weight:500">${{v}}</td>
      <td>${{pl(estado,ecls)}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="text-align:center">${{ck(m.email,'c_intro')}}</td>
      <td>${{nf(m.email,'n_intro')}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="8" class="empty">Sin Intro Journeys activos</td></tr>';
}}

function renderPotenciales(){{
  const pots=MEMBERS.filter(m=>!m.tags.includes('Member')&&!m.tags.includes('introjourney')&&!m.tags.includes('member potencial')&&m.days_inactive>30&&m.visits>0).sort((a,b)=>b.visits-a.visits);
  document.getElementById('body-pot').innerHTML=pots.length?pots.map(m=>{{
    const ls=m.last_seen?new Date(m.last_seen).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit',year:'2-digit'}}):'—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="font-size:11px;color:#847366">${{m.email}}</td>
      <td style="font-size:11px">${{m.phone||'—'}}</td>
      <td style="font-size:11px">${{ls}}</td>
      <td style="text-align:center;font-weight:500">${{m.visits}}</td>
      <td style="text-align:center;color:#847366">${{m.days_inactive}}d</td>
      <td style="text-align:center">${{ck(m.email,'c_pot')}}</td>
      <td>${{nf(m.email,'n_pot')}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="8" class="empty">Sin potenciales</td></tr>';
}}

function renderBriefing(){{
  const today=new Date().toLocaleDateString('es-ES',{{weekday:'long',day:'numeric',month:'long'}});
  const hp=TASKS_TODAY.filter(t=>!n(t.email+'_'+t.type).done);
  const wp=TASKS_WEEK.filter(t=>!n(t.email+'_'+t.type).done);
  let txt=`Briefing aretē · ${{today}}\\n${{Array(45).fill('─').join('')}}\\n\\n`;
  txt+=`RESUMEN\\nMembers activos: {stats['active_members']} / 300 (${{Math.round({stats['active_members']}/3)}}%)\\nTareas hoy pendientes: ${{hp.length}} · Esta semana: ${{wp.length}}\\n\\n`;
  const sinM=hp.filter(t=>t.type==='sin_metodo_pago');
  if(sinM.length){{txt+=`SIN MÉTODO DE PAGO — HOY (${{sinM.length}})\\n`;sinM.forEach(t=>txt+=`· ${{t.name}} — ${{t.detail}}\\n`);txt+='\\n';}}
  const packs=hp.filter(t=>t.type==='pack_expirando');
  if(packs.length){{txt+=`PACKS TERMINAN HOY (${{packs.length}})\\n`;packs.forEach(t=>txt+=`· ${{t.name}} — ${{t.nc||''}}\\n`);txt+='\\n';}}
  const intros=hp.filter(t=>t.type==='intro_journey');
  if(intros.length){{txt+=`INTRO JOURNEY — ACCIÓN HOY (${{intros.length}})\\n`;intros.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}\\n`);txt+='\\n';}}
  if(wp.length){{
    txt+=`PRÓXIMAS ACCIONES ESTA SEMANA\\n`;
    wp.slice(0,10).forEach(t=>{{const nota=n(t.email+'_'+t.type).note;txt+=`· ${{t.name}} — ${{t.action}}${{t.nc?' ('+t.nc+')':''}}${{nota?' — '+nota:''}}\\n`;}});
    if(wp.length>10)txt+=`· ...y ${{wp.length-10}} más\\n`;
  }}
  txt+=`\\n${{Array(45).fill('─').join('')}}\\nGenerado automáticamente · aretē · {TODAY_STR}`;
  document.getElementById('briefing-text').textContent=txt;
}}

function copyBriefing(){{navigator.clipboard.writeText(document.getElementById('briefing-text').textContent).then(()=>toast('Briefing copiado'));}}

function saveNotes(){{
  const b=new Blob([JSON.stringify(NOTES,null,2)],{{type:'application/json'}});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(b);
  a.download='arete_notas_'+new Date().toISOString().slice(0,10)+'.json';
  a.click();
  toast('Notas guardadas');
}}

function importNotes(e){{
  const f=e.target.files[0];if(!f)return;
  const r=new FileReader();
  r.onload=ev=>{{
    try{{Object.assign(NOTES,JSON.parse(ev.target.result));renderAll();toast('Notas cargadas: '+Object.keys(NOTES).length+' personas');}}
    catch{{toast('Error al cargar notas');}}
  }};
  r.readAsText(f);e.target.value='';
}}

function renderAll(){{
  filterList('today',fT);filterList('week',fW);
  renderMembers();renderIntro();renderPotenciales();
  updateCounts();
}}

renderAll();
</script>
</body>
</html>'''

def main():
    print('🔐 Autenticando...')
    token = get_token()
    print('✅ Token obtenido')

    print('🏷️  Cargando tags...')
    tag_ids = fetch_all_tags(token)
    print(f'   {len(tag_ids)} tags encontrados')

    print('👥 Cargando todos los members...')
    all_members = fetch_all_members(token)
    print(f'✅ {len(all_members)} members cargados')

    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    relevant_members = []
    for m in all_members:
        member_tag_names = {t['name'] for t in m.get('customerTags', [])}
        visits = m.get('visits', {}).get('totalVisits', 0)
        if bool(member_tag_names & RELEVANT) or visits >= 3:
            relevant_members.append(m)

    print(f'   Procesando {len(relevant_members)} members relevantes...')

    members_data = []
    for i, member in enumerate(relevant_members):
        if i % 20 == 0:
            print(f'   {i}/{len(relevant_members)}...')
        if i > 0 and i % 80 == 0:
            print('   Refrescando token...')
            token = get_token()
        result = process_member(token, member, tag_ids)
        if result:
            members_data.append(result)

    print(f'✅ {len(members_data)} members procesados')

    active_count = sum(1 for m in members_data if 'Member' in m['tags'])
    intro_count = sum(1 for m in members_data if 'introjourney' in m['tags'] or 'member potencial' in m['tags'])
    potencial_count = sum(1 for m in members_data if
        not any(t in m['tags'] for t in ['Member','introjourney','member potencial']) and
        m['days_inactive'] > 30 and m['visits'] > 0)
    no_pm = sum(1 for m in members_data if
        'Member' in m['tags'] and
        not any(t in m['tags'] for t in ['PM','MANUAL','CASH']))

    stats = {
        'total_members': len(members_data),
        'active_members': active_count,
        'intro_count': intro_count,
        'potenciales': potencial_count,
        'no_payment_method': no_pm,
    }

    print('📋 Construyendo tareas...')
    tasks_today, tasks_week = build_tasks(members_data)
    print(f'   Hoy: {len(tasks_today)} · Semana: {len(tasks_week)}')

    print('🏗️  Generando dashboard...')
    html = generate_html(members_data, tasks_today, tasks_week, stats)

    os.makedirs('output', exist_ok=True)
    with open('output/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print('✅ Dashboard generado')
    print(f'   Members activos: {active_count} / 300')
    print(f'   Intro Journey: {intro_count}')
    print(f'   Potenciales: {potencial_count}')
    print(f'   Sin método pago: {no_pm}')
    print(f'   Tareas hoy: {len(tasks_today)}')
    print(f'   Tareas semana: {len(tasks_week)}')

if __name__ == '__main__':
    main()
