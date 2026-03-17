import requests
import json
import os
import time
from datetime import datetime, timezone

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
GH_REPO = os.environ.get('GH_REPO', 'estudio-arete/dashboard_acuerdo13_v2')
GH_PAT = os.environ.get('GH_PAT', '')
BASE = 'https://api.momence.com'
HOST_ID = 45937
MOMENCE_PROFILE_BASE = f'https://momence.com/dashboard/{HOST_ID}/crm'
TODAY = datetime.now(timezone.utc)
TODAY_STR = TODAY.strftime('%d/%m/%Y %H:%M')
TODAY_DATE = TODAY.date()

PLATFORM_TAGS = {'classpass', 'WELLHUB', 'urbansportsclub'}
PLATFORM_EMAILS = ['classpass.com', 'urbansportsclub.com', 'members.classpass.com', 'gympass.com', 'wellhub.com']

def is_platform_user(member):
    email = member.get('email', '').lower()
    if any(p in email for p in ['classpass', 'urbansports', 'wellhub', 'gympass']):
        return True
    tag_names = {t['name'].lower() for t in member.get('customerTags', [])}
    if tag_names & {'classpass', 'wellhub', 'urbansportsclub', 'gympass'}:
        return True
    return False

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

def fetch_all_sessions(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/sessions', {'page': 0, 'pageSize': 20})
    sessions = data.get('payload', [])
    past, future = [], []
    for s in sessions:
        starts = s.get('session', {}).get('startsAt', '')
        if starts:
            try:
                dt = datetime.fromisoformat(starts.replace('Z', '+00:00'))
                if dt > TODAY:
                    future.append({'dt': dt, 'data': s})
                else:
                    past.append({'dt': dt, 'data': s})
            except: pass
    future.sort(key=lambda x: x['dt'])
    past.sort(key=lambda x: x['dt'], reverse=True)
    return past, future

def fetch_notes(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/notes', {'page': 0, 'pageSize': 5})
    return data.get('payload', [])

def assign_tag(token, mid, tag_id):
    return api_post(token, f'/api/v2/host/members/{mid}/tags', {'tagId': tag_id})

def remove_tag(token, mid, tag_id):
    return api_delete(token, f'/api/v2/host/members/{mid}/tags/{tag_id}')

def format_session(s_obj):
    if not s_obj: return None
    dt = s_obj['dt']
    name = s_obj['data'].get('session', {}).get('name', '')
    return dt.strftime('%d/%m %H:%M') + ' · ' + name.split('·')[0].strip()

def process_member(token, member, tag_ids):
    mid = member['id']
    tag_names = [t['name'] for t in member.get('customerTags', [])]
    tag_id_map = {t['name']: t['id'] for t in member.get('customerTags', [])}
    is_platform = is_platform_user(member)

    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    visits = member.get('visits', {}).get('totalVisits', 0)
    if not (set(tag_names) & RELEVANT) and visits < 3:
        return None

    active_mems = fetch_active_memberships(token, mid)
    past_sessions, future_sessions = fetch_all_sessions(token, mid)
    notes = fetch_notes(token, mid)

    # Filter platform memberships
    own_active_mems = [m for m in active_mems if not any(
        p in m.get('membership', {}).get('name', '').lower()
        for p in ['classpass', 'wellhub', 'gympass', 'urban']
    )]

    has_active = len(own_active_mems) > 0
    has_future = len(future_sessions) > 0
    days_inactive = days_since(member.get('lastSeen', '')) or 0

    is_intro_mem = any(
        'intro' in m.get('membership', {}).get('name', '').lower() or
        'prueba' in m.get('membership', {}).get('name', '').lower()
        for m in own_active_mems
    )

    # Auto tag logic (skip platform-only users for member tagging)
    add_tags, remove_tags = [], []
    if not is_platform:
        if (has_active and not is_intro_mem) or (has_future and not has_active) or (not has_active and not has_future and days_inactive <= 30):
            if 'Member' not in tag_names: add_tags.append('Member')
            if 'FORMER MEMBER' in tag_names: remove_tags.append('FORMER MEMBER')
        elif is_intro_mem:
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

    # Session info
    next_session = future_sessions[0] if future_sessions else None
    prev_session = past_sessions[0] if past_sessions else None
    next_class = format_session(next_session)
    prev_class = format_session(prev_session)
    next_class_days = (next_session['dt'].date() - TODAY_DATE).days if next_session else None

    # Intro journey classes info
    intro_classes_used = 0
    intro_classes_total = 0
    intro_classes_left = 0
    intro_expiry_days = None
    if is_intro_mem:
        m = own_active_mems[0]
        intro_classes_used = m.get('usedSessions', 0)
        intro_classes_total = m.get('usageLimitForSessions') or 3
        intro_classes_left = max(0, intro_classes_total - intro_classes_used)
        end_date = m.get('endDate', '')
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                intro_expiry_days = (dt.date() - TODAY_DATE).days
            except: pass

    # Membership summary
    membership_summary, renewal_days = '', None
    if own_active_mems:
        m = own_active_mems[0]
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

    # Notes
    last_note = notes[0].get('content', '') if notes else ''
    all_notes = [{'content': n.get('content',''), 'date': n.get('createdAt','')} for n in notes[:3]]

    has_pm = 'PM' in tag_names or 'MANUAL' in tag_names or 'CASH' in tag_names

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
        'is_platform': is_platform,
        'is_intro': is_intro_mem,
        'is_manual_cash': 'MANUAL' in tag_names or 'CASH' in tag_names,
        'has_pm': has_pm,
        'membership_summary': membership_summary,
        'renewal_days': renewal_days,
        'next_class': next_class,
        'next_class_days': next_class_days,
        'prev_class': prev_class,
        'intro_classes_used': intro_classes_used,
        'intro_classes_total': intro_classes_total,
        'intro_classes_left': intro_classes_left,
        'intro_expiry_days': intro_expiry_days,
        'last_note': last_note,
        'all_notes': all_notes,
        'momence_url': f'{MOMENCE_PROFILE_BASE}/{mid}',
        'added_tags': add_tags,
    }

def build_tasks(members_data):
    tasks_today, tasks_week = [], []
    seen = set()

    for m in members_data:
        if not m or m['is_platform']: continue
        tags = m['tags']
        nc_days = m['next_class_days']
        email = m['email']

        # Sin PM + renovación próxima (solo propios, no plataforma)
        if not m['has_pm'] and m['has_active'] and m['renewal_days'] is not None and m['renewal_days'] <= 7:
            key = f"{email}_sin_metodo_pago"
            if key not in seen:
                seen.add(key)
                item = {
                    'type': 'sin_metodo_pago',
                    'name': m['name'], 'email': email,
                    'detail': m['membership_summary'],
                    'action': 'Conseguir método de pago antes de la renovación',
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'momence_url': m['momence_url'],
                    'priority': 2, 'sd': nc_days if nc_days is not None else 99
                }
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Pack expirando (solo pago directo, no plataforma)
        if not m['has_active'] and m['has_future'] and nc_days is not None and nc_days <= 14:
            key = f"{email}_pack_expirando"
            if key not in seen:
                seen.add(key)
                item = {
                    'type': 'pack_expirando',
                    'name': m['name'], 'email': email,
                    'detail': f"Última clase en {'hoy' if nc_days == 0 else str(nc_days)+'d'} · {m['next_class']}",
                    'action': 'Ofrecer renovación de pack — hablar en clase',
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'momence_url': m['momence_url'],
                    'priority': 3, 'sd': nc_days or 0
                }
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Intro journey — ordenado por urgencia
        if m['is_intro'] and m['visits'] >= 1:
            key = f"{email}_intro_journey"
            if key not in seen:
                seen.add(key)
                left = m['intro_classes_left']
                used = m['intro_classes_used']
                if left == 0:
                    urgency = 1
                    action = 'URGENTE — No le quedan clases. Contactar hoy para convertir'
                elif left == 1:
                    urgency = 2
                    action = 'Le queda 1 clase — hablar en la próxima para convertir'
                elif used >= 2:
                    urgency = 3
                    action = 'Convertir a member — hablar después de la clase'
                else:
                    urgency = 4
                    action = 'Seguimiento — preguntar cómo va el intro'

                item = {
                    'type': 'intro_journey',
                    'name': m['name'], 'email': email,
                    'detail': f"Intro · {used}/{m['intro_classes_total']} clases · {left} restantes · caduca en {m['intro_expiry_days']}d",
                    'action': action,
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'prev_class': m['prev_class'],
                    'momence_url': m['momence_url'],
                    'priority': urgency, 'sd': nc_days if nc_days is not None else 99
                }
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

    tasks_today.sort(key=lambda x: x['priority'])
    tasks_week.sort(key=lambda x: (x.get('sd', 99), x['priority']))
    return tasks_today, tasks_week

def generate_html(members_data, tasks_today, tasks_week, stats):
    mj = json.dumps([m for m in members_data if m], ensure_ascii=False)
    tj = json.dumps(tasks_today, ensure_ascii=False)
    wj = json.dumps(tasks_week, ensure_ascii=False)
    gh_repo = GH_REPO

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>aretē · gestión</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;color:#222323;background:#f5f5f5}}
.app{{padding:1rem;max-width:1100px;margin:0 auto}}
.topbar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;padding:0.75rem 1rem;border-radius:8px;background:#222323;color:#fff;flex-wrap:wrap;gap:8px}}
.brand{{font-size:16px;font-weight:500;letter-spacing:0.04em}}
.brand em{{font-weight:400;color:#847366;font-size:12px;margin-left:8px;font-style:normal}}
.update-info{{font-size:10px;color:#847366}}
.topbar-actions{{display:flex;gap:6px;align-items:center}}
.btn{{font-size:11px;padding:5px 10px;border:1px solid rgba(255,255,255,0.2);border-radius:6px;background:transparent;color:#fff;cursor:pointer;white-space:nowrap}}
.btn:hover{{background:rgba(255,255,255,0.1)}}
.btn.rust{{background:#8e352d;border-color:#8e352d}}
.btn.rust:hover{{background:#a03e35}}
.btn-refresh{{font-size:11px;padding:5px 12px;border:1px solid #8e352d;border-radius:6px;background:#8e352d;color:#fff;cursor:pointer;display:flex;align-items:center;gap:5px}}
.btn-refresh:hover{{background:#a03e35}}
.btn-refresh.loading{{opacity:0.7;cursor:not-allowed}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:1rem}}
.metric{{background:#fff;border-radius:8px;padding:0.65rem;text-align:center;border:1px solid #eee}}
.metric .n{{font-size:22px;font-weight:500;line-height:1.2}}
.metric .l{{font-size:10px;color:#847366;margin-top:2px;line-height:1.3}}
.red .n{{color:#a32d2d}}.amber .n{{color:#854f0b}}.green .n{{color:#3b6d11}}.blue .n{{color:#185fa5}}
.prog-wrap{{background:#fff;border-radius:8px;padding:0.75rem 1rem;margin-bottom:1rem;border:1px solid #eee}}
.prog-bar{{height:5px;background:#f0f0f0;border-radius:3px;overflow:hidden;margin-top:6px}}
.prog-fill{{height:100%;background:#639922;border-radius:3px}}
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
.member-link{{color:#222323;text-decoration:none;font-weight:500}}
.member-link:hover{{color:#8e352d;text-decoration:underline}}
.note-link{{font-size:10px;color:#8e352d;text-decoration:none;margin-left:4px}}
.note-link:hover{{text-decoration:underline}}
.briefing-box{{background:#f9f9f9;border-radius:8px;padding:1rem;font-size:12px;line-height:1.9;white-space:pre-wrap;border:1px solid #eee;min-height:220px;margin-bottom:0.75rem;font-family:'Courier New',monospace}}
.subtabs{{display:flex;gap:4px;margin-bottom:0.75rem}}
.stab{{font-size:11px;padding:4px 12px;border:1px solid #eee;border-radius:6px;cursor:pointer;background:#fff;color:#847366}}
.stab.active{{background:#222323;color:#fff;border-color:#222323}}
.toast{{position:fixed;bottom:1.5rem;right:1.5rem;background:#222323;color:#fff;padding:10px 18px;border-radius:8px;font-size:12px;opacity:0;transition:opacity 0.3s;pointer-events:none;z-index:999;box-shadow:0 4px 12px rgba(0,0,0,0.2)}}
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
      <div class="update-info" id="update-label">Última actualización: {TODAY_STR} UTC</div>
    </div>
    <div class="topbar-actions">
      <button class="btn-refresh" id="refresh-btn" onclick="triggerRefresh()">
        <span id="refresh-icon">↻</span> Actualizar ahora
      </button>
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
        <div class="section-title">Esta semana — en orden de urgencia y próxima clase</div>
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
      <div class="subtabs">
        <button class="stab active" onclick="showSubtab('activos',this)">Activos ({stats['active_members']})</button>
        <button class="stab" onclick="showSubtab('refrescar',this)">A refrescar ({stats['to_refresh']})</button>
      </div>
      <div id="subtab-activos">
        <div class="toolbar">
          <input class="search" placeholder="Buscar nombre, email..." oninput="filterTbl('tbl-activos',this.value)">
        </div>
        <div class="tbl-wrap">
          <table id="tbl-activos">
            <thead><tr><th>Nombre</th><th>Tags</th><th>Membresía</th><th>Última visita</th><th>Próxima clase</th><th>Visitas</th><th>Última nota</th></tr></thead>
            <tbody id="body-activos"></tbody>
          </table>
        </div>
      </div>
      <div id="subtab-refrescar" style="display:none">
        <div class="toolbar">
          <input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-refrescar',this.value)">
          <span style="font-size:11px;color:#847366">Members activos que llevan más de 14 días sin venir</span>
        </div>
        <div class="tbl-wrap">
          <table id="tbl-refrescar">
            <thead><tr><th>Nombre</th><th>Tags</th><th>Membresía</th><th>Última visita</th><th>Días inactivo</th><th>Próxima clase</th><th>Notas Momence</th></tr></thead>
            <tbody id="body-refrescar"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="tab-intro" class="tab-content">
      <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-intro',this.value)"></div>
      <div class="tbl-wrap">
        <table id="tbl-intro">
          <thead><tr><th>Nombre</th><th>Clases</th><th>Urgencia</th><th>Clase anterior</th><th>Próxima clase</th><th>Caduca en</th><th>Notas Momence</th></tr></thead>
          <tbody id="body-intro"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-potenciales" class="tab-content">
      <div class="toolbar">
        <input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-pot',this.value)">
        <span style="font-size:11px;color:#847366">Excluyendo ClassPass, Wellhub y plataformas</span>
      </div>
      <div class="tbl-wrap">
        <table id="tbl-pot">
          <thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Última visita</th><th>Visitas</th><th>Días inactivo</th><th>Notas Momence</th></tr></thead>
          <tbody id="body-pot"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-briefing" class="tab-content">
      <div class="briefing-box" id="briefing-text"></div>
      <button onclick="copyBriefing()" style="width:100%;padding:8px;border:none;border-radius:6px;background:#222323;color:#fff;font-size:12px;cursor:pointer;margin-top:0">Copiar briefing</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const MEMBERS={mj};
const TASKS_TODAY={tj};
const TASKS_WEEK={wj};
const GH_REPO='{gh_repo}';
const GH_ACTIONS_URL='https://github.com/estudio-arete/dashboard_acuerdo13_v2/actions/workflows/update.yml';
let fT='',fW='';

function toast(m,dur=2500){{const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),dur);}}
function filterTbl(id,q){{document.querySelectorAll(`#${{id}} tbody tr`).forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none');}}
function pl(t,c){{return`<span class="pill ${{c}}">${{t}}</span>`;}}

function showTab(t){{
  ['hoy','semana','members','intro','potenciales','briefing'].forEach((n,i)=>{{
    document.querySelectorAll('.tab')[i]?.classList.toggle('active',n===t);
  }});
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t)?.classList.add('active');
  if(t==='briefing') renderBriefing();
}}

function showSubtab(name, btn){{
  document.getElementById('subtab-activos').style.display = name==='activos'?'block':'none';
  document.getElementById('subtab-refrescar').style.display = name==='refrescar'?'block':'none';
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
}}

function triggerRefresh(){{
  window.open(GH_ACTIONS_URL, '_blank');
  toast('Se abre GitHub Actions — haz clic en Run workflow');
}}

const TM={{
  sin_metodo_pago:{{label:'⚠️ Sin método',pill:'tp2',cls:'warn',acls:'a'}},
  pack_expirando:{{label:'📦 Pack acaba',pill:'tp3',cls:'info',acls:'b'}},
  intro_journey:{{label:'🎯 Intro Journey',pill:'tp4',cls:'info',acls:'b'}},
}};

function taskHTML(t){{
  const m=TM[t.type]||{{label:'',pill:'tp5',cls:'',acls:''}};
  const nc=t.nc?`<span class="tclass">📅 ${{t.nc}}</span>`:'';
  const pc=t.prev_class?`<span class="tclass" style="color:#aaa">⬅️ ${{t.prev_class}}</span>`:'';
  const nameEl=t.momence_url?`<a href="${{t.momence_url}}" target="_blank">${{t.name}}</a>`:t.name;
  const urgClass = t.priority===1?'urg':t.priority<=2?'warn':'info';
  return`<div class="task ${{urgClass}}">
    <div class="task-body">
      <div class="task-top"><span class="tname">${{nameEl}}</span><span class="tpill ${{m.pill}}">${{m.label}}</span></div>
      <div class="tdetail">${{t.detail}}</div>
      <div class="taction ${{m.acls}}">${{t.action}}</div>
      <div class="tmeta">${{pc}}${{nc}}</div>
    </div>
  </div>`;
}}

function updateCounts(){{
  document.getElementById('m-hoy').textContent=TASKS_TODAY.length||'0';
  document.getElementById('m-semana').textContent=TASKS_WEEK.length||'0';
  document.getElementById('b-hoy').textContent=TASKS_TODAY.length;
  document.getElementById('b-semana').textContent=TASKS_WEEK.length;
  document.getElementById('hoy-count').textContent=`${{TASKS_TODAY.length}} tareas`;
  document.getElementById('semana-count').textContent=`${{TASKS_WEEK.length}} tareas`;
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
const SHOW_TAGS=['Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PM','ENG','NO CANCELAR!'];

function tagPills(tags){{return tags.filter(t=>SHOW_TAGS.includes(t)).map(t=>`<span class="pill ${{TAG_COLORS[t]||'p-grey'}}">${{t}}</span>`).join('');}}

function noteCell(m){{
  const note = m.last_note || '';
  const link = `<a href="${{m.momence_url}}" target="_blank" class="note-link">+ añadir nota</a>`;
  return note ? `<span style="font-style:italic;color:#847366">"${{note.slice(0,50)}}${{note.length>50?'…':''}}"</span> ${{link}}` : link;
}}

function renderActivos(){{
  const ms = MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform);
  document.getElementById('body-activos').innerHTML = ms.length ? ms.map(m=>{{
    const ls = m.last_seen ? new Date(m.last_seen).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit'}}) : '—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td>${{tagPills(m.tags)}}</td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px;color:${{m.days_inactive>21?'#a32d2d':m.days_inactive>14?'#854f0b':'#3b6d11'}}">${{ls}} <span style="font-size:10px">(${{m.days_inactive}}d)</span></td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="text-align:center;font-weight:500">${{m.visits}}</td>
      <td style="font-size:11px">${{noteCell(m)}}</td>
    </tr>`;
  }}).join('') : '<tr><td colspan="7" class="empty">Sin members activos</td></tr>';
}}

function renderRefrescar(){{
  const ms = MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform&&m.days_inactive>14).sort((a,b)=>b.days_inactive-a.days_inactive);
  document.getElementById('body-refrescar').innerHTML = ms.length ? ms.map(m=>{{
    const ls = m.last_seen ? new Date(m.last_seen).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit',year:'2-digit'}}) : '—';
    const dcColor = m.days_inactive>21?'#a32d2d':'#854f0b';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td>${{tagPills(m.tags)}}</td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px">${{ls}}</td>
      <td style="font-weight:500;color:${{dcColor}}">${{m.days_inactive}}d</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="font-size:11px">${{noteCell(m)}}</td>
    </tr>`;
  }}).join('') : '<tr><td colspan="7" class="empty">Todos los members han venido recientemente</td></tr>';
}}

function renderIntro(){{
  const intros = MEMBERS.filter(m=>m.is_intro&&!m.is_platform).sort((a,b)=>a.intro_classes_left-b.intro_classes_left);
  document.getElementById('body-intro').innerHTML = intros.length ? intros.map(m=>{{
    const left = m.intro_classes_left;
    const used = m.intro_classes_used;
    const total = m.intro_classes_total;
    let urgLabel, urgCls;
    if(left===0){{urgLabel='🔴 Sin clases — URGENTE';urgCls='p-danger';}}
    else if(left===1){{urgLabel='🟠 1 restante — HABLAR HOY';urgCls='p-warn';}}
    else if(used>=2){{urgLabel='🟡 Momento de convertir';urgCls='p-warn';}}
    else{{urgLabel='🟢 Seguimiento';urgCls='p-ok';}}
    const expiry = m.intro_expiry_days!==null ? `${{m.intro_expiry_days}}d` : '—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="text-align:center">
        <span style="font-size:13px;font-weight:500">${{used}}/${{total}}</span>
        <div style="font-size:10px;color:#847366">${{left}} restante${{left!==1?'s':''}}</div>
      </td>
      <td>${{pl(urgLabel,urgCls)}}</td>
      <td style="font-size:11px;color:#aaa">${{m.prev_class||'—'}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="text-align:center;color:${{m.intro_expiry_days!==null&&m.intro_expiry_days<=7?'#a32d2d':'#847366'}};font-size:11px">${{expiry}}</td>
      <td style="font-size:11px">${{noteCell(m)}}</td>
    </tr>`;
  }}).join('') : '<tr><td colspan="7" class="empty">Sin Intro Journeys activos</td></tr>';
}}

function renderPotenciales(){{
  const pots = MEMBERS.filter(m=>
    !m.is_platform &&
    !m.tags.includes('Member') &&
    !m.is_intro &&
    m.days_inactive>30 &&
    m.visits>0
  ).sort((a,b)=>b.visits-a.visits);
  document.getElementById('body-pot').innerHTML = pots.length ? pots.map(m=>{{
    const ls = m.last_seen ? new Date(m.last_seen).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit',year:'2-digit'}}) : '—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="font-size:11px;color:#847366">${{m.email}}</td>
      <td style="font-size:11px">${{m.phone||'—'}}</td>
      <td style="font-size:11px">${{ls}}</td>
      <td style="text-align:center;font-weight:500">${{m.visits}}</td>
      <td style="text-align:center;color:#847366">${{m.days_inactive}}d</td>
      <td style="font-size:11px">${{noteCell(m)}}</td>
    </tr>`;
  }}).join('') : '<tr><td colspan="7" class="empty">Sin potenciales</td></tr>';
}}

function renderBriefing(){{
  const today = new Date().toLocaleDateString('es-ES',{{weekday:'long',day:'numeric',month:'long'}});
  let txt = `Briefing aretē · ${{today}}\\n${{Array(45).fill('─').join('')}}\\n\\n`;
  txt += `RESUMEN\\nMembers activos: {stats['active_members']} / 300 (${{Math.round({stats['active_members']}/3)}}%)\\n`;
  txt += `Tareas hoy: ${{TASKS_TODAY.length}} · Esta semana: ${{TASKS_WEEK.length}}\\n\\n`;

  const sinM = TASKS_TODAY.filter(t=>t.type==='sin_metodo_pago');
  if(sinM.length){{txt+=`SIN MÉTODO DE PAGO — HOY (${{sinM.length}})\\n`;sinM.forEach(t=>txt+=`· ${{t.name}} — ${{t.detail}}\\n`);txt+='\\n';}}

  const packs = TASKS_TODAY.filter(t=>t.type==='pack_expirando');
  if(packs.length){{txt+=`PACKS TERMINAN HOY (${{packs.length}})\\n`;packs.forEach(t=>txt+=`· ${{t.name}} — ${{t.nc||''}}\\n`);txt+='\\n';}}

  const intros = TASKS_TODAY.filter(t=>t.type==='intro_journey');
  if(intros.length){{txt+=`INTRO JOURNEY — ACCIÓN HOY (${{intros.length}})\\n`;intros.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}\\n`);txt+='\\n';}}

  const semana = TASKS_WEEK.slice(0,10);
  if(semana.length){{
    txt+=`PRÓXIMAS ACCIONES ESTA SEMANA\\n`;
    semana.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}${{t.nc?' (${{t.nc}})':''}}\\n`);
    if(TASKS_WEEK.length>10)txt+=`· ...y ${{TASKS_WEEK.length-10}} más\\n`;
  }}
  txt += `\\n${{Array(45).fill('─').join('')}}\\nGenerado automáticamente · aretē · {TODAY_STR}`;
  document.getElementById('briefing-text').textContent = txt;
}}

function copyBriefing(){{navigator.clipboard.writeText(document.getElementById('briefing-text').textContent).then(()=>toast('Briefing copiado'));}}

function init(){{
  filterList('today','');
  filterList('week','');
  renderActivos();
  renderRefrescar();
  renderIntro();
  renderPotenciales();
  updateCounts();
}}

init();
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

    print('👥 Cargando members...')
    all_members = fetch_all_members(token)
    print(f'✅ {len(all_members)} members cargados')

    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    relevant_members = []
    for m in all_members:
        tag_names = {t['name'] for t in m.get('customerTags', [])}
        visits = m.get('visits', {}).get('totalVisits', 0)
        if bool(tag_names & RELEVANT) or visits >= 3:
            relevant_members.append(m)

    print(f'   Procesando {len(relevant_members)} members relevantes...')
    members_data = []
    for i, member in enumerate(relevant_members):
        if i % 20 == 0: print(f'   {i}/{len(relevant_members)}...')
        if i > 0 and i % 80 == 0:
            print('   Refrescando token...')
            token = get_token()
        result = process_member(token, member, tag_ids)
        if result: members_data.append(result)

    print(f'✅ {len(members_data)} members procesados')

    active = sum(1 for m in members_data if 'Member' in m['tags'] and not m['is_platform'])
    intro = sum(1 for m in members_data if m['is_intro'] and not m['is_platform'])
    potencial = sum(1 for m in members_data if
        not m['is_platform'] and
        not any(t in m['tags'] for t in ['Member','introjourney','member potencial']) and
        m['days_inactive'] > 30 and m['visits'] > 0)
    no_pm = sum(1 for m in members_data if
        'Member' in m['tags'] and not m['is_platform'] and not m['has_pm'])
    to_refresh = sum(1 for m in members_data if
        'Member' in m['tags'] and not m['is_platform'] and m['days_inactive'] > 14)

    stats = {
        'active_members': active,
        'intro_count': intro,
        'potenciales': potencial,
        'no_payment_method': no_pm,
        'to_refresh': to_refresh,
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
    print(f'   Members activos: {active} / 300')
    print(f'   Intro Journey: {intro}')
    print(f'   Potenciales: {potencial}')
    print(f'   Sin método pago: {no_pm}')
    print(f'   A refrescar: {to_refresh}')
    print(f'   Tareas hoy: {len(tasks_today)}')
    print(f'   Tareas semana: {len(tasks_week)}')

if __name__ == '__main__':
    main()
