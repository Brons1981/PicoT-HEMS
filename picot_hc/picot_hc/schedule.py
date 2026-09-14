"""Comfort requirements for a future cost planner; never a device scheduler."""
import copy
import json
import math
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .control import PENDING, numeric

TZ = ZoneInfo('Europe/Amsterdam')
DOOR = 'binary_sensor.1_3_woonkamer_deur_raam_sensor_achterdeur_contact'
WEEK = 7 * 1440


def minutes(value, *, end=False):
    if end and value == '24:00':
        return 1440
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('Gebruik HH:MM; alleen een eindtijd mag 24:00 zijn.')
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def validate_settings(value):
    keys = {'enabled', 'windows', 'optimization_band', 'door_open_seconds', 'door_close_seconds', 'sensor_max_age_seconds'}
    if not isinstance(value, dict) or set(value) != keys or type(value['enabled']) is not bool:
        raise ValueError('Ongeldige comfortinstellingen; het schema heeft geen bronkeuze.')
    band = value['optimization_band']
    if type(band) not in (int, float) or not math.isfinite(band) or not 0 <= band <= 5:
        raise ValueError('Optimalisatieband moet tussen 0 en 5 °C liggen (±).')
    for key in ('door_open_seconds', 'door_close_seconds'):
        if type(value[key]) is not int or not 0 <= value[key] <= 1800:
            raise ValueError('Deurvertraging moet tussen 0 en 1800 seconden liggen.')
    if type(value['sensor_max_age_seconds']) is not int or not 30 <= value['sensor_max_age_seconds'] <= 86400:
        raise ValueError('Maximale meetleeftijd moet tussen 30 en 86400 seconden liggen.')
    windows = value['windows']
    if not isinstance(windows, list) or len(windows) > 112 or (value['enabled'] and not windows):
        raise ValueError('Voeg 1 tot 112 tijdvensters toe voordat je het comfortschema gebruikt.')
    spans = []
    for window in windows:
        if not isinstance(window, dict) or set(window) != {'day', 'start', 'end', 'target', 'hard'}:
            raise ValueError('Geef dag, begin/einde, temperatuur en comfortkeuze op.')
        if type(window['day']) is not int or not 0 <= window['day'] <= 6 or type(window['hard']) is not bool:
            raise ValueError('Ongeldige weekdag of harde grens.')
        start, end = minutes(window['start']), minutes(window['end'], end=True)
        if start == end:
            raise ValueError('Begin en einde zijn gelijk; gebruik 00:00–24:00 voor een hele dag.')
        if end < start:
            end += 1440
        target = window['target']
        if type(target) not in (int, float) or not math.isfinite(target) or not 5 <= target <= 35:
            raise ValueError('Temperatuur moet tussen 5 en 35 °C liggen.')
        begin, finish = window['day'] * 1440 + start, window['day'] * 1440 + end
        spans.append((begin, min(finish, WEEK)))
        if finish > WEEK:
            spans.append((0, finish-WEEK))
    spans.sort()
    if any(b[0] < a[1] for a, b in zip(spans, spans[1:])):
        raise ValueError('Tijdvensters overlappen, mogelijk over middernacht of de weekgrens.')
    result = copy.deepcopy(value)
    result['windows'].sort(key=lambda w: (w['day'], w['start']))
    return result


def wall_time(day, minute, *, end=False):
    wall = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
    # Use the same first autumn occurrence for adjacent boundaries; move spring gaps forward.
    for _ in range(181):
        instant = wall.replace(tzinfo=TZ, fold=0).timestamp()
        if datetime.fromtimestamp(instant, TZ).replace(tzinfo=None) == wall:
            return instant
        wall += timedelta(minutes=1)
    raise ValueError('Lokale tijd kan niet worden omgezet.')


def occurrences(settings, now):
    date = datetime.fromtimestamp(now, TZ).date()
    result = []
    for offset in range(-1, 9):
        day = date + timedelta(days=offset)
        for window in settings['windows']:
            if day.weekday() != window['day']:
                continue
            start, end = minutes(window['start']), minutes(window['end'], end=True)
            if end < start:
                end += 1440
            begin, finish = wall_time(day, start), wall_time(day, end, end=True)
            if begin < finish:
                band = 0 if window['hard'] else settings['optimization_band']
                result.append(dict(window, minimum=max(5, window['target']-band),
                                   maximum=min(35, window['target']+band), starts_at=begin, ends_at=finish, required_at=begin,
                                   zone='beneden', kind='window'))
    return sorted(result, key=lambda w: (w['starts_at'], w['ends_at']))


def next_boundary(settings, now):
    if not settings['enabled']:
        return None
    boundaries = [w[k] for w in occurrences(settings, now) for k in ('starts_at', 'ends_at') if w[k] > now]
    return min(boundaries) if boundaries else None


def migrate_settings(old):
    """Preserve dev.9's weekly temperatures, archive source choice, require review."""
    result = dict(enabled=False, windows=[], optimization_band=1, door_open_seconds=old.get('door_open_seconds', 60),
                  door_close_seconds=old.get('door_close_seconds', 120),
                  sensor_max_age_seconds=old.get('sensor_max_age_seconds', 900))
    entries = sorted(old.get('entries', []), key=lambda e: (e['day'], e['time']))
    for index, entry in enumerate(entries):
        start = entry['day'] * 1440 + minutes(entry['time'])
        following = entries[(index+1) % len(entries)]
        finish = following['day'] * 1440 + minutes(following['time'])
        if finish <= start:
            finish += WEEK
        while start < finish:
            end = min(finish, (start // 1440 + 1)*1440)
            day, minute = divmod(start, 1440)
            last = end - day*1440
            result['windows'].append(dict(day=day % 7, start=f'{minute//60:02}:{minute%60:02}',
                end=f'{last//60:02}:{last%60:02}', target=entry['temperature'], hard=True))
            start = end
    return validate_settings(result)


class Schedule:
    # Runtime serializes this state with Control.lock. No method dispatches services.
    def __init__(self, control, store, config):
        self.control, self.store, self.config = control, store, config
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_schedule (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_schedule WHERE id=1').fetchone()
        old = json.loads(row[0]) if row else None
        if old and old.get('format') not in (2, 3):
            self.data = dict(format=3, settings=migrate_settings(old['settings']), revision=old['revision']+1,
                baseline=old.get('baseline', {}), overrides={}, door=old.get('door'), legacy_pause=old.get('override'),
                migration='Bestaande schakelmomenten zijn omgezet naar comfortvensters. Controleer grenzen en schakel het comfortschema opnieuw in.')
            with store.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS hc_schedule_archive (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('INSERT OR IGNORE INTO hc_schedule_archive VALUES (1, ?)', (json.dumps(old),))
                db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)', (json.dumps(self.data),))
        elif old and old.get('format') == 2:
            self.data = copy.deepcopy(old)
            settings = self.data['settings']
            settings['optimization_band'] = 1
            changed = False
            for window in settings['windows']:
                band = 0 if window['hard'] else 1
                changed |= (window['minimum'] != max(5, window['target']-band)
                            or window['maximum'] != min(35, window['target']+band))
                del window['minimum'], window['maximum']
            if changed:
                settings['enabled'] = False
                self.data['migration'] = 'Controleer de centrale optimalisatieband (±1 °C) en comfortkeuzes; oude grenzen zijn veranderd. Schakel daarna het schema opnieuw in.'
            self.data.update(format=3, revision=old['revision']+1)
            validate_settings(settings)
            with store.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS hc_schedule_archive (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('INSERT OR IGNORE INTO hc_schedule_archive VALUES (2, ?)', (json.dumps(old),))
                db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)', (json.dumps(self.data),))
        else:
            self.data = old or dict(format=3, settings=migrate_settings({}), revision=0,
                                   baseline={}, overrides={}, door=None, legacy_pause=None, migration=None)
        self.ready = False
        self.control.observer = self.observe
        self.control.intent_observer = self.intent

    def save(self):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)',
                       (json.dumps(self.data, allow_nan=False),))

    def update(self, payload, now):
        if not isinstance(payload, dict) or set(payload) != {'revision', 'settings'}:
            raise ValueError('Ongeldig comfortverzoek.')
        if type(payload['revision']) is not int or payload['revision'] != self.data['revision']:
            raise ValueError('Het schema is elders gewijzigd. Herlaad het dashboard.')
        settings = validate_settings(payload['settings'])
        previous = copy.deepcopy(self.data)
        self.data.update(settings=settings, revision=self.data['revision']+1, migration=None)
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        return self.view(now)

    def resume(self, now):
        previous = copy.deepcopy(self.data)
        self.data.update(overrides={}, legacy_pause=None)
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        return self.view(now)

    def hold(self, source, field, value, now, reason, *, command=None, mode=None):
        binding = self.control.bindings[source]
        zones = ['beneden', 'boven'] if source == 'cv' else [source]
        until = next_boundary(self.data['settings'], now) if 'beneden' in zones else None
        self.data['overrides'][binding['entity_id']] = dict(source=source, entity_id=binding['entity_id'],
            zones=zones, field=field, value=value, temperature=value if field == 'temperature' else None,
            mode=mode, forced_source=field == 'temperature', since=now, until=until,
            command_id=command, reason=reason)
        self.save()

    def intent(self, command):
        if command.get('origin', 'manual') == 'manual':
            self.hold(command['source'], command['field'], command['value'], command['created'],
                      'Handmatige broninstelling vanuit HC.', command=command['id'], mode=command['before']['mode'])

    def observe(self, states, started, now):
        records = self.control.records()
        for source, binding in self.control.bindings.items():
            entity = binding['entity_id']
            item = states.get(entity, {})
            if item.get('state') in (None, 'unknown', 'unavailable'):
                continue
            attrs = item.get('attributes') or {}
            current = dict(mode=item['state'], temperature=numeric(attrs.get('temperature')), preset=attrs.get('preset_mode'))
            previous = self.data['baseline'].get(entity)
            changes = []
            if previous:
                for field, value in current.items():
                    if value is None or previous.get(field) is None or value == previous[field]:
                        continue
                    own = next((c for c in records if c['entity_id'] == entity and c.get('sent')
                                and c['sent'] <= now <= c['deadline'] and c['status'] != 'failed'
                                and (c['field'] == field or (field == 'mode' and c['field'] == 'state')
                                     or c['field'] == 'heating' or field == 'preset')), None)
                    expected = False
                    if own:
                        desired = ('heat' if field == 'mode' else own['value']) if own['field'] == 'heating' else own['value']
                        settling = own['status'] in PENDING
                        expected = ((settling or own.get('finished') == now) if field == 'preset' else
                                    value == desired or (settling and value == own.get('before', {}).get(field)))
                    if not expected:
                        changes.append(field)
            if changes:
                # An explicit off/mode/preset remains a hold; a setpoint change forces its source.
                field = 'temperature' if 'temperature' in changes and current['mode'] != 'off' else changes[0]
                self.hold(source, field, current[field], now, 'Handmatige wijziging via thermostaat of HA.', mode=current['mode'])
            self.data['baseline'][entity] = current
        door_value = states.get(DOOR, {}).get('state')
        if door_value not in ('on', 'off'):
            door_value = 'unknown'
        old = self.data['door']
        if not self.ready or not old or old['value'] != door_value or now < old['since']:
            self.data['door'] = dict(value=door_value, since=now)
        self.ready = True
        self.tick(self.config, now)

    def tick(self, config, now=None):
        self.config = config
        now = time.time() if now is None else now
        self.data['overrides'] = {k:v for k,v in self.data['overrides'].items() if v['until'] is None or now < v['until']}
        if self.data.get('legacy_pause') and self.data['legacy_pause'].get('until') is not None and now >= self.data['legacy_pause']['until']:
            self.data['legacy_pause'] = None
        self.save()

    def view(self, now):
        settings = self.data['settings']
        windows = occurrences(settings, now) if settings['enabled'] else []
        active = next((w for w in windows if w['starts_at'] <= now < w['ends_at']), None)
        following = next((w for w in windows if w['starts_at'] > now), None)
        horizon = [w for w in windows if w['ends_at'] > now and w['starts_at'] < now + 48*3600]
        records = {c['id']:c for c in self.control.records()}
        overrides = []
        for value in self.data['overrides'].values():
            if value['until'] is not None and now >= value['until']:
                continue
            command = records.get(value['command_id'])
            status = command['status'] if command else ('unrecorded' if value['command_id'] else 'observed')
            overrides.append(dict(value, status=status, confirmed=status in ('observed','confirmed','already_set'),
                                  active=status not in ('failed','superseded','unrecorded')))
        zones = {}
        for zone in self.config['zones']:
            fixed = dict(zone=zone['id'], kind='fixed' if zone['id'] != 'beneden' else 'fallback',
                         target=zone.get('target'), minimum=zone.get('minimum') if zone.get('minimum') is not None else zone.get('target'),
                         maximum=zone.get('maximum') if zone.get('maximum') is not None else zone.get('target'),
                         hard=False, required_at=None)
            request = active if zone['id'] == 'beneden' and active else fixed if fixed['target'] is not None else None
            errors = []
            if request:
                if zone.get('minimum') is not None and request['minimum'] is not None and request['minimum'] < zone['minimum']:
                    errors.append('Vensterminimum ligt onder de algemene comfortgrens.')
                if zone.get('maximum') is not None and request['maximum'] is not None and request['maximum'] > zone['maximum']:
                    errors.append('Venstermaximum ligt boven de algemene comfortgrens.')
            zones[zone['id']] = dict(request=request, bounds={k:zone.get(k) for k in ('minimum','maximum')}, errors=errors,
                source_constraints=[v for v in overrides if zone['id'] in v['zones']],
                humidity={k:zone.get('humidity_'+k) for k in ('min','target','max')} if zone['id']=='boven' else None)
        return dict(settings=copy.deepcopy(settings), revision=self.data['revision'], current=active, next=following,
            next_boundary=next_boundary(settings, now), overrides=overrides, legacy_pause=copy.deepcopy(self.data.get('legacy_pause')),
            migration=self.data.get('migration'), door=copy.deepcopy(self.data['door']),
            reason='Comfortschema als plannerinvoer beschikbaar.' if settings['enabled'] else 'Tijdvensters staan uit; vaste basiswaarden blijven beschikbaar.',
            comfort=dict(zones=zones, horizon=horizon,
                         deadlines=[w for w in horizon if w['hard'] and w['starts_at'] > now],
                         source_policy='lowest_total_cost_within_comfort', selected_sources=None,
                         priority=['manual_source_constraints', 'comfort_constraints', 'total_cost'],
                         cost_factors=['energy_prices', 'efficiency', 'heat_loss', 'reheat_energy'],
                         planner_status='not_implemented',
                         planner_reason='Financiële bronkeuze en voorverwarmen volgen met het woningmodel; het comfortschema stuurt geen apparaten aan.'))
