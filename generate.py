import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
BASE = 'https://api.momence.com'
HOST_ID = 45937
MOMENCE_CRM = f'https://momence.com/dashboard/{HOST_ID}/crm'
TODAY = datetime.now(timezone.utc)
TODAY_STR = TODAY.strftime('%d/%m/%Y %H:%M')

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo('Europe/Madrid')
except:
    MADRID = None

def to_madrid(dt):
    if not dt: return dt
    if MADRID:
        return dt.astimezone(MADRID)
    return dt + timedelta(hours=1)

def today_madrid():
    return to_madrid(TODAY).date()

def parse_dt(iso_str):
    if not iso_str: return None
    try:
        return datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    except: return None

def days_ago(dt):
    if not dt: return None
    return max(0, (TODAY - dt).days)

# Platforms to exclude
PLATFORM_TAGS = {'classpass', 'wellhub', 'urbansportsclub', 'gympass'}
PLATFORM_EMAIL_DOMAINS = ['classpass.com', 'wellhub.com', 'gympass.com', 'urbansportsclub.com']

def is_platform(member):
    email = member.get('email', '').lower()
    if any(d in email for d in PLATFORM_EMAIL_DOMAINS): return True
    tags = {t['name'].lower() for t in member.get('customerTags', [])}
    return bool(tags & PLATFORM_TAGS)

def get_token():
    r = requests.post(f'{BASE}/api/v2/auth/token', data={
        'grant_type': 'password', 'username': EMAIL, 'password': PASSWORD,
        'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET
    })
    r.raise_for_status()
    return r.json()['access_token']

def api_get(token, path, params=None):
    time.sleep(0.15)
    try:
        r = requests.get(f'{BASE}{path}',
            headers={'Authorization': f'Bearer {token}'},
            params=params or {}, timeout=15)
        if r.status_code == 429:
            time.sleep(3)
            r = requests.get(f'{BASE}{path}',
                headers={'Authorization': f'Bearer {token}'},
                params=params or {}, timeout=15)
        if r.status_code not in [200, 201]: return {}
        return r.json()
    except: return {}

def api_post_tag(token, mid, tag_id):
    time.sleep(0.15)
    try:
        r = requests.post(f'{BASE}/api/v2/host/members/{mid}/tags',
            headers={'Authorization': f'Bearer {token}'},
            json={'tagId': tag_id}, timeout=10)
        return r.status_code in [200, 201]
    except: return False

def api_del_tag(token, mid, tag_id):
    time.sleep(0.15)
    try:
        r = requests.delete(f'{BASE}/api/v2/host/members/{mid}/tags/{tag_id}',
            headers={'Authorization': f'Bearer {token}'}, timeout=10)
        return r.status_code in [200, 204]
    except: return False

# ── DATA FETCHERS ──────────────────────────────────────────────────────────────

def fetch_all_members(token):
    members, page = [], 0
    while True:
        data = api_get(token, '/api/v2/host/members', {'page': page, 'pageSize': 100})
        batch = data.get('payload', [])
        if not batch: break
        members.extend(batch)
        total = data.get('pagination', {}).get('totalCount', 0)
        if page % 5 == 0: print(f'  {len(members)}/{total}...')
        if len(members) >= total: break
        page += 1
        # Refresh token every 20 pages to avoid expiry during long fetch
        if page % 20 == 0:
            print('  Refrescando token (fetch)...')
    return members

def fetch_tags(token):
    data = api_get(token, '/api/v2/host/tags', {'page': 0, 'pageSize': 100})
    return {t['name']: t['id'] for t in data.get('payload', [])}

def fetch_membership_prices(token):
    """Returns {membership_id: price}"""
    prices = {}
    page = 0
    while True:
        data = api_get(token, '/api/v2/host/memberships', {'page': page, 'pageSize': 100})
        for m in data.get('payload', []):
            mid = m.get('id')
            price = m.get('price') or 0
            if mid:
                try: prices[mid] = float(price)
                except: prices[mid] = 0.0
        total = data.get('pagination', {}).get('totalCount', 0)
        fetched = (page + 1) * 100
        if fetched >= total or not data.get('payload'): break
        page += 1
    print(f'  {len(prices)} membresías con precio')
    return prices

def fetch_active_memberships(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/bought-memberships/active',
                   {'page': 0, 'pageSize': 10})
    return data.get('payload', [])

def fetch_sessions(token, mid):
    """Returns (past_checkins, future_bookings) sorted"""
    data = api_get(token, f'/api/v2/host/members/{mid}/sessions',
                   {'page': 0, 'pageSize': 20})
    past, future = [], []
    for s in data.get('payload', []):
        starts = s.get('session', {}).get('startsAt', '')
        dt = parse_dt(starts)
        if not dt: continue
        teacher = s.get('session', {}).get('teacher', {}) or {}
        coach_name = f"{teacher.get('firstName','')} {teacher.get('lastName','')}".strip()
        checked_in = s.get('checkedIn', False)
        entry = {
            'dt': dt,
            'dt_madrid': to_madrid(dt),
            'name': s.get('session', {}).get('name', ''),
            'coach': coach_name,
            'checked_in': checked_in,
        }
        if dt > TODAY:
            future.append(entry)
        else:
            past.append(entry)
    future.sort(key=lambda x: x['dt'])
    past.sort(key=lambda x: x['dt'], reverse=True)
    return past, future

def fetch_notes(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/notes',
                   {'page': 0, 'pageSize': 5})
    notes = []
    for n in data.get('payload', []):
        text = (n.get('content') or '').strip()
        if text:
            dt = parse_dt(n.get('createdAt', ''))
            date_str = to_madrid(dt).strftime('%d/%m/%y') if dt else ''
            notes.append({'content': text, 'date': date_str})
    return notes

# ── MEMBERSHIP HELPERS ────────────────────────────────────────────────────────

def mem_name(m): return m.get('membership', {}).get('name', '').lower()
def is_intro(m): return 'intro journey' in mem_name(m)
def is_prueba(m): return 'clase de prueba' in mem_name(m) or 'free trial' in mem_name(m).lower() or 'welcome' in mem_name(m)
def is_subscription(m): return m.get('membership', {}).get('type') == 'subscription' or m.get('membership', {}).get('autoRenewing') == True

def get_credits(m):
    used = m.get('usedSessions') or 0
    total = m.get('usageLimitForSessions')
    if total:
        left = max(0, total - used)
        return used, total, left
    return used, None, None

def get_renewal_days(m):
    end = parse_dt(m.get('endDate', ''))
    if not end: return None
    return (end.astimezone(MADRID).date() - today_madrid()).days if MADRID else (end.date() - TODAY.date()).days

# ── PROCESS MEMBER ─────────────────────────────────────────────────────────────

def process_member(token, member, tag_ids, mem_prices):
    mid = member['id']
    tag_names = [t['name'] for t in member.get('customerTags', [])]
    tag_id_map = {t['name']: t['id'] for t in member.get('customerTags', [])}
    platform = is_platform(member)

    # Only process if relevant
    RELEVANT_TAGS = {'Member','FORMER MEMBER','member potencial','introjourney',
                     'DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    visits_total = (member.get('visits') or {}).get('bookingsVisits', 0) or 0
    if not (set(tag_names) & RELEVANT_TAGS) and visits_total < 3:
        return None

    # Fetch data
    active_mems = fetch_active_memberships(token, mid)
    past_sessions, future_sessions = fetch_sessions(token, mid)
    notes = fetch_notes(token, mid)

    # Filter out platform memberships
    own_mems = [m for m in active_mems if not any(
        p in mem_name(m) for p in ['classpass', 'wellhub', 'gympass', 'urban sport']
    )]

    # Classify memberships
    subscription_mems = [m for m in own_mems if is_subscription(m) and not is_intro(m) and not is_prueba(m)]
    intro_mems = [m for m in own_mems if is_intro(m)]
    prueba_mems = [m for m in own_mems if is_prueba(m)]
    pack_mems = [m for m in own_mems if not is_subscription(m) and not is_intro(m) and not is_prueba(m)]

    has_subscription = len(subscription_mems) > 0
    has_intro = len(intro_mems) > 0
    has_prueba = len(prueba_mems) > 0
    has_pack = len(pack_mems) > 0
    has_active = len(own_mems) > 0
    has_future = len(future_sessions) > 0

    # Last real visit (checkedIn = True)
    last_checkin = next((s for s in past_sessions if s['checked_in']), None)
    last_checkin_dt = last_checkin['dt'] if last_checkin else None
    days_inactive = days_ago(last_checkin_dt) if last_checkin_dt else days_ago(parse_dt(member.get('lastSeen', ''))) or 999

    # New member detection — bought in last 7 days, ≤1 visit
    is_new = False
    new_purchase = None
    for m in own_mems:
        start = parse_dt(m.get('startDate', ''))
        if start and (TODAY - start).days <= 7 and visits_total <= 1:
            is_new = True
            new_purchase = m.get('membership', {}).get('name', '')
            break

    # Payment method — only PM tag counts
    has_pm = 'PM' in tag_names

    # MRR — sum of subscription prices from catalog
    mrr = 0.0
    for m in subscription_mems:
        mid_mem = m.get('membership', {}).get('id')
        if mid_mem and mid_mem in mem_prices:
            mrr += mem_prices[mid_mem]

    # Pack info
    pack_left = pack_total = pack_alert = None
    if pack_mems:
        pm = pack_mems[0]
        used, total, left = get_credits(pm)
        if total and total > 1:
            pack_left = left
            pack_total = total
            threshold = max(1, round(total * 0.20))
            pack_alert = left <= threshold

    # Intro info
    intro_used = intro_total = intro_left = intro_expiry = None
    if intro_mems:
        im = intro_mems[0]
        intro_used, intro_total, intro_left = get_credits(im)
        intro_expiry = get_renewal_days(im)

    # Renewal info (subscription)
    renewal_days = None
    if subscription_mems:
        renewal_days = get_renewal_days(subscription_mems[0])

    # Membership summary
    if subscription_mems:
        sm = subscription_mems[0]
        used, total, left = get_credits(sm)
        parts = [sm.get('membership', {}).get('name', '')]
        if total and left is not None: parts.append(f'{left} clases restantes')
        if renewal_days is not None: parts.append(f'renueva en {renewal_days}d')
        membership_summary = ' · '.join(parts)
    elif pack_mems:
        pm = pack_mems[0]
        used, total, left = get_credits(pm)
        parts = [pm.get('membership', {}).get('name', '')]
        if total and left is not None: parts.append(f'{left}/{total} clases')
        membership_summary = ' · '.join(parts)
    elif intro_mems:
        membership_summary = intro_mems[0].get('membership', {}).get('name', '')
    elif prueba_mems:
        membership_summary = prueba_mems[0].get('membership', {}).get('name', '')
    else:
        membership_summary = ''

    # Next class
    next_sess = future_sessions[0] if future_sessions else None
    prev_sess = last_checkin or (past_sessions[0] if past_sessions else None)

    def fmt_sess(s):
        if not s: return None
        dt = s['dt_madrid']
        name = s['name'].split('·')[0].strip()
        coach = s['coach'].split()[0] if s['coach'] else ''
        result = dt.strftime('%d/%m %H:%M') + ' · ' + name
        if coach: result += f' ({coach})'
        return result

    next_class = fmt_sess(next_sess)
    prev_class = fmt_sess(prev_sess)
    next_coach = next_sess['coach'] if next_sess else None

    if next_sess:
        dt_madrid = next_sess['dt_madrid']
        next_class_days = (dt_madrid.date() - today_madrid()).days
    else:
        next_class_days = None

    # Past coaches
    past_coaches = []
    seen_c = set()
    for s in past_sessions[:10]:
        c = s['coach'].split()[0] if s['coach'] else ''
        if c and c not in seen_c:
            seen_c.add(c)
            past_coaches.append(c)
            if len(past_coaches) >= 3: break

    # Auto-tag logic (skip platform users)
    add_tags, remove_tags = [], []
    if not platform:
        should_member = has_subscription or (has_pack and has_future) or (has_active and not has_intro and not has_prueba)
        should_potencial = has_intro or has_prueba or (not has_active and days_inactive <= 30 and visits_total >= 1)
        should_former = not has_active and not has_future and days_inactive > 30 and 'DUCK' not in tag_names and 'INFLU' not in tag_names

        if should_member:
            if 'Member' not in tag_names: add_tags.append('Member')
            if 'FORMER MEMBER' in tag_names: remove_tags.append('FORMER MEMBER')
            if 'member potencial' in tag_names: remove_tags.append('member potencial')
        elif should_potencial:
            if 'member potencial' not in tag_names: add_tags.append('member potencial')
            if 'Member' in tag_names: remove_tags.append('Member')
        elif should_former:
            if 'FORMER MEMBER' not in tag_names: add_tags.append('FORMER MEMBER')
            if 'Member' in tag_names: remove_tags.append('Member')

    for tag_name in add_tags:
        tid = tag_ids.get(tag_name)
        if tid and api_post_tag(token, mid, tid):
            tag_names.append(tag_name)
    for tag_name in remove_tags:
        tid = tag_id_map.get(tag_name)
        if tid and api_del_tag(token, mid, tid):
            if tag_name in tag_names: tag_names.remove(tag_name)

    return {
        'id': mid,
        'name': f"{member.get('firstName','')} {member.get('lastName','')}".strip(),
        'email': member.get('email', ''),
        'phone': member.get('phoneNumber', ''),
        'tags': tag_names,
        'visits': visits_total,
        'days_inactive': days_inactive,
        'last_seen': member.get('lastSeen', ''),
        'last_checkin': last_checkin_dt.isoformat() if last_checkin_dt else None,
        'is_platform': platform,
        'is_new': is_new,
        'new_purchase': new_purchase,
        'has_active': has_active,
        'has_subscription': has_subscription,
        'has_pack': has_pack,
        'has_intro': has_intro,
        'has_prueba': has_prueba,
        'has_future': has_future,
        'has_pm': has_pm,
        'mrr': mrr,
        'membership_summary': membership_summary,
        'renewal_days': renewal_days,
        'pack_left': pack_left,
        'pack_total': pack_total,
        'pack_alert': pack_alert,
        'intro_used': intro_used or 0,
        'intro_total': intro_total or 3,
        'intro_left': intro_left if intro_left is not None else 3,
        'intro_expiry': intro_expiry,
        'next_class': next_class,
        'next_class_days': next_class_days,
        'next_coach': next_coach,
        'prev_class': prev_class,
        'past_coaches': past_coaches,
        'notes': notes,
        'last_note': notes[0]['content'] if notes else '',
        'momence_url': f'{MOMENCE_CRM}/{mid}',
        'notes_url': f'{MOMENCE_CRM}/{mid}#?tab=notes',
    }

# ── BUILD TASKS ────────────────────────────────────────────────────────────────

def build_tasks(members):
    today_tasks, week_tasks = [], []
    seen = set()

    for m in members:
        if not m or m['is_platform']: continue
        email = m['email']
        nc_days = m['next_class_days']

        def task(type_, detail, action, priority, sd=None):
            return {
                'type': type_,
                'name': m['name'], 'email': email,
                'detail': detail, 'action': action,
                'nc': m['next_class'], 'nc_days': nc_days,
                'prev_class': m['prev_class'],
                'next_coach': m['next_coach'],
                'past_coaches': m['past_coaches'],
                'last_note': m['last_note'],
                'notes': m['notes'],
                'momence_url': m['momence_url'],
                'notes_url': m['notes_url'],
                'priority': priority,
                'sd': sd if sd is not None else (nc_days if nc_days is not None else 99),
            }

        def add(t):
            key = f"{email}_{t['type']}"
            if key not in seen:
                seen.add(key)
                if t['nc_days'] == 0:
                    today_tasks.append(t)
                else:
                    week_tasks.append(t)

        # ── 1. NUEVO MEMBER ──────────────────────────────────────────────────
        if m['is_new']:
            add(task('bienvenida',
                f"Nuevo · {m['new_purchase'] or m['membership_summary']} · {m['visits']} visita{'s' if m['visits']!=1 else ''}",
                'Enviar WhatsApp de bienvenida — presentarse y confirmar primera clase',
                1, sd=0))

        # ── 2. SIN MÉTODO DE PAGO — viene hoy ───────────────────────────────
        if not m['has_pm'] and m['has_subscription'] and nc_days == 0:
            renewal = f" · renueva en {m['renewal_days']}d" if m['renewal_days'] is not None else ""
            add(task('pm_hoy',
                f"Viene hoy · sin método de pago{renewal}",
                'Pedir método de pago al llegar — tarjeta o cuenta bancaria',
                2, sd=0))

        # ── 3. SIN MÉTODO DE PAGO — no viene hoy (semana) ───────────────────
        if not m['has_pm'] and m['has_subscription'] and nc_days != 0:
            renewal_days = m['renewal_days'] if m['renewal_days'] is not None else 99
            urgency = 1 if renewal_days <= 3 else 2 if renewal_days <= 7 else 3
            t = task('sin_pm',
                m['membership_summary'],
                'Conseguir método de pago — contactar por WhatsApp',
                urgency, sd=renewal_days)
            key = f"{email}_sin_pm"
            if key not in seen:
                seen.add(key)
                week_tasks.append(t)

        # ── 4. RESERVA UNPAID (futuro sin membresía activa) ──────────────────
        # Handled implicitly — if no active membership and has future session, it's unpaid context

        # ── 5. PACK EXPIRANDO ────────────────────────────────────────────────
        if m['pack_alert'] and m['has_future']:
            add(task('pack_expirando',
                f"Pack · {m['pack_left']} clase{'s' if m['pack_left']!=1 else ''} restante{'s' if m['pack_left']!=1 else ''} de {m['pack_total']}",
                'Ofrecer renovación de pack — hablar en la próxima clase',
                3))

        # ── 6. INTRO JOURNEY ─────────────────────────────────────────────────
        if m['has_intro'] and m['intro_used'] >= 1:
            left = m['intro_left']
            used = m['intro_used']
            if left == 0:
                urgency, action = 1, 'URGENTE — Sin clases restantes. Contactar hoy para convertir'
            elif left == 1:
                urgency, action = 2, 'Le queda 1 clase — hablar en la próxima para convertir'
            elif used >= 2:
                urgency, action = 3, 'Convertir a member — hablar después de la clase'
            else:
                urgency, action = 4, 'Seguimiento — preguntar cómo va el intro'
            expiry = f" · caduca en {m['intro_expiry']}d" if m['intro_expiry'] is not None else ""
            add(task('intro_journey',
                f"Intro Journey · {used}/{m['intro_total']} clases · {left} restante{'s' if left!=1 else ''}{expiry}",
                action, urgency))

    today_tasks.sort(key=lambda x: x['priority'])
    week_tasks.sort(key=lambda x: (x['sd'], x['priority']))
    return today_tasks, week_tasks

# ── GENERATE HTML ──────────────────────────────────────────────────────────────

def generate_html(members, tasks_today, tasks_week, stats):
    mj = json.dumps([m for m in members if m], ensure_ascii=False)
    tj = json.dumps(tasks_today, ensure_ascii=False)
    wj = json.dumps(tasks_week, ensure_ascii=False)
    mrr_json = json.dumps(stats.get('mrr_breakdown', {}), ensure_ascii=False)
    gh_url = f"https://github.com/estudio-arete/dashboard_acuerdo13_v2/actions/workflows/update.yml"

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>aretē · gestión</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans',-apple-system,'Helvetica Neue',sans-serif;font-size:13px;color:#222323;background:#f7f7f7}}
.app{{padding:1rem;max-width:1100px;margin:0 auto}}

/* Topbar */
.topbar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;padding:0.9rem 1.25rem;border-radius:6px;background:#27303d;flex-wrap:wrap;gap:8px}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-name{{font-size:22px;font-weight:300;letter-spacing:0.06em;color:#d8e3f4;font-family:Georgia,serif}}
.brand-sub{{font-size:11px;color:#8fa0b8;letter-spacing:0.04em}}
.update-info{{font-size:10px;color:#8fa0b8;margin-top:2px}}
.btn-refresh{{font-size:11px;padding:6px 14px;border:1px solid rgba(216,227,244,0.25);border-radius:4px;background:transparent;color:#d8e3f4;cursor:pointer;font-family:inherit;letter-spacing:0.03em}}
.btn-refresh:hover{{background:rgba(216,227,244,0.1)}}

/* Metrics */
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:1rem}}
.metric{{background:#fff;border-radius:4px;padding:0.75rem;text-align:center;border:1px solid #ebebeb}}
.metric .n{{font-size:22px;font-weight:300;line-height:1.2;letter-spacing:-0.02em;color:#222323}}
.metric .l{{font-size:10px;color:#847366;margin-top:3px;letter-spacing:0.04em}}
.metric.hi .n{{color:#27303d}}
.metric.warn .n{{color:#854f0b}}

/* Progress */
.prog-wrap{{background:#fff;border-radius:4px;padding:0.85rem 1.25rem;margin-bottom:1rem;border:1px solid #ebebeb}}
.prog-label{{display:flex;justify-content:space-between;font-size:11px;color:#847366;margin-bottom:8px}}
.prog-label strong{{color:#222323}}
.prog-bar{{height:3px;background:#ebebeb;border-radius:2px}}
.prog-fill{{height:100%;background:#27303d;border-radius:2px}}

/* Tabs */
.tabs-wrap{{background:#fff;border-radius:4px;border:1px solid #ebebeb;overflow:hidden}}
.tabs{{display:flex;border-bottom:1px solid #ebebeb;overflow-x:auto}}
.tab{{font-size:11px;padding:10px 16px;cursor:pointer;color:#847366;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;letter-spacing:0.03em}}
.tab.active{{color:#222323;font-weight:500;border-bottom-color:#27303d}}
.tab:hover{{color:#222323}}
.tab-content{{display:none;padding:1.25rem}}
.tab-content.active{{display:block}}
.badge{{font-size:9px;padding:1px 5px;border-radius:100px;margin-left:3px}}
.badge.r{{background:#f0f0f0;color:#222323}}
.badge.w{{background:#fdf6ec;color:#854f0b}}
.badge.b{{background:#eef3f8;color:#27303d}}
.badge.g{{background:#edf5e8;color:#3b6d11}}

/* Section header */
.section-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem}}
.section-title{{font-size:11px;font-weight:500;letter-spacing:0.06em;color:#847366}}
.section-count{{font-size:11px;color:#847366}}

/* Filter bar */
.filter-bar{{display:flex;gap:5px;margin-bottom:0.75rem;flex-wrap:wrap}}
.fb{{font-size:10px;padding:3px 10px;border:1px solid #ebebeb;border-radius:100px;cursor:pointer;background:#fff;color:#847366;letter-spacing:0.03em}}
.fb.active{{background:#27303d;color:#fff;border-color:#27303d}}

/* Tasks */
.task-list{{display:flex;flex-direction:column;gap:6px}}
.task{{padding:12px 14px;border:1px solid #ebebeb;border-radius:4px;background:#fff;border-left:2px solid #ebebeb}}
.task.t-urgent{{border-left-color:#222323}}
.task.t-warn{{border-left-color:#c4832a}}
.task.t-info{{border-left-color:#27303d}}
.task.t-ok{{border-left-color:#3b6d11}}
.task-top{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}}
.tname{{font-size:13px;font-weight:500}}
.tname a{{color:#222323;text-decoration:none}}
.tname a:hover{{color:#27303d;text-decoration:underline}}
.tpill{{font-size:9px;padding:2px 7px;border-radius:100px;font-weight:500;letter-spacing:0.03em}}
.tp-urg{{background:#f0f0f0;color:#222323}}
.tp-warn{{background:#fdf6ec;color:#854f0b}}
.tp-info{{background:#eef3f8;color:#27303d}}
.tp-ok{{background:#edf5e8;color:#3b6d11}}
.tdetail{{font-size:11px;color:#847366;margin-bottom:4px;line-height:1.5}}
.taction{{font-size:12px;font-weight:500;color:#222323;line-height:1.4}}
.taction.urg{{color:#222323}}.taction.warn{{color:#854f0b}}.taction.info{{color:#27303d}}.taction.ok{{color:#3b6d11}}
.tmeta{{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap}}
.tclass{{font-size:10px;color:#847366;padding:2px 8px;border:1px solid #ebebeb;border-radius:100px;background:#fafafa}}
.tnotes{{margin-top:8px;padding:8px 10px;background:#fafafa;border-radius:4px;border:1px solid #ebebeb}}
.tnote-item{{font-size:11px;color:#847366;font-style:italic;margin-bottom:3px;line-height:1.4}}
.tnote-date{{font-size:10px;color:#bbb;margin-right:6px}}
.note-link{{font-size:10px;color:#27303d;text-decoration:none;letter-spacing:0.02em}}
.note-link:hover{{text-decoration:underline}}

/* Toolbar + table */
.toolbar{{display:flex;align-items:center;gap:8px;margin-bottom:0.75rem;flex-wrap:wrap}}
.search{{font-size:12px;padding:6px 10px;border:1px solid #ebebeb;border-radius:4px;background:#fff;color:#222323;font-family:inherit;width:200px}}
.search:focus{{outline:none;border-color:#27303d}}
.tbl-wrap{{overflow-x:auto;border:1px solid #ebebeb;border-radius:4px;max-height:500px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;min-width:700px}}
th{{font-size:10px;font-weight:500;color:#847366;text-align:left;padding:8px 10px;background:#fafafa;border-bottom:1px solid #ebebeb;white-space:nowrap;position:sticky;top:0;z-index:1;letter-spacing:0.04em}}
td{{font-size:12px;padding:7px 10px;border-bottom:1px solid #f5f5f5;vertical-align:middle;line-height:1.4}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#fafafa}}
.member-link{{color:#222323;text-decoration:none;font-weight:500}}
.member-link:hover{{color:#27303d}}
.pill{{display:inline-block;font-size:9px;padding:2px 7px;border-radius:100px;font-weight:500;margin:1px;letter-spacing:0.03em}}
.p-dark{{background:#27303d;color:#fff}}.p-grey{{background:#f0f0f0;color:#847366}}
.p-ok{{background:#edf5e8;color:#3b6d11}}.p-warn{{background:#fdf6ec;color:#854f0b}}
.p-info{{background:#eef3f8;color:#27303d}}.p-danger{{background:#f0f0f0;color:#222323}}

/* Subtabs */
.subtabs{{display:flex;gap:4px;margin-bottom:0.75rem}}
.stab{{font-size:11px;padding:4px 12px;border:1px solid #ebebeb;border-radius:4px;cursor:pointer;background:#fff;color:#847366;font-family:inherit}}
.stab.active{{background:#27303d;color:#fff;border-color:#27303d}}

/* Economia */
.eco-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:1rem}}
.eco-card{{background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem}}
.eco-label{{font-size:10px;color:#847366;letter-spacing:0.06em;margin-bottom:6px}}
.eco-value{{font-size:30px;font-weight:300;letter-spacing:-0.02em;color:#222323;line-height:1}}
.eco-value span{{font-size:14px;color:#847366}}
.eco-sub{{font-size:11px;color:#847366;margin-top:5px}}

/* Briefing */
.briefing-box{{background:#fafafa;border-radius:4px;padding:1.25rem;font-size:12px;line-height:1.9;white-space:pre-wrap;border:1px solid #ebebeb;min-height:200px;margin-bottom:0.75rem;font-family:'Courier New',monospace}}
.copy-btn{{width:100%;padding:9px;border:none;border-radius:4px;background:#27303d;color:#fff;font-size:11px;cursor:pointer;font-family:inherit;letter-spacing:0.05em}}
.copy-btn:hover{{background:#1e2530}}

/* Toast */
.toast{{position:fixed;bottom:1.5rem;right:1.5rem;background:#27303d;color:#d8e3f4;padding:10px 18px;border-radius:4px;font-size:11px;opacity:0;transition:opacity 0.3s;pointer-events:none;z-index:999}}
.toast.show{{opacity:1}}
.empty{{padding:3rem;text-align:center;color:#847366;font-size:12px;letter-spacing:0.03em}}
@media(max-width:650px){{.metrics{{grid-template-columns:repeat(3,1fr)}};.eco-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="app">

  <div class="topbar">
    <div>
      <div class="brand">
        <span class="brand-name">aretē</span>
        <span class="brand-sub">· sistema de gestión</span>
      </div>
      <div class="update-info">Actualizado: {TODAY_STR} · Se actualiza cada hora</div>
    </div>
    <button class="btn-refresh" onclick="window.open('{gh_url}','_blank');toast('Abre GitHub Actions → Run workflow')">↻ Actualizar ahora</button>
  </div>

  <div class="metrics">
    <div class="metric hi"><div class="n">{stats['members']}</div><div class="l">MEMBERS</div></div>
    <div class="metric hi"><div class="n">{stats['total_mrr']:.0f}€</div><div class="l">MRR</div></div>
    <div class="metric warn"><div class="n">{stats['mrr_risk']:.0f}€</div><div class="l">MRR EN RIESGO</div></div>
    <div class="metric"><div class="n" id="m-hoy">—</div><div class="l">TAREAS HOY</div></div>
    <div class="metric"><div class="n" id="m-semana">—</div><div class="l">ESTA SEMANA</div></div>
    <div class="metric"><div class="n">{stats['no_pm']}</div><div class="l">SIN MÉTODO PAGO</div></div>
  </div>

  <div class="prog-wrap">
    <div class="prog-label"><strong>Objetivo 300 members</strong><span>{stats['members']} / 300 — {min(100,round(stats['members']/3))}%</span></div>
    <div class="prog-bar"><div class="prog-fill" style="width:{min(100,round(stats['members']/3))}%"></div></div>
  </div>

  <div class="tabs-wrap">
    <div class="tabs">
      <div class="tab active" onclick="showTab('hoy')">Hoy<span class="badge r" id="b-hoy">—</span></div>
      <div class="tab" onclick="showTab('semana')">Semana<span class="badge w" id="b-semana">—</span></div>
      <div class="tab" onclick="showTab('nuevos')">Nuevos<span class="badge g">{stats['new_members']}</span></div>
      <div class="tab" onclick="showTab('members')">Members<span class="badge b">{stats['members']}</span></div>
      <div class="tab" onclick="showTab('intro')">Intro<span class="badge b">{stats['intro']}</span></div>
      <div class="tab" onclick="showTab('potenciales')">Potenciales<span class="badge w">{stats['potenciales']}</span></div>
      <div class="tab" onclick="showTab('economia')">Economía</div>
      <div class="tab" onclick="showTab('briefing')">Briefing</div>
    </div>

    <!-- HOY -->
    <div id="tab-hoy" class="tab-content active">
      <div class="section-hdr">
        <div class="section-title">OBLIGATORIO HOY</div>
        <div class="section-count" id="hoy-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="fl('t','',this)">Todos</button>
        <button class="fb" onclick="fl('t','bienvenida',this)">👋 Bienvenida</button>
        <button class="fb" onclick="fl('t','pm_hoy',this)">💳 Pedir PM</button>
        <button class="fb" onclick="fl('t','pack_expirando',this)">Pack</button>
        <button class="fb" onclick="fl('t','intro_journey',this)">Intro</button>
      </div>
      <div class="task-list" id="list-hoy"></div>
    </div>

    <!-- SEMANA -->
    <div id="tab-semana" class="tab-content">
      <div class="section-hdr">
        <div class="section-title">ESTA SEMANA — EN ORDEN DE URGENCIA</div>
        <div class="section-count" id="semana-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="fl('w','',this)">Todos</button>
        <button class="fb" onclick="fl('w','sin_pm',this)">💳 Sin PM</button>
        <button class="fb" onclick="fl('w','pack_expirando',this)">Pack</button>
        <button class="fb" onclick="fl('w','intro_journey',this)">Intro</button>
        <button class="fb" onclick="fl('w','bienvenida',this)">👋 Nuevos</button>
      </div>
      <div class="task-list" id="list-semana"></div>
    </div>

    <!-- NUEVOS -->
    <div id="tab-nuevos" class="tab-content">
      <div class="section-hdr">
        <div class="section-title">NUEVOS MEMBERS — ÚLTIMOS 7 DÍAS</div>
        <div class="section-count">Enviar WhatsApp de bienvenida</div>
      </div>
      <div class="tbl-wrap">
        <table><thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Membresía</th><th>Visitas</th><th>Próxima clase</th></tr></thead>
        <tbody id="body-nuevos"></tbody></table>
      </div>
    </div>

    <!-- MEMBERS -->
    <div id="tab-members" class="tab-content">
      <div class="subtabs">
        <button class="stab active" onclick="showSub('activos',this)">Activos ({stats['members']})</button>
        <button class="stab" onclick="showSub('refrescar',this)">A refrescar ({stats['to_refresh']})</button>
      </div>
      <div id="sub-activos">
        <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="ft('tbl-activos',this.value)"></div>
        <div class="tbl-wrap"><table id="tbl-activos">
          <thead><tr><th>Nombre</th><th>Membresía</th><th>Última visita</th><th>Próx. clase</th><th>Coaches</th><th>Visitas</th><th>Nota</th></tr></thead>
          <tbody id="body-activos"></tbody>
        </table></div>
      </div>
      <div id="sub-refrescar" style="display:none">
        <div class="toolbar">
          <input class="search" placeholder="Buscar..." oninput="ft('tbl-refrescar',this.value)">
          <span style="font-size:11px;color:#847366">Más de 14 días sin venir</span>
        </div>
        <div class="tbl-wrap"><table id="tbl-refrescar">
          <thead><tr><th>Nombre</th><th>Membresía</th><th>Última visita</th><th>Días</th><th>Próx. clase</th><th>Nota</th></tr></thead>
          <tbody id="body-refrescar"></tbody>
        </table></div>
      </div>
    </div>

    <!-- INTRO -->
    <div id="tab-intro" class="tab-content">
      <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="ft('tbl-intro',this.value)"></div>
      <div class="tbl-wrap"><table id="tbl-intro">
        <thead><tr><th>Nombre</th><th>Clases</th><th>Estado</th><th>Clase anterior</th><th>Próxima clase</th><th>Caduca</th><th>Nota</th></tr></thead>
        <tbody id="body-intro"></tbody>
      </table></div>
    </div>

    <!-- POTENCIALES -->
    <div id="tab-potenciales" class="tab-content">
      <div class="toolbar">
        <input class="search" placeholder="Buscar..." oninput="ft('tbl-pot',this.value)">
        <span style="font-size:11px;color:#847366">Ordenados por última visita · sin plataformas</span>
      </div>
      <div class="tbl-wrap"><table id="tbl-pot">
        <thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Última visita</th><th>Visitas</th><th>Días inactivo</th><th>Nota</th></tr></thead>
        <tbody id="body-pot"></tbody>
      </table></div>
    </div>

    <!-- ECONOMÍA -->
    <div id="tab-economia" class="tab-content">
      <div class="eco-grid">
        <div class="eco-card">
          <div class="eco-label">MRR TOTAL</div>
          <div class="eco-value">{stats['total_mrr']:.0f}<span>€</span></div>
          <div class="eco-sub">{stats['members']} suscripciones activas</div>
        </div>
        <div class="eco-card">
          <div class="eco-label">MRR EN RIESGO</div>
          <div class="eco-value">{stats['mrr_risk']:.0f}<span>€</span></div>
          <div class="eco-sub">{stats['no_pm']} members sin método de pago</div>
        </div>
        <div class="eco-card">
          <div class="eco-label">TICKET MEDIO</div>
          <div class="eco-value">{stats['avg_mrr']:.0f}<span>€</span></div>
          <div class="eco-sub">Por member con suscripción</div>
        </div>
      </div>
      <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem;margin-bottom:1rem">
        <div class="section-title" style="margin-bottom:1rem">DESGLOSE POR MEMBRESÍA</div>
        <div id="mrr-breakdown"></div>
      </div>
      <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem">
        <div class="section-title" style="margin-bottom:0.75rem">SIN MÉTODO DE PAGO — DETALLE</div>
        <div class="tbl-wrap" style="max-height:300px"><table>
          <thead><tr><th>Nombre</th><th>Membresía</th><th>MRR</th><th>Renueva en</th><th>Próxima clase</th></tr></thead>
          <tbody id="body-mrr-riesgo"></tbody>
        </table></div>
      </div>
    </div>

    <!-- BRIEFING -->
    <div id="tab-briefing" class="tab-content">
      <div class="briefing-box" id="briefing-text"></div>
      <button class="copy-btn" onclick="copyBriefing()">COPIAR BRIEFING</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const MEMBERS={mj};
const TT={tj};
const TW={wj};
const MRR_BD={mrr_json};

function toast(m,d=2500){{const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}}
function ft(id,q){{document.querySelectorAll(`#${{id}} tbody tr`).forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none');}}
function fmtDate(iso){{if(!iso)return'—';try{{const d=new Date(iso);return d.toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit'}});}}catch{{return'—';}}}}
function pl(t,c){{return`<span class="pill ${{c}}">${{t}}</span>`;}}

function showTab(t){{
  const tabs=['hoy','semana','nuevos','members','intro','potenciales','economia','briefing'];
  tabs.forEach((n,i)=>{{document.querySelectorAll('.tab')[i]?.classList.toggle('active',n===t);}});
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t)?.classList.add('active');
  if(t==='briefing')renderBriefing();
  if(t==='economia')renderEconomia();
}}

function showSub(name,btn){{
  document.getElementById('sub-activos').style.display=name==='activos'?'block':'none';
  document.getElementById('sub-refrescar').style.display=name==='refrescar'?'block':'none';
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');
}}

const TM={{
  bienvenida:{{label:'👋 Bienvenida',pill:'tp-ok',cls:'t-ok',acls:'ok'}},
  pm_hoy:{{label:'💳 Pedir PM hoy',pill:'tp-urg',cls:'t-urgent',acls:'urg'}},
  sin_pm:{{label:'⚠️ Sin método',pill:'tp-warn',cls:'t-warn',acls:'warn'}},
  pack_expirando:{{label:'Pack acaba',pill:'tp-info',cls:'t-info',acls:'info'}},
  intro_journey:{{label:'Intro Journey',pill:'tp-info',cls:'t-info',acls:'info'}},
}};

function notesHTML(notes){{
  if(!notes||!notes.length)return'';
  return notes.slice(0,3).map(n=>`<div class="tnote-item"><span class="tnote-date">${{n.date}}</span>"${{n.content.slice(0,90)}}${{n.content.length>90?'…':''}}"</div>`).join('');
}}

function taskHTML(t){{
  const m=TM[t.type]||{{label:'',pill:'tp-info',cls:'',acls:'info'}};
  const nc=t.nc?`<span class="tclass">📅 ${{t.nc}}</span>`:'';
  const pc=t.prev_class?`<span class="tclass" style="opacity:0.5">↩ ${{t.prev_class}}</span>`:'';
  const coach=t.next_coach?`<span class="tclass">Coach: ${{t.next_coach.split(' ')[0]}}</span>`:'';
  const notes=notesHTML(t.notes||[]);
  return`<div class="task ${{m.cls}}">
    <div class="task-top">
      <span class="tname"><a href="${{t.momence_url}}" target="_blank">${{t.name}}</a></span>
      <span class="tpill ${{m.pill}}">${{m.label}}</span>
    </div>
    <div class="tdetail">${{t.detail}}</div>
    <div class="taction ${{m.acls}}">${{t.action}}</div>
    <div class="tmeta">${{pc}}${{nc}}${{coach}}</div>
    ${{notes||t.last_note?`<div class="tnotes">${{notes||`<div class="tnote-item">"${{t.last_note}}"</div>`}}<a href="${{t.notes_url}}" target="_blank" class="note-link" style="display:block;margin-top:4px">+ añadir nota en Momence →</a></div>`:`<div class="tnotes"><a href="${{t.notes_url}}" target="_blank" class="note-link">+ añadir nota en Momence →</a></div>`}}
  </div>`;
}}

function updateCounts(){{
  document.getElementById('m-hoy').textContent=TT.length||'0';
  document.getElementById('m-semana').textContent=TW.length||'0';
  document.getElementById('b-hoy').textContent=TT.length;
  document.getElementById('b-semana').textContent=TW.length;
  document.getElementById('hoy-count').textContent=TT.length+' tareas';
  document.getElementById('semana-count').textContent=TW.length+' tareas';
}}

let fT='',fW='';
function fl(which,type,btn){{
  if(which==='t')fT=type; else fW=type;
  if(btn){{btn.closest('.filter-bar').querySelectorAll('.fb').forEach(b=>b.classList.remove('active'));btn.classList.add('active');}}
  const tasks=which==='t'?TT:TW;
  const filtered=type?tasks.filter(t=>t.type===type):tasks;
  const el=document.getElementById(which==='t'?'list-hoy':'list-semana');
  el.innerHTML=filtered.length?filtered.map(taskHTML).join(''):'<div class="empty">Sin tareas</div>';
}}

const TC={{'Member':'p-dark','FORMER MEMBER':'p-grey','member potencial':'p-ok','introjourney':'p-info','DUCK':'p-warn','PM':'p-ok','MANUAL':'p-warn','CASH':'p-warn','ENG':'p-info','INFLU':'p-grey','NO CANCELAR!':'p-danger'}};
const ST=['Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PM','ENG','NO CANCELAR!'];
function tagPills(tags){{return tags.filter(t=>ST.includes(t)).map(t=>`<span class="pill ${{TC[t]||'p-grey'}}">${{t}}</span>`).join('');}}
function noteCell(m){{
  const n=m.notes&&m.notes.length?`<div style="font-size:11px;color:#847366;font-style:italic">"${{m.notes[0].content.slice(0,50)}}${{m.notes[0].content.length>50?'…':''}}"</div>`:'';
  return n+`<a href="${{m.notes_url}}" target="_blank" class="note-link">+ nota →</a>`;
}}

function renderNuevos(){{
  const ms=MEMBERS.filter(m=>m.is_new&&!m.is_platform).sort((a,b)=>a.days_inactive-b.days_inactive);
  document.getElementById('body-nuevos').innerHTML=ms.length?ms.map(m=>`<tr>
    <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
    <td style="font-size:11px;color:#847366">${{m.email}}</td>
    <td style="font-size:11px">${{m.phone||'—'}}</td>
    <td style="font-size:11px">${{m.new_purchase||m.membership_summary||'—'}}</td>
    <td style="text-align:center">${{m.visits}}</td>
    <td style="font-size:11px">${{m.next_class||'—'}}</td>
  </tr>`).join(''):'<tr><td colspan="6" class="empty">Sin nuevos members esta semana</td></tr>';
}}

function renderActivos(){{
  const ms=MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform).sort((a,b)=>a.days_inactive-b.days_inactive);
  document.getElementById('body-activos').innerHTML=ms.length?ms.map(m=>{{
    const lv=m.last_checkin?fmtDate(m.last_checkin):fmtDate(m.last_seen);
    const dc=m.days_inactive;
    const dcCol=dc>21?'#222323':dc>14?'#854f0b':'#3b6d11';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px;color:${{dcCol}}">${{lv}} <span style="font-size:10px;opacity:0.6">(${{dc}}d)</span></td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="font-size:11px;color:#847366">${{m.past_coaches.join(', ')||'—'}}</td>
      <td style="text-align:center">${{m.visits}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin datos</td></tr>';
}}

function renderRefrescar(){{
  const ms=MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform&&m.days_inactive>14).sort((a,b)=>b.days_inactive-a.days_inactive);
  document.getElementById('body-refrescar').innerHTML=ms.length?ms.map(m=>{{
    const lv=m.last_checkin?fmtDate(m.last_checkin):fmtDate(m.last_seen);
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px">${{lv}}</td>
      <td style="font-weight:500;color:${{m.days_inactive>21?'#222323':'#854f0b'}}">${{m.days_inactive}}d</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="6" class="empty">Todos han venido recientemente</td></tr>';
}}

function renderIntro(){{
  const ms=MEMBERS.filter(m=>m.has_intro&&!m.is_platform).sort((a,b)=>(a.intro_left||0)-(b.intro_left||0));
  document.getElementById('body-intro').innerHTML=ms.length?ms.map(m=>{{
    const left=m.intro_left||0,used=m.intro_used||0,total=m.intro_total||3;
    let estado,ecls;
    if(left===0){{estado='Sin clases — URGENTE';ecls='p-danger';}}
    else if(left===1){{estado='1 restante — hablar ya';ecls='p-warn';}}
    else if(used>=2){{estado='Convertir';ecls='p-warn';}}
    else{{estado='Seguimiento';ecls='p-ok';}}
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="text-align:center"><span style="font-size:14px;font-weight:300">${{used}}/${{total}}</span><div style="font-size:10px;color:#847366">${{left}} restante${{left!==1?'s':''}}</div></td>
      <td>${{pl(estado,ecls)}}</td>
      <td style="font-size:11px;color:#aaa">${{m.prev_class||'—'}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="font-size:11px;color:${{m.intro_expiry!==null&&m.intro_expiry<=7?'#222323':'#847366'}}">${{m.intro_expiry!==null?m.intro_expiry+'d':'—'}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin Intro Journeys activos</td></tr>';
}}

function renderPotenciales(){{
  const ms=MEMBERS.filter(m=>
    !m.is_platform&&!m.tags.includes('Member')&&!m.has_intro&&
    m.days_inactive>30&&m.visits>0
  ).sort((a,b)=>a.days_inactive-b.days_inactive);
  document.getElementById('body-pot').innerHTML=ms.length?ms.map(m=>{{
    const lv=m.last_checkin?fmtDate(m.last_checkin):fmtDate(m.last_seen);
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="font-size:11px;color:#847366">${{m.email}}</td>
      <td style="font-size:11px">${{m.phone||'—'}}</td>
      <td style="font-size:11px">${{lv}}</td>
      <td style="text-align:center">${{m.visits}}</td>
      <td style="text-align:center;color:#847366">${{m.days_inactive}}d</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin potenciales</td></tr>';
}}

function renderEconomia(){{
  // MRR breakdown chart
  const entries=Object.entries(MRR_BD).sort((a,b)=>b[1]-a[1]);
  const total=entries.reduce((s,e)=>s+e[1],0)||1;
  document.getElementById('mrr-breakdown').innerHTML=entries.map(([name,val])=>{{
    const pct=Math.round((val/total)*100);
    return`<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span style="font-size:12px">${{name}}</span>
        <span style="font-size:12px;font-weight:500">${{val.toFixed(0)}}€ <span style="font-size:10px;color:#847366">${{pct}}%</span></span>
      </div>
      <div style="height:3px;background:#f0f0f0;border-radius:2px"><div style="height:100%;width:${{pct}}%;background:#27303d;border-radius:2px"></div></div>
    </div>`;
  }}).join('');
  // MRR at risk table
  const risk=MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform&&!m.has_pm&&m.has_subscription)
    .sort((a,b)=>(a.renewal_days||99)-(b.renewal_days||99));
  document.getElementById('body-mrr-riesgo').innerHTML=risk.length?risk.map(m=>{{
    const r=m.renewal_days!==null&&m.renewal_days!==undefined?m.renewal_days+'d':'—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="font-size:11px">${{m.membership_summary.split('·')[0].trim()}}</td>
      <td style="font-weight:500">${{m.mrr>0?m.mrr.toFixed(0)+'€':'—'}}</td>
      <td style="color:${{m.renewal_days!==null&&m.renewal_days<=7?'#222323':'#847366'}}">${{r}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="5" class="empty">Sin MRR en riesgo</td></tr>';
}}

function renderBriefing(){{
  const today=new Date().toLocaleDateString('es-ES',{{weekday:'long',day:'numeric',month:'long'}});
  let txt=`aretē · briefing ${{today}}\\n${{Array(44).fill('—').join('')}}\\n\\n`;
  txt+=`members: {stats['members']} / 300 · mrr: {stats['total_mrr']:.0f}€ · en riesgo: {stats['mrr_risk']:.0f}€\\n`;
  txt+=`tareas hoy: ${{TT.length}} · esta semana: ${{TW.length}}\\n\\n`;
  const byType=(arr,type)=>arr.filter(t=>t.type===type);
  [['bienvenida','👋 nuevos members'],['pm_hoy','💳 pedir pm hoy'],['sin_pm','⚠️ sin método de pago'],
   ['pack_expirando','📦 packs terminan'],['intro_journey','🎯 intro journey']].forEach(([type,label])=>{{
    const items=byType(TT,type).concat(byType(TW,type));
    if(items.length){{txt+=`${{label}} (${{items.length}})\\n`;items.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}\\n`);txt+='\\n';}}
  }});
  txt+=`${{Array(44).fill('—').join('')}}\\naretē · {TODAY_STR}`;
  document.getElementById('briefing-text').textContent=txt;
}}

function copyBriefing(){{navigator.clipboard.writeText(document.getElementById('briefing-text').textContent).then(()=>toast('Briefing copiado'));}}

function init(){{
  fl('t','');fl('w','');
  renderNuevos();renderActivos();renderRefrescar();
  renderIntro();renderPotenciales();updateCounts();
}}
init();
</script>
</body>
</html>'''

# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    print('🔐 Autenticando...')
    token = get_token()
    print('✅ Token OK')

    print('🏷️  Tags...')
    tag_ids = fetch_tags(token)
    print(f'   {len(tag_ids)} tags')

    print('💶  Precios membresías...')
    mem_prices = fetch_membership_prices(token)

    print('👥 Cargando members...')
    all_members = fetch_all_members(token)
    print(f'✅ {len(all_members)} members')

    # Filter relevant
    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney',
                'DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    relevant = []
    for m in all_members:
        tag_set = {t['name'] for t in m.get('customerTags', [])}
        visits = (m.get('visits') or {}).get('bookingsVisits', 0) or 0
        if bool(tag_set & RELEVANT) or visits >= 3:
            relevant.append(m)
    print(f'   {len(relevant)} relevantes')

    # Process
    members_data = []
    for i, member in enumerate(relevant):
        if i % 20 == 0: print(f'   {i}/{len(relevant)}...')
        if i > 0 and i % 80 == 0:
            print('   Refrescando token...')
            token = get_token()
        result = process_member(token, member, tag_ids, mem_prices)
        if result: members_data.append(result)

    print(f'✅ {len(members_data)} procesados')

    # Stats
    own = [m for m in members_data if not m['is_platform']]
    active = [m for m in own if 'Member' in m['tags']]
    total_mrr = sum(m['mrr'] for m in active)
    no_pm = [m for m in active if not m['has_pm'] and m['has_subscription']]
    mrr_risk = sum(m['mrr'] for m in no_pm)
    avg_mrr = total_mrr / len([m for m in active if m['mrr'] > 0]) if any(m['mrr'] > 0 for m in active) else 0

    # MRR breakdown
    mrr_breakdown = {}
    for m in active:
        if m['mrr'] > 0:
            name = m['membership_summary'].split('·')[0].strip() if m['membership_summary'] else 'Otro'
            mrr_breakdown[name] = mrr_breakdown.get(name, 0) + m['mrr']

    stats = {
        'members': len(active),
        'intro': sum(1 for m in own if m['has_intro']),
        'new_members': sum(1 for m in own if m['is_new']),
        'potenciales': sum(1 for m in own if not m['tags'].__contains__('Member') and not m['has_intro'] and m['days_inactive'] > 30 and m['visits'] > 0),
        'no_pm': len(no_pm),
        'to_refresh': sum(1 for m in active if m['days_inactive'] > 14),
        'total_mrr': total_mrr,
        'mrr_risk': mrr_risk,
        'avg_mrr': avg_mrr,
        'mrr_breakdown': mrr_breakdown,
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
    print(f'   Members: {len(active)} · MRR: {total_mrr:.0f}€ · En riesgo: {mrr_risk:.0f}€')
    print(f'   Sin PM: {len(no_pm)} · Nuevos: {stats["new_members"]} · Intro: {stats["intro"]}')
    print(f'   Tareas hoy: {len(tasks_today)} · Semana: {len(tasks_week)}')

if __name__ == '__main__':
    main()
