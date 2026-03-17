import requests
import json
import os
import time
from datetime import datetime, timezone, timedelta

CLIENT_ID = os.environ['MOMENCE_CLIENT_ID']
CLIENT_SECRET = os.environ['MOMENCE_CLIENT_SECRET']
EMAIL = os.environ['MOMENCE_EMAIL']
PASSWORD = os.environ['MOMENCE_PASSWORD']
GH_REPO = os.environ.get('GH_REPO', 'estudio-arete/dashboard_acuerdo13_v2')
BASE = 'https://api.momence.com'
HOST_ID = 45937
MOMENCE_CRM = f'https://momence.com/dashboard/{HOST_ID}/crm'
TODAY = datetime.now(timezone.utc)
TODAY_STR = TODAY.strftime('%d/%m/%Y %H:%M')
TODAY_DATE = TODAY.date()

def is_platform_user(member):
    email = member.get('email', '').lower()
    if any(p in email for p in ['classpass', 'urbansports', 'wellhub', 'gympass']):
        return True
    tag_names = {t['name'].lower() for t in member.get('customerTags', [])}
    return bool(tag_names & {'classpass', 'wellhub', 'urbansportsclub', 'gympass'})

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
        # Convert to Madrid time for accurate calculation
        from datetime import timezone
        import zoneinfo
        try:
            madrid = zoneinfo.ZoneInfo('Europe/Madrid')
        except:
            madrid = timezone(timedelta(hours=1))
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        today_madrid = TODAY.astimezone(madrid).date()
        dt_madrid = dt.astimezone(madrid).date()
        return max(0, (today_madrid - dt_madrid).days)
    except: return None

def get_last_checkin_date(sessions_past):
    for s in sessions_past:
        checked_in = s['data'].get('checkedIn', False)
        if checked_in:
            return s['dt']
    return None

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
                coach_first = s.get('session', {}).get('teacher', {}).get('firstName', '')
                coach_last = s.get('session', {}).get('teacher', {}).get('lastName', '')
                coach = f"{coach_first} {coach_last}".strip()
                payment = s.get('paymentMethod', '') or ''
                is_unpaid = 'unpaid' in payment.lower() or 'pay later' in payment.lower()
                entry = {'dt': dt, 'data': s, 'coach': coach, 'is_unpaid': is_unpaid}
                if dt > TODAY:
                    future.append(entry)
                else:
                    past.append(entry)
            except: pass
    future.sort(key=lambda x: x['dt'])
    past.sort(key=lambda x: x['dt'], reverse=True)
    return past, future

def fetch_notes(token, mid):
    data = api_get(token, f'/api/v2/host/members/{mid}/notes', {'page': 0, 'pageSize': 5})
    return data.get('payload', [])

def format_notes(notes):
    result = []
    for n in notes[:3]:
        content_text = n.get('content', '').strip()
        created = n.get('createdAt', '')
        if content_text:
            date_str = ''
            if created:
                try:
                    from zoneinfo import ZoneInfo
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    madrid = ZoneInfo('Europe/Madrid')
                    dt_madrid = dt.astimezone(madrid)
                    date_str = dt_madrid.strftime('%d/%m/%y')
                except:
                    pass
            result.append({'content': content_text, 'date': date_str})
    return result

def assign_tag(token, mid, tag_id):
    return api_post(token, f'/api/v2/host/members/{mid}/tags', {'tagId': tag_id})

def remove_tag(token, mid, tag_id):
    return api_delete(token, f'/api/v2/host/members/{mid}/tags/{tag_id}')

def format_session(s_obj, show_coach=False):
    if not s_obj: return None
    dt = s_obj['dt']
    name = s_obj['data'].get('session', {}).get('name', '')
    result = dt.strftime('%d/%m %H:%M') + ' · ' + name.split('·')[0].strip()
    if show_coach and s_obj.get('coach'):
        result += f" ({s_obj['coach'].split()[0]})"
    return result

def is_intro_journey(mem):
    name = mem.get('membership', {}).get('name', '').lower()
    return 'intro journey' in name

def is_clase_prueba(mem):
    name = mem.get('membership', {}).get('name', '').lower()
    return 'clase de prueba' in name

def is_subscription(mem):
    return mem.get('type') == 'subscription'

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

    own_active_mems = [m for m in active_mems if not any(
        p in m.get('membership', {}).get('name', '').lower()
        for p in ['classpass', 'wellhub', 'gympass', 'urban']
    )]

    has_active = len(own_active_mems) > 0
    has_subscription = any(is_subscription(m) for m in own_active_mems)
    has_future = len(future_sessions) > 0

    # Pack credits - for non-subscription memberships
    pack_credits_left = None
    pack_credits_total = None
    pack_alert = False
    for m in own_active_mems:
        if not is_subscription(m) and not is_intro_journey(m) and not is_clase_prueba(m):
            used = m.get('usedSessions') or 0
            total = m.get('usageLimitForSessions')
            if total:
                left = max(0, total - used)
                pack_credits_left = left
                pack_credits_total = total
                # Alert when <=20% remaining
                threshold = max(1, round(total * 0.20))
                pack_alert = left <= threshold
                break
    # Use last checked-in session for accurate inactivity, fallback to lastSeen
    last_checkin = get_last_checkin_date(past_sessions)
    if last_checkin:
        days_inactive = days_since(last_checkin.isoformat()) or 0
    else:
        days_inactive = days_since(member.get('lastSeen', '')) or 0

    # Exact membership type detection
    has_intro_journey = any(is_intro_journey(m) for m in own_active_mems)
    has_clase_prueba = any(is_clase_prueba(m) for m in own_active_mems)

    # New member detection (bought in last 7 days, <=1 visit)
    is_new_member = False
    new_member_purchase = None
    for m in own_active_mems:
        start = m.get('startDate', '')
        if start:
            try:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                days_since_purchase = (TODAY - dt).days
                if days_since_purchase <= 7 and visits <= 1:
                    is_new_member = True
                    new_member_purchase = m.get('membership', {}).get('name', '')
                    break
            except: pass

    # Unpaid future sessions without active membership
    unpaid_future = [s for s in future_sessions if s.get('is_unpaid') and not has_active]

    # Auto tag logic
    add_tags, remove_tags = [], []
    if not is_platform:
        if (has_subscription and not has_intro_journey) or (has_future and not has_active) or (not has_active and not has_future and days_inactive <= 30):
            if 'Member' not in tag_names: add_tags.append('Member')
            if 'FORMER MEMBER' in tag_names: remove_tags.append('FORMER MEMBER')
        elif has_intro_journey or has_clase_prueba:
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
    next_class = format_session(next_session, show_coach=True)
    prev_class = format_session(prev_session, show_coach=True)
    next_class_days = (next_session['dt'].date() - TODAY_DATE).days if next_session else None
    next_coach = next_session['coach'] if next_session else None

    # Past coaches (unique, last 3)
    past_coaches = []
    seen_coaches = set()
    for s in past_sessions[:10]:
        c = s.get('coach', '')
        if c and c not in seen_coaches:
            seen_coaches.add(c)
            past_coaches.append(c.split()[0])
            if len(past_coaches) >= 3: break

    # Intro journey details
    intro_classes_used = 0
    intro_classes_total = 3
    intro_classes_left = 3
    intro_expiry_days = None
    if has_intro_journey:
        m = next(x for x in own_active_mems if is_intro_journey(x))
        intro_classes_used = m.get('usedSessions') or 0
        intro_classes_total = m.get('usageLimitForSessions') or 3
        intro_classes_left = max(0, (intro_classes_total or 0) - (intro_classes_used or 0))
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
        used = m.get('usedSessions') or 0
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
                if is_subscription(m):
                    parts.append(f'renueva en {renewal_days}d')
            except: pass
        membership_summary = ' · '.join(parts)

    last_note = notes[0].get('content', '').strip() if notes else ''
    formatted_notes = format_notes(notes)
    has_pm = 'PM' in tag_names or 'MANUAL' in tag_names or 'CASH' in tag_names

    # MRR calculation - sum of all active subscription amounts
    mrr = 0.0
    for m in own_active_mems:
        if is_subscription(m):
            # Get renewal amount from membership
            price = m.get('membership', {}).get('price', 0) or 0
            try:
                mrr += float(price)
            except:
                pass

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
        'has_subscription': has_subscription,
        'has_future': has_future,
        'pack_credits_left': pack_credits_left,
        'pack_credits_total': pack_credits_total,
        'pack_alert': pack_alert,
        'is_platform': is_platform,
        'is_intro': has_intro_journey,
        'is_clase_prueba': has_clase_prueba,
        'is_new_member': is_new_member,
        'new_member_purchase': new_member_purchase,
        'is_manual_cash': 'MANUAL' in tag_names or 'CASH' in tag_names,
        'has_pm': has_pm,
        'mrr': mrr,
        'membership_summary': membership_summary,
        'renewal_days': renewal_days,
        'next_class': next_class,
        'next_class_days': next_class_days,
        'next_coach': next_coach,
        'prev_class': prev_class,
        'past_coaches': past_coaches,
        'unpaid_future': [{'date': s['dt'].strftime('%d/%m %H:%M'), 'class': s['data'].get('session',{}).get('name','').split('·')[0].strip()} for s in unpaid_future],
        'intro_classes_used': intro_classes_used,
        'intro_classes_total': intro_classes_total,
        'intro_classes_left': intro_classes_left,
        'intro_expiry_days': intro_expiry_days,
        'last_note': last_note,
        'formatted_notes': formatted_notes,
        'momence_url': f'{MOMENCE_CRM}/{mid}',
        'momence_notes_url': f'{MOMENCE_CRM}/{mid}#?tab=notes',
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

        # Bienvenida nuevo member
        if m['is_new_member'] and m['visits'] <= 1:
            key = f"{email}_bienvenida"
            if key not in seen:
                seen.add(key)
                item = {
                    'type': 'bienvenida',
                    'name': m['name'], 'email': email,
                    'detail': f"Nuevo member · {m['new_member_purchase'] or 'membresía nueva'} · {m['visits']} visita{'s' if m['visits']!=1 else ''}",
                    'action': 'Enviar WhatsApp de bienvenida — presentarse y confirmar primera clase',
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'prev_class': None, 'past_coaches': m['past_coaches'],
                    'next_coach': m['next_coach'],
                    'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                    'momence_url': m['momence_url'],
                    'momence_notes_url': m['momence_notes_url'],
                    'priority': 1, 'sd': nc_days if nc_days is not None else 0
                }
                tasks_today.append(item)

        # Sin PM + suscripción que renueva pronto
        if not m['has_pm'] and m['has_subscription'] and m['renewal_days'] is not None and m['renewal_days'] <= 7:
            key = f"{email}_sin_metodo_pago"
            if key not in seen:
                seen.add(key)
                item = {
                    'type': 'sin_metodo_pago',
                    'name': m['name'], 'email': email,
                    'detail': m['membership_summary'],
                    'action': 'Conseguir método de pago antes de la renovación',
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'prev_class': m['prev_class'], 'past_coaches': m['past_coaches'],
                    'next_coach': m['next_coach'],
                    'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                    'momence_url': m['momence_url'],
                    'momence_notes_url': m['momence_notes_url'],
                    'priority': 2, 'sd': nc_days if nc_days is not None else 99
                }
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Reminder metodo de pago el dia que vienen
        if not m['has_pm'] and m['has_subscription'] and nc_days == 0:
            key = f"{email}_pm_reminder_hoy"
            if key not in seen:
                seen.add(key)
                tasks_today.append({
                    'type': 'pm_reminder',
                    'name': m['name'], 'email': email,
                    'detail': f"Viene hoy · {m['next_class']} · sin método de pago guardado",
                    'action': 'Pedir método de pago al llegar — tarjeta o cuenta bancaria',
                    'nc': m['next_class'], 'nc_days': 0,
                    'prev_class': m['prev_class'], 'past_coaches': m['past_coaches'],
                    'next_coach': m['next_coach'],
                    'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                    'momence_url': m['momence_url'],
                    'momence_notes_url': m['momence_notes_url'],
                    'priority': 2, 'sd': 0
                })

        # Reservas unpaid sin membresía activa (avisar 2 días antes)
        for unpaid in m['unpaid_future']:
            key = f"{email}_unpaid_{unpaid['date']}"
            if key not in seen:
                seen.add(key)
                try:
                    unpaid_dt = datetime.strptime(unpaid['date'], '%d/%m %H:%M').replace(year=TODAY.year, tzinfo=timezone.utc)
                    days_to_class = (unpaid_dt.date() - TODAY_DATE).days
                    if days_to_class <= 2:
                        item = {
                            'type': 'reserva_unpaid',
                            'name': m['name'], 'email': email,
                            'detail': f"Clase reservada sin pago · {unpaid['date']} · {unpaid['class']}",
                            'action': 'Revisar pago antes de la clase',
                            'nc': unpaid['date'], 'nc_days': days_to_class,
                            'prev_class': m['prev_class'], 'past_coaches': m['past_coaches'],
                            'next_coach': m['next_coach'],
                            'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                            'momence_url': m['momence_url'],
                            'momence_notes_url': m['momence_notes_url'],
                            'priority': 2, 'sd': days_to_class
                        }
                        if days_to_class == 0: tasks_today.append(item)
                        else: tasks_week.append(item)
                except: pass

        # Pack expirando - usar créditos restantes (<=20% del total)
        if not m['has_subscription'] and m['pack_credits_left'] is not None and m['pack_alert']:
            key = f"{email}_pack_expirando"
            if key not in seen:
                seen.add(key)
                left = m['pack_credits_left']
                total = m['pack_credits_total']
                item = {
                    'type': 'pack_expirando',
                    'name': m['name'], 'email': email,
                    'detail': f"Pack · {left} clase{'s' if left!=1 else ''} restante{'s' if left!=1 else ''} de {total} · {m['membership_summary'].split('·')[0].strip()}",
                    'action': 'Ofrecer renovación de pack — hablar en la próxima clase',
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'prev_class': m['prev_class'], 'past_coaches': m['past_coaches'],
                    'next_coach': m['next_coach'],
                    'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                    'momence_url': m['momence_url'],
                    'momence_notes_url': m['momence_notes_url'],
                    'priority': 3, 'sd': nc_days if nc_days is not None else 99
                }
                if nc_days == 0: tasks_today.append(item)
                else: tasks_week.append(item)

        # Intro journey
        if m['is_intro'] and m['intro_classes_used'] >= 1:
            left = m['intro_classes_left'] or 0
            used = m['intro_classes_used'] or 0
            key = f"{email}_intro_journey"
            if key not in seen:
                seen.add(key)
                if left == 0:
                    urgency, action = 1, 'URGENTE — No le quedan clases. Contactar hoy para convertir'
                elif left == 1:
                    urgency, action = 2, 'Le queda 1 clase — hablar en la próxima para convertir'
                elif used >= 2:
                    urgency, action = 3, 'Convertir a member — hablar después de la clase'
                else:
                    urgency, action = 4, 'Seguimiento — preguntar cómo va el intro'

                item = {
                    'type': 'intro_journey',
                    'name': m['name'], 'email': email,
                    'detail': f"Intro Journey · {used}/{m['intro_classes_total']} clases · {left} restante{'s' if left!=1 else ''} · caduca en {m['intro_expiry_days'] or '?'}d",
                    'action': action,
                    'nc': m['next_class'], 'nc_days': nc_days,
                    'prev_class': m['prev_class'], 'past_coaches': m['past_coaches'],
                    'next_coach': m['next_coach'],
                    'last_note': m['last_note'],
                    'formatted_notes': m.get('formatted_notes', []),
                    'momence_url': m['momence_url'],
                    'momence_notes_url': m['momence_notes_url'],
                    'priority': urgency, 'sd': nc_days if nc_days is not None else 99
                }
                if nc_days is not None and nc_days == 0:
                    tasks_today.append(item)
                else:
                    tasks_week.append(item)

    tasks_today.sort(key=lambda x: x['priority'])
    tasks_week.sort(key=lambda x: (x.get('sd', 99), x['priority']))
    return tasks_today, tasks_week

def generate_html(members_data, tasks_today, tasks_week, stats):
    mj = json.dumps([m for m in members_data if m], ensure_ascii=False)
    tj = json.dumps(tasks_today, ensure_ascii=False)
    wj = json.dumps(tasks_week, ensure_ascii=False)
    mrr_breakdown_json = json.dumps(stats.get('mrr_breakdown', {}), ensure_ascii=False)
    gh_actions_url = f'https://github.com/{GH_REPO}/actions/workflows/update.yml'

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>aretē · gestión</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;font-size:13px;color:#222323;background:#f7f7f7;min-height:100vh}}
.app{{padding:1rem;max-width:1100px;margin:0 auto}}
.topbar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;padding:0.85rem 1.25rem;border-radius:6px;background:#222323;color:#fff;flex-wrap:wrap;gap:8px}}
.brand{{font-size:15px;font-weight:400;letter-spacing:0.08em;color:#fff}}
.brand em{{font-weight:300;color:#847366;font-size:11px;margin-left:10px;font-style:normal;letter-spacing:0.04em}}
.update-info{{font-size:10px;color:#847366;margin-top:2px}}
.topbar-actions{{display:flex;gap:6px;align-items:center}}
.btn-refresh{{font-size:11px;padding:6px 14px;border:1px solid #27303d;border-radius:4px;background:#27303d;color:#fff;cursor:pointer;letter-spacing:0.03em;font-family:inherit}}
.btn-refresh:hover{{background:#1e2530}}
.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:1rem}}
.metric{{background:#fff;border-radius:4px;padding:0.75rem;text-align:center;border:1px solid #ebebeb}}
.metric .n{{font-size:24px;font-weight:300;line-height:1.2;letter-spacing:-0.02em}}
.metric .l{{font-size:10px;color:#847366;margin-top:3px;letter-spacing:0.03em}}
.red .n{{color:#222323}}.amber .n{{color:#854f0b}}.green .n{{color:#3b6d11}}.blue .n{{color:#27303d}}
.prog-wrap{{background:#fff;border-radius:4px;padding:0.85rem 1.25rem;margin-bottom:1rem;border:1px solid #ebebeb}}
.prog-label{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.prog-label span{{font-size:11px;color:#847366;letter-spacing:0.03em}}
.prog-label strong{{font-size:11px;color:#222323}}
.prog-bar{{height:3px;background:#ebebeb;border-radius:2px;overflow:hidden}}
.prog-fill{{height:100%;background:#222323;border-radius:2px}}
.tabs-wrap{{background:#fff;border-radius:4px;border:1px solid #ebebeb;overflow:hidden}}
.tabs{{display:flex;border-bottom:1px solid #ebebeb;overflow-x:auto}}
.tab{{font-size:11px;padding:10px 16px;cursor:pointer;color:#847366;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;background:#fff;letter-spacing:0.03em;font-weight:400}}
.tab.active{{color:#222323;font-weight:500;border-bottom-color:#222323}}
.tab:hover{{color:#222323}}
.tab-content{{display:none;padding:1.25rem}}
.tab-content.active{{display:block}}
.badge{{font-size:9px;background:#ebebeb;color:#222323;padding:1px 5px;border-radius:100px;margin-left:3px;letter-spacing:0.02em}}
.badge.w{{background:#fdf6ec;color:#854f0b}}.badge.i{{background:#eef3f8;color:#27303d}}.badge.g{{background:#edf5e8;color:#3b6d11}}
.section-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem}}
.section-title{{font-size:12px;font-weight:500;letter-spacing:0.04em;color:#222323}}
.section-count{{font-size:11px;color:#847366}}
.filter-bar{{display:flex;gap:5px;margin-bottom:0.75rem;flex-wrap:wrap}}
.fb{{font-size:10px;padding:3px 10px;border:1px solid #ebebeb;border-radius:100px;cursor:pointer;background:#fff;color:#847366;letter-spacing:0.03em}}
.fb.active{{background:#222323;color:#fff;border-color:#222323}}
.task-list{{display:flex;flex-direction:column;gap:6px;margin-bottom:1rem}}
.task{{display:flex;gap:12px;padding:12px 14px;border:1px solid #ebebeb;border-radius:4px;background:#fff}}
.task.urg{{border-left:2px solid #222323;padding-left:12px}}
.task.warn{{border-left:2px solid #c4832a;padding-left:12px}}
.task.info{{border-left:2px solid #27303d;padding-left:12px}}
.task.ok-t{{border-left:2px solid #3b6d11;padding-left:12px}}
.task-body{{flex:1;min-width:0}}
.task-top{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}}
.tname{{font-size:13px;font-weight:500}}
.tname a{{color:#222323;text-decoration:none}}
.tname a:hover{{color:#27303d}}
.tpill{{font-size:9px;padding:2px 7px;border-radius:100px;white-space:nowrap;letter-spacing:0.03em;font-weight:500}}
.tp1{{background:#f0f0f0;color:#222323}}.tp2{{background:#fdf6ec;color:#854f0b}}
.tp3{{background:#eef3f8;color:#27303d}}.tp4{{background:#f2f0fd;color:#3c3489}}
.tp5{{background:#f5f5f5;color:#847366}}.tp-new{{background:#edf5e8;color:#3b6d11}}
.tdetail{{font-size:11px;color:#847366;margin-bottom:4px;line-height:1.5}}
.taction{{font-size:12px;font-weight:500;line-height:1.4}}
.taction.r{{color:#222323}}.taction.a{{color:#854f0b}}.taction.b{{color:#27303d}}.taction.g{{color:#3b6d11}}
.tmeta{{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap}}
.tclass{{font-size:10px;color:#847366;padding:2px 8px;border:1px solid #ebebeb;border-radius:100px;background:#fafafa}}
.tcoach{{font-size:10px;color:#847366;padding:2px 8px;border:1px solid #ebebeb;border-radius:100px;background:#fafafa}}
.tnote-box{{margin-top:8px;padding:8px 10px;background:#f7f7f7;border-radius:4px;border:1px solid #ebebeb}}
.tnote-content{{font-size:11px;color:#847366;font-style:italic;margin-bottom:4px}}
.tnote-actions{{display:flex;gap:8px;align-items:center}}
.tnote-input{{font-size:11px;padding:4px 8px;border:1px solid #ebebeb;border-radius:4px;background:#fff;color:#222323;width:200px;font-family:inherit}}
.tnote-input:focus{{outline:none;border-color:#847366}}
.note-link{{font-size:10px;color:#27303d;text-decoration:none;letter-spacing:0.02em}}
.note-link:hover{{text-decoration:underline}}
.toolbar{{display:flex;align-items:center;gap:8px;margin-bottom:0.75rem;flex-wrap:wrap}}
.search{{font-size:12px;padding:6px 10px;border:1px solid #ebebeb;border-radius:4px;background:#fff;color:#222323;width:200px;font-family:inherit}}
.search:focus{{outline:none;border-color:#847366}}
.tbl-wrap{{overflow-x:auto;border:1px solid #ebebeb;border-radius:4px;max-height:500px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;min-width:700px}}
th{{font-size:10px;font-weight:500;color:#847366;text-align:left;padding:8px 10px;background:#fafafa;border-bottom:1px solid #ebebeb;white-space:nowrap;position:sticky;top:0;z-index:1;letter-spacing:0.04em}}
td{{font-size:12px;padding:8px 10px;border-bottom:1px solid #f5f5f5;vertical-align:middle;line-height:1.4}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#fafafa}}
.pill{{display:inline-block;font-size:9px;padding:2px 7px;border-radius:100px;font-weight:500;white-space:nowrap;margin:1px;letter-spacing:0.03em}}
.p-ok{{background:#edf5e8;color:#3b6d11}}.p-warn{{background:#fdf6ec;color:#854f0b}}
.p-danger{{background:#f0f0f0;color:#222323}}.p-info{{background:#eef3f8;color:#27303d}}
.p-grey{{background:#f5f5f5;color:#847366}}.p-dark{{background:#222323;color:#fff}}
.member-link{{color:#222323;text-decoration:none;font-weight:500}}
.member-link:hover{{color:#27303d}}
.subtabs{{display:flex;gap:4px;margin-bottom:0.75rem}}
.stab{{font-size:11px;padding:4px 12px;border:1px solid #ebebeb;border-radius:4px;cursor:pointer;background:#fff;color:#847366;font-family:inherit}}
.stab.active{{background:#27303d;color:#fff;border-color:#27303d}}
.briefing-box{{background:#fafafa;border-radius:4px;padding:1.25rem;font-size:12px;line-height:1.9;white-space:pre-wrap;border:1px solid #ebebeb;min-height:220px;margin-bottom:0.75rem;font-family:'Courier New',monospace;color:#222323}}
.copy-btn{{width:100%;padding:9px;border:none;border-radius:4px;background:#27303d;color:#fff;font-size:11px;cursor:pointer;font-family:inherit;letter-spacing:0.05em}}
.copy-btn:hover{{background:#444}}
.toast{{position:fixed;bottom:1.5rem;right:1.5rem;background:#222323;color:#fff;padding:10px 18px;border-radius:4px;font-size:11px;opacity:0;transition:opacity 0.3s;pointer-events:none;z-index:999;letter-spacing:0.03em}}
.toast.show{{opacity:1}}
.empty{{padding:3rem;text-align:center;color:#847366;font-size:12px;letter-spacing:0.03em}}
@media(max-width:650px){{.metrics{{grid-template-columns:repeat(3,1fr)}}}}
</style>
</head>
<body>
<div class="app">
  <div class="topbar">
    <div>
      <div class="brand">aretē <em>· sistema de gestión</em></div>
      <div class="update-info">Actualizado: {TODAY_STR} UTC · Se actualiza automáticamente cada hora</div>
    </div>
    <div class="topbar-actions">
      <button class="btn-refresh" onclick="window.open('{gh_actions_url}','_blank');toast('Abre GitHub Actions → Run workflow')">
        ↻ Actualizar ahora
      </button>
    </div>
  </div>

  <div class="metrics">
    <div class="metric green"><div class="n">{stats['active_members']}</div><div class="l">MEMBERS ACTIVOS</div></div>
    <div class="metric green"><div class="n">{stats['total_mrr']:.0f}€</div><div class="l">MRR</div></div>
    <div class="metric amber"><div class="n">{stats['mrr_at_risk']:.0f}€</div><div class="l">MRR EN RIESGO</div></div>
    <div class="metric red"><div class="n" id="m-hoy">—</div><div class="l">TAREAS HOY</div></div>
    <div class="metric amber"><div class="n" id="m-semana">—</div><div class="l">ESTA SEMANA</div></div>
    <div class="metric blue"><div class="n">{stats['intro_count']}</div><div class="l">INTRO JOURNEY</div></div>
  </div>

  <div class="prog-wrap">
    <div class="prog-label">
      <strong>Objetivo 300 members</strong>
      <span>{stats['active_members']} / 300 — {min(100,round(stats['active_members']/3))}%</span>
    </div>
    <div class="prog-bar"><div class="prog-fill" style="width:{min(100,round(stats['active_members']/3))}%"></div></div>
  </div>

  <div class="tabs-wrap">
    <div class="tabs">
      <div class="tab active" onclick="showTab('hoy')">Hoy<span class="badge" id="b-hoy">—</span></div>
      <div class="tab" onclick="showTab('semana')">Semana<span class="badge w" id="b-semana">—</span></div>
      <div class="tab" onclick="showTab('nuevos')">Nuevos<span class="badge g">{stats['new_members']}</span></div>
      <div class="tab" onclick="showTab('members')">Members<span class="badge i">{stats['active_members']}</span></div>
      <div class="tab" onclick="showTab('intro')">Intro Journey<span class="badge i">{stats['intro_count']}</span></div>
      <div class="tab" onclick="showTab('potenciales')">Potenciales<span class="badge w">{stats['potenciales']}</span></div>
      <div class="tab" onclick="showTab('economia')">Economía</div>
      <div class="tab" onclick="showTab('briefing')">Briefing</div>
    </div>

    <div id="tab-hoy" class="tab-content active">
      <div class="section-hdr">
        <div class="section-title">OBLIGATORIO HOY</div>
        <div class="section-count" id="hoy-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="filterList('today','',this)">Todos</button>
        <button class="fb" onclick="filterList('today','bienvenida',this)">👋 Bienvenida</button>
        <button class="fb" onclick="filterList('today','sin_metodo_pago',this)">⚠️ Sin método</button>
        <button class="fb" onclick="filterList('today','pack_expirando',this)">Pack hoy</button>
        <button class="fb" onclick="filterList('today','intro_journey',this)">Intro</button>
        <button class="fb" onclick="filterList('today','reserva_unpaid',this)">Unpaid</button>
        <button class="fb" onclick="filterList('today','pm_reminder',this)">💳 Pedir PM</button>
      </div>
      <div class="task-list" id="list-hoy"></div>
    </div>

    <div id="tab-semana" class="tab-content">
      <div class="section-hdr">
        <div class="section-title">ESTA SEMANA — EN ORDEN DE URGENCIA</div>
        <div class="section-count" id="semana-count"></div>
      </div>
      <div class="filter-bar">
        <button class="fb active" onclick="filterList('week','',this)">Todos</button>
        <button class="fb" onclick="filterList('week','sin_metodo_pago',this)">⚠️ Sin método</button>
        <button class="fb" onclick="filterList('week','pack_expirando',this)">Pack</button>
        <button class="fb" onclick="filterList('week','intro_journey',this)">Intro</button>
        <button class="fb" onclick="filterList('week','reserva_unpaid',this)">Unpaid</button>
      </div>
      <div class="task-list" id="list-semana"></div>
    </div>

    <div id="tab-nuevos" class="tab-content">
      <div class="section-hdr">
        <div class="section-title">NUEVOS MEMBERS ESTA SEMANA</div>
        <div class="section-count">Enviar WhatsApp de bienvenida</div>
      </div>
      <div class="tbl-wrap">
        <table id="tbl-nuevos">
          <thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Membresía</th><th>Visitas</th><th>Próxima clase</th></tr></thead>
          <tbody id="body-nuevos"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-members" class="tab-content">
      <div class="subtabs">
        <button class="stab active" onclick="showSubtab('activos',this)">Activos ({stats['active_members']})</button>
        <button class="stab" onclick="showSubtab('refrescar',this)">A refrescar ({stats['to_refresh']})</button>
      </div>
      <div id="subtab-activos">
        <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-activos',this.value)"></div>
        <div class="tbl-wrap">
          <table id="tbl-activos">
            <thead><tr><th>Nombre</th><th>Tags</th><th>Membresía</th><th>Última visita</th><th>Próxima clase</th><th>Coaches</th><th>Nota</th></tr></thead>
            <tbody id="body-activos"></tbody>
          </table>
        </div>
      </div>
      <div id="subtab-refrescar" style="display:none">
        <div class="toolbar">
          <input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-refrescar',this.value)">
          <span style="font-size:11px;color:#847366">Members activos sin venir más de 14 días</span>
        </div>
        <div class="tbl-wrap">
          <table id="tbl-refrescar">
            <thead><tr><th>Nombre</th><th>Membresía</th><th>Última visita</th><th>Días inactivo</th><th>Próxima clase</th><th>Nota</th></tr></thead>
            <tbody id="body-refrescar"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="tab-intro" class="tab-content">
      <div class="toolbar"><input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-intro',this.value)"></div>
      <div class="tbl-wrap">
        <table id="tbl-intro">
          <thead><tr><th>Nombre</th><th>Clases</th><th>Urgencia</th><th>Clase anterior</th><th>Próxima clase</th><th>Caduca en</th><th>Nota</th></tr></thead>
          <tbody id="body-intro"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-potenciales" class="tab-content">
      <div class="toolbar">
        <input class="search" placeholder="Buscar..." oninput="filterTbl('tbl-pot',this.value)">
        <span style="font-size:11px;color:#847366">Sin plataformas · más de 30 días inactivos</span>
      </div>
      <div class="tbl-wrap">
        <table id="tbl-pot">
          <thead><tr><th>Nombre</th><th>Email</th><th>Teléfono</th><th>Última visita</th><th>Visitas</th><th>Días</th><th>Nota</th></tr></thead>
          <tbody id="body-pot"></tbody>
        </table>
      </div>
    </div>

    <div id="tab-economia" class="tab-content">
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin-bottom:1.5rem">
        <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem">
          <div style="font-size:10px;color:#847366;letter-spacing:0.04em;margin-bottom:6px">MRR TOTAL</div>
          <div style="font-size:32px;font-weight:300;letter-spacing:-0.02em;color:#222323">{stats['total_mrr']:.0f}<span style="font-size:16px;color:#847366">€</span></div>
          <div style="font-size:11px;color:#847366;margin-top:4px">{stats['active_members']} suscripciones activas</div>
        </div>
        <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem">
          <div style="font-size:10px;color:#847366;letter-spacing:0.04em;margin-bottom:6px">MRR EN RIESGO</div>
          <div style="font-size:32px;font-weight:300;letter-spacing:-0.02em;color:#222323">{stats['mrr_at_risk']:.0f}<span style="font-size:16px;color:#847366">€</span></div>
          <div style="font-size:11px;color:#847366;margin-top:4px">{stats['no_payment_method']} members sin método de pago</div>
        </div>
        <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem">
          <div style="font-size:10px;color:#847366;letter-spacing:0.04em;margin-bottom:6px">LTV MEDIO</div>
          <div style="font-size:32px;font-weight:300;letter-spacing:-0.02em;color:#222323">{stats['avg_ltv']:.0f}<span style="font-size:16px;color:#847366">€</span></div>
          <div style="font-size:11px;color:#847366;margin-top:4px">Por member activo</div>
        </div>
      </div>
      <div style="background:#fff;border:1px solid #ebebeb;border-radius:4px;padding:1.25rem">
        <div style="font-size:11px;font-weight:500;letter-spacing:0.04em;margin-bottom:1rem">DESGLOSE MRR POR MEMBRESÍA</div>
        <div id="mrr-breakdown"></div>
      </div>
    </div>

    <div id="tab-briefing" class="tab-content">
      <div class="briefing-box" id="briefing-text"></div>
      <button class="copy-btn" onclick="copyBriefing()">COPIAR BRIEFING</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const MEMBERS={mj};
const TASKS_TODAY={tj};
const TASKS_WEEK={wj};
let fT='',fW='';

function toast(m,dur=2500){{const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),dur);}}
function filterTbl(id,q){{document.querySelectorAll(`#${{id}} tbody tr`).forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none');}}
function pl(t,c){{return`<span class="pill ${{c}}">${{t}}</span>`;}}
function fmtDate(iso){{if(!iso)return'—';return new Date(iso).toLocaleDateString('es-ES',{{day:'2-digit',month:'2-digit'}});}}

function showTab(t){{
  ['hoy','semana','nuevos','members','intro','potenciales','economia','briefing'].forEach((n,i)=>{{
    document.querySelectorAll('.tab')[i]?.classList.toggle('active',n===t);
  }});
  document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t)?.classList.add('active');
  if(t==='briefing') renderBriefing();
  if(t==='economia') renderEconomia();
}}

function showSubtab(name,btn){{
  document.getElementById('subtab-activos').style.display=name==='activos'?'block':'none';
  document.getElementById('subtab-refrescar').style.display=name==='refrescar'?'block':'none';
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
}}

const TM={{
  bienvenida:{{label:'👋 Bienvenida',pill:'tp-new',cls:'ok-t',acls:'g'}},
  sin_metodo_pago:{{label:'⚠️ Sin método',pill:'tp2',cls:'warn',acls:'a'}},
  pack_expirando:{{label:'Pack acaba',pill:'tp3',cls:'info',acls:'b'}},
  intro_journey:{{label:'Intro Journey',pill:'tp4',cls:'info',acls:'b'}},
  reserva_unpaid:{{label:'Unpaid',pill:'tp1',cls:'urg',acls:'r'}},
  pm_reminder:{{label:'💳 Pedir método pago',pill:'tp2',cls:'warn',acls:'a'}},
}};

function taskHTML(t){{
  const m=TM[t.type]||{{label:'',pill:'tp5',cls:'',acls:''}};
  const nc=t.nc?`<span class="tclass">📅 ${{t.nc}}</span>`:'';
  const pc=t.prev_class?`<span class="tclass" style="opacity:0.6">↩ ${{t.prev_class}}</span>`:'';
  const coach=t.next_coach?`<span class="tcoach">Coach: ${{t.next_coach.split(' ')[0]}}</span>`:'';
  const nameEl=`<a href="${{t.momence_url}}" target="_blank">${{t.name}}</a>`;
  const note=t.last_note?`<div class="tnote-content">"${{t.last_note.slice(0,80)}}${{t.last_note.length>80?'…':''}}"</div>`:'';
  return`<div class="task ${{m.cls}}">
    <div class="task-body">
      <div class="task-top"><span class="tname">${{nameEl}}</span><span class="tpill ${{m.pill}}">${{m.label}}</span></div>
      <div class="tdetail">${{t.detail}}</div>
      <div class="taction ${{m.acls}}">${{t.action}}</div>
      <div class="tmeta">${{pc}}${{nc}}${{coach}}</div>
      <div class="tnote-box">
        ${{renderNotes(t.formatted_notes||[])}}
        <div class="tnote-actions">
          <a href="${{t.momence_notes_url}}" target="_blank" class="note-link">+ añadir nota en Momence →</a>
        </div>
      </div>
    </div>
  </div>`;
}}

function updateCounts(){{
  document.getElementById('m-hoy').textContent=TASKS_TODAY.length||'0';
  document.getElementById('m-semana').textContent=TASKS_WEEK.length||'0';
  document.getElementById('b-hoy').textContent=TASKS_TODAY.length;
  document.getElementById('b-semana').textContent=TASKS_WEEK.length;
  document.getElementById('hoy-count').textContent=TASKS_TODAY.length+' tareas';
  document.getElementById('semana-count').textContent=TASKS_WEEK.length+' tareas';
}}

function filterList(which,type,btn){{
  if(which==='today')fT=type; else fW=type;
  if(btn){{btn.closest('.filter-bar').querySelectorAll('.fb').forEach(b=>b.classList.remove('active'));btn.classList.add('active');}}
  const tasks=which==='today'?TASKS_TODAY:TASKS_WEEK;
  const filtered=type?tasks.filter(t=>t.type===type):tasks;
  const cid=which==='today'?'list-hoy':'list-semana';
  document.getElementById(cid).innerHTML=filtered.length?filtered.map(taskHTML).join(''):'<div class="empty">Sin tareas en esta categoría</div>';
}}

const TC={{'Member':'p-dark','FORMER MEMBER':'p-grey','member potencial':'p-ok','introjourney':'p-info','DUCK':'p-warn','PM':'p-ok','MANUAL':'p-warn','CASH':'p-warn','ENG':'p-info','INFLU':'p-grey','NO CANCELAR!':'p-danger'}};
const ST=['Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PM','ENG','NO CANCELAR!'];

function tags(ts){{return ts.filter(t=>ST.includes(t)).map(t=>`<span class="pill ${{TC[t]||'p-grey'}}">${{t}}</span>`).join('');}}
function noteCell(m){{
  const note=m.last_note||'';
  const link=`<a href="${{m.momence_notes_url}}" target="_blank" class="note-link">+ nota →</a>`;
  return note?`<span style="font-style:italic;color:#847366;font-size:11px">"${{note.slice(0,50)}}${{note.length>50?'…':''}}"</span> ${{link}}`:link;
}}

function renderNuevos(){{
  const ms=MEMBERS.filter(m=>m.is_new_member&&!m.is_platform).sort((a,b)=>a.days_inactive-b.days_inactive);
  document.getElementById('body-nuevos').innerHTML=ms.length?ms.map(m=>{{
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="color:#847366;font-size:11px">${{m.email}}</td>
      <td style="font-size:11px">${{m.phone||'—'}}</td>
      <td style="font-size:11px">${{m.new_member_purchase||m.membership_summary||'—'}}</td>
      <td style="text-align:center">${{m.visits}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="6" class="empty">Sin nuevos members esta semana</td></tr>';
}}

function renderActivos(){{
  const ms=MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform);
  document.getElementById('body-activos').innerHTML=ms.length?ms.map(m=>{{
    const ls=fmtDate(m.last_seen);
    const coaches=m.past_coaches&&m.past_coaches.length?m.past_coaches.join(', '):'—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="max-width:150px">${{tags(m.tags)}}</td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px;color:${{m.days_inactive>21?'#222323':m.days_inactive>14?'#854f0b':'#3b6d11'}}">${{ls}} <span style="font-size:10px;opacity:0.7">(${{m.days_inactive}}d)</span></td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="font-size:11px;color:#847366">${{coaches}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin datos</td></tr>';
}}

function renderRefrescar(){{
  const ms=MEMBERS.filter(m=>m.tags.includes('Member')&&!m.is_platform&&m.days_inactive>14).sort((a,b)=>b.days_inactive-a.days_inactive);
  document.getElementById('body-refrescar').innerHTML=ms.length?ms.map(m=>{{
    const ls=fmtDate(m.last_seen);
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="font-size:11px">${{m.membership_summary||'—'}}</td>
      <td style="font-size:11px">${{ls}}</td>
      <td style="font-weight:500;color:${{m.days_inactive>21?'#222323':'#854f0b'}}">${{m.days_inactive}}d</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="6" class="empty">Todos los members han venido recientemente</td></tr>';
}}

function renderIntro(){{
  const intros=MEMBERS.filter(m=>m.is_intro&&!m.is_platform).sort((a,b)=>(a.intro_classes_left||0)-(b.intro_classes_left||0));
  document.getElementById('body-intro').innerHTML=intros.length?intros.map(m=>{{
    const left=m.intro_classes_left||0;
    const used=m.intro_classes_used||0;
    const total=m.intro_classes_total||3;
    let urgLabel,urgCls;
    if(left===0){{urgLabel='Sin clases — URGENTE';urgCls='p-danger';}}
    else if(left===1){{urgLabel='1 restante — hablar hoy';urgCls='p-warn';}}
    else if(used>=2){{urgLabel='Momento de convertir';urgCls='p-warn';}}
    else{{urgLabel='Seguimiento';urgCls='p-ok';}}
    const expiry=m.intro_expiry_days!==null?`${{m.intro_expiry_days}}d`:'—';
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a><div style="font-size:10px;color:#847366">${{m.email}}</div></td>
      <td style="text-align:center"><span style="font-size:14px;font-weight:300">${{used}}/${{total}}</span><div style="font-size:10px;color:#847366">${{left}} restante${{left!==1?'s':''}}</div></td>
      <td>${{pl(urgLabel,urgCls)}}</td>
      <td style="font-size:11px;color:#aaa">${{m.prev_class||'—'}}</td>
      <td style="font-size:11px">${{m.next_class||'—'}}</td>
      <td style="text-align:center;color:${{m.intro_expiry_days!==null&&m.intro_expiry_days<=7?'#222323':'#847366'}};font-size:11px">${{expiry}}</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin Intro Journeys activos</td></tr>';
}}

function renderPotenciales(){{
  const pots=MEMBERS.filter(m=>!m.is_platform&&!m.tags.includes('Member')&&!m.is_intro&&m.days_inactive>30&&m.visits>0).sort((a,b)=>b.visits-a.visits);
  document.getElementById('body-pot').innerHTML=pots.length?pots.map(m=>{{
    return`<tr>
      <td><a href="${{m.momence_url}}" target="_blank" class="member-link">${{m.name}}</a></td>
      <td style="font-size:11px;color:#847366">${{m.email}}</td>
      <td style="font-size:11px">${{m.phone||'—'}}</td>
      <td style="font-size:11px">${{fmtDate(m.last_seen)}}</td>
      <td style="text-align:center;font-weight:500">${{m.visits}}</td>
      <td style="text-align:center;color:#847366">${{m.days_inactive}}d</td>
      <td>${{noteCell(m)}}</td>
    </tr>`;
  }}).join(''):'<tr><td colspan="7" class="empty">Sin potenciales</td></tr>';
}}

function renderBriefing(){{
  const today=new Date().toLocaleDateString('es-ES',{{weekday:'long',day:'numeric',month:'long'}});
  let txt=`aretē · briefing ${{today}}\\n${{Array(44).fill('—').join('')}}\\n\\n`;
  txt+=`members activos: {stats['active_members']} / 300 (${{Math.round({stats['active_members']}/3)}}%)\\n`;
  txt+=`tareas hoy: ${{TASKS_TODAY.length}} · esta semana: ${{TASKS_WEEK.length}}\\n\\n`;
  const byType=(tasks,type)=>tasks.filter(t=>t.type===type);
  const bienvenida=byType(TASKS_TODAY,'bienvenida');
  if(bienvenida.length){{txt+=`bienvenida a nuevos members (${{bienvenida.length}})\\n`;bienvenida.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}\\n`);txt+='\\n';}}
  const sinM=byType(TASKS_TODAY,'sin_metodo_pago');
  if(sinM.length){{txt+=`sin método de pago — hoy (${{sinM.length}})\\n`;sinM.forEach(t=>txt+=`· ${{t.name}} — ${{t.detail}}\\n`);txt+='\\n';}}
  const unpaid=byType(TASKS_TODAY,'reserva_unpaid');
  if(unpaid.length){{txt+=`reservas sin pagar — hoy (${{unpaid.length}})\\n`;unpaid.forEach(t=>txt+=`· ${{t.name}} — ${{t.detail}}\\n`);txt+='\\n';}}
  const packs=byType(TASKS_TODAY,'pack_expirando');
  if(packs.length){{txt+=`packs terminan hoy (${{packs.length}})\\n`;packs.forEach(t=>txt+=`· ${{t.name}}\\n`);txt+='\\n';}}
  const intros=byType(TASKS_TODAY,'intro_journey');
  if(intros.length){{txt+=`intro journey — acción hoy (${{intros.length}})\\n`;intros.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}\\n`);txt+='\\n';}}
  const semana=TASKS_WEEK.slice(0,8);
  if(semana.length){{txt+=`próximas acciones esta semana\\n`;semana.forEach(t=>txt+=`· ${{t.name}} — ${{t.action}}${{t.nc?' ('+t.nc+')':''}}\\n`);if(TASKS_WEEK.length>8)txt+=`· ...y ${{TASKS_WEEK.length-8}} más\\n`;}}
  txt+=`\\n${{Array(44).fill('—').join('')}}\\naretē · {TODAY_STR}`;
  document.getElementById('briefing-text').textContent=txt;
}}

function copyBriefing(){{navigator.clipboard.writeText(document.getElementById('briefing-text').textContent).then(()=>toast('Briefing copiado'));}}

function renderNotes(notes){{
  if(!notes||!notes.length) return '';
  const items=notes.map(n=>`<div style="display:flex;align-items:baseline;gap:8px;margin-bottom:3px"><span style="font-size:10px;color:#aaa;flex-shrink:0">${{n.date||''}}</span><span style="font-size:11px;color:#847366;font-style:italic">"${{n.content.slice(0,100)}}${{n.content.length>100?'…':''}}"</span></div>`).join('');
  return items;
}}

function renderEconomia(){{
  const MRR_BREAKDOWN={mrr_breakdown_json};
  const el=document.getElementById('mrr-breakdown');
  if(!el)return;
  const entries=Object.entries(MRR_BREAKDOWN).sort((a,b)=>b[1]-a[1]);
  const total=entries.reduce((s,e)=>s+e[1],0)||1;
  el.innerHTML=entries.map(([name,val])=>{{
    const pct=Math.round((val/total)*100);
    return`<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">
        <span style="font-size:12px;color:#222323">${{name}}</span>
        <span style="font-size:12px;font-weight:500">${{val.toFixed(0)}}€ <span style="font-size:10px;color:#847366">${{pct}}%</span></span>
      </div>
      <div style="height:3px;background:#f0f0f0;border-radius:2px"><div style="height:100%;width:${{pct}}%;background:#27303d;border-radius:2px"></div></div>
    </div>`;
  }}).join('');
}}

function init(){{
  filterList('today','');filterList('week','');
  renderNuevos();renderActivos();renderRefrescar();
  renderIntro();renderPotenciales();updateCounts();
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
    print(f'   {len(tag_ids)} tags')

    print('👥 Cargando members...')
    all_members = fetch_all_members(token)
    print(f'✅ {len(all_members)} members')

    RELEVANT = {'Member','FORMER MEMBER','member potencial','introjourney','DUCK','INFLU','MANUAL','CASH','PAGO FALLIDO','NO CANCELAR!'}
    relevant = []
    for m in all_members:
        tns = {t['name'] for t in m.get('customerTags', [])}
        visits = m.get('visits', {}).get('totalVisits', 0)
        if bool(tns & RELEVANT) or visits >= 3:
            relevant.append(m)

    print(f'   Procesando {len(relevant)} relevantes...')
    members_data = []
    for i, member in enumerate(relevant):
        if i % 20 == 0: print(f'   {i}/{len(relevant)}...')
        if i > 0 and i % 80 == 0:
            print('   Refrescando token...')
            token = get_token()
        result = process_member(token, member, tag_ids)
        if result: members_data.append(result)

    print(f'✅ {len(members_data)} procesados')

    active = sum(1 for m in members_data if 'Member' in m['tags'] and not m['is_platform'])
    intro = sum(1 for m in members_data if m['is_intro'] and not m['is_platform'])
    new_members = sum(1 for m in members_data if m['is_new_member'] and not m['is_platform'])
    potencial = sum(1 for m in members_data if
        not m['is_platform'] and not any(t in m['tags'] for t in ['Member','introjourney','member potencial']) and
        m['days_inactive'] > 30 and m['visits'] > 0)
    no_pm = sum(1 for m in members_data if
        'Member' in m['tags'] and not m['is_platform'] and not m['has_pm'] and m['has_subscription'])
    to_refresh = sum(1 for m in members_data if
        'Member' in m['tags'] and not m['is_platform'] and m['days_inactive'] > 14)

    # MRR calculations
    total_mrr = sum(m['mrr'] for m in members_data if m and 'Member' in m['tags'] and not m['is_platform'])
    mrr_at_risk = sum(m['mrr'] for m in members_data if m and 'Member' in m['tags'] and not m['is_platform'] and not m['has_pm'] and m['has_subscription'])
    mrr_failed = sum(m['mrr'] for m in members_data if m and 'Member' in m['tags'] and not m['is_platform'] and m['mrr'] > 0 and not m['has_pm'])
    ltv_values = [m.get('ltv', 0) for m in members_data if m and 'Member' in m['tags'] and not m['is_platform']]
    avg_ltv = sum(ltv_values) / len(ltv_values) if ltv_values else 0

    # MRR by membership type
    mrr_by_type = {}
    for m in members_data:
        if not m or 'Member' not in m['tags'] or m['is_platform']: continue
        for mem in m.get('active_memberships', []) if 'active_memberships' in m else []:
            pass
    # Simpler: group by membership_summary prefix
    mrr_breakdown = {}
    for m in members_data:
        if not m or 'Member' not in m['tags'] or m['is_platform'] or m['mrr'] <= 0: continue
        mem_name = m['membership_summary'].split('·')[0].strip() if m['membership_summary'] else 'Otro'
        mrr_breakdown[mem_name] = mrr_breakdown.get(mem_name, 0) + m['mrr']

    stats = {
        'active_members': active, 'intro_count': intro,
        'new_members': new_members, 'potenciales': potencial,
        'no_payment_method': no_pm, 'to_refresh': to_refresh,
        'total_mrr': round(total_mrr, 2),
        'mrr_at_risk': round(mrr_at_risk, 2),
        'avg_ltv': round(avg_ltv, 2),
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
    print(f'   Members: {active} / 300 · Nuevos: {new_members} · Intro: {intro}')
    print(f'   Sin PM: {no_pm} · A refrescar: {to_refresh}')
    print(f'   Tareas hoy: {len(tasks_today)} · Semana: {len(tasks_week)}')

if __name__ == '__main__':
    main()
