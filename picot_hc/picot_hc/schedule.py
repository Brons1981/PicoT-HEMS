"""Opt-in weekly downstairs setpoints; manual changes always take precedence."""
import copy
import json
import math
import re
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .control import PENDING, numeric
from .core import observation, timestamp

TZ = ZoneInfo('Europe/Amsterdam')
DOOR = 'binary_sensor.1_3_woonkamer_deur_raam_sensor_achterdeur_contact'


def validate_settings(value):
    keys = {'enabled', 'source', 'entries', 'door_open_seconds', 'door_close_seconds', 'sensor_max_age_seconds'}
    if not isinstance(value, dict) or set(value) != keys or type(value['enabled']) is not bool:
        raise ValueError('Ongeldige schema-instellingen.')
    if value['source'] not in ('cv', 'beneden'):
        raise ValueError('Kies cv of airco beneden.')
    for key in ('door_open_seconds', 'door_close_seconds'):
        if type(value[key]) is not int or not 0 <= value[key] <= 1800:
            raise ValueError('Deurvertraging moet tussen 0 en 1800 seconden liggen.')
    if type(value['sensor_max_age_seconds']) is not int or not 30 <= value['sensor_max_age_seconds'] <= 86400:
        raise ValueError('Maximale meetleeftijd moet tussen 30 en 86400 seconden liggen.')
    entries = value['entries']
    if not isinstance(entries, list) or len(entries) > 56 or (value['enabled'] and not entries):
        raise ValueError('Voeg 1 tot 56 schemamomenten toe voordat je het schema inschakelt.')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'day', 'time', 'temperature'}:
            raise ValueError('Geef per moment dag, tijd en temperatuur op.')
        if type(entry['day']) is not int or not 0 <= entry['day'] <= 6:
            raise ValueError('Ongeldige weekdag.')
        if not isinstance(entry['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', entry['time']):
            raise ValueError('Gebruik een tijd als 07:30.')
        temp = entry['temperature']
        if type(temp) not in (int, float) or not math.isfinite(temp) or not 5 <= temp <= 35:
            raise ValueError('Gebruik een temperatuur tussen 5 en 35 °C; apparaat- en comfortgrenzen gelden ook.')
        key = (entry['day'], entry['time'])
        if key in seen:
            raise ValueError('Twee momenten op dezelfde dag en tijd zijn niet toegestaan.')
        seen.add(key)
    result = copy.deepcopy(value)
    result['entries'].sort(key=lambda e: (e['day'], e['time']))
    return result


def moments(settings, now):
    """Local weekly wall times. Skip missing spring times; autumn fold runs once."""
    date = datetime.fromtimestamp(now, TZ).date()
    result = []
    for offset in range(-8, 9):
        day = date + timedelta(days=offset)
        for entry in settings['entries']:
            if day.weekday() != entry['day']:
                continue
            wall = datetime.fromisoformat(str(day) + 'T' + entry['time'])
            instant = wall.replace(tzinfo=TZ, fold=0).timestamp()
            if datetime.fromtimestamp(instant, TZ).replace(tzinfo=None) != wall:
                continue
            result.append(dict(entry, at=instant))
    result.sort(key=lambda e: e['at'])
    previous = [e for e in result if e['at'] <= now]
    following = [e for e in result if e['at'] > now]
    return (previous[-1] if previous else None, following[0] if following else None)


class Schedule:
    # All methods run under Control.lock, shared with reads, writes and observation.
    def __init__(self, control, store):
        self.control, self.store = control, store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_schedule (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_schedule WHERE id=1').fetchone()
        self.data = json.loads(row[0]) if row else dict(
            settings=dict(enabled=False, source='cv', entries=[], door_open_seconds=60, door_close_seconds=120, sensor_max_age_seconds=900),
            revision=0, baseline={}, override=None, action=None, fault=None, door=None)
        self.ready = False
        self.reason = 'Wachten op actuele HA-gegevens.'
        if self.data['settings']['enabled']:
            # Never replay an unfinished action or assume what happened while HC was down.
            action = self.data['action']
            command = next((c for c in control.records() if action and c['id'] == action['id']), None)
            if action and (not command or command['status'] not in ('confirmed', 'already_set')):
                self.data['fault'] = 'HC is herstart. Controleer de bron en kies HC hervatten.'
            elif not self.data['override']:
                self.pause('HC herstart; regeling tijdelijk gepauzeerd.', time.time())
        self.control.observer = self.observe
        self.control.intent_observer = self.intent

    def save(self):
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_schedule VALUES (1, ?)',
                       (json.dumps(self.data, allow_nan=False),))

    def pause(self, reason, now):
        _, following = moments(self.data['settings'], now)
        self.data['override'] = dict(reason=reason, since=now, until=following['at'] if following else None)
        self.save()  # Must succeed before a manual command is allowed to dispatch.

    def update(self, payload, now):
        if not isinstance(payload, dict) or set(payload) != {'revision', 'settings'}:
            raise ValueError('Ongeldig schemaverzoek.')
        if type(payload['revision']) is not int or payload['revision'] != self.data['revision']:
            raise ValueError('Het schema is elders gewijzigd. Herlaad het dashboard.')
        settings = validate_settings(payload['settings'])
        if self.data['settings']['enabled'] and settings['source'] != self.data['settings']['source']:
            raise ValueError('Schakel het schema eerst uit voordat je een andere bron kiest.')
        previous = copy.deepcopy(self.data)
        self.data['settings'] = settings
        self.data['revision'] += 1
        self.data['action'] = None
        if not settings['enabled']:
            self.data.update(override=None, fault=None)
        elif self.data['override']:
            _, following = moments(settings, now)
            self.data['override']['until'] = following['at'] if following else None
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        return self.view(now)

    def resume(self, now):
        previous = copy.deepcopy(self.data)
        self.data.update(override=None, fault=None, action=None, recovered_at=now)
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        return self.view(now)

    def intent(self, command):
        if command.get('origin') != 'schedule' and self.data['settings']['enabled']:
            watched = {self.control.bindings[s]['entity_id'] for s in ('cv', 'beneden') if s in self.control.bindings}
            if command['entity_id'] in watched:
                self.pause('Handmatige bediening vanuit HC.', command['created'])

    def observe(self, states, started, now):
        records = self.control.records()
        if self.data['settings']['enabled'] and now < self.data.get('last_observed', now) - 5:
            self.data['fault'] = 'De klok is teruggezet. Controleer de tijd en kies HC hervatten.'
        self.data['last_observed'] = now
        changed = []
        for source in ('cv', 'beneden'):
            if source not in self.control.bindings:
                continue
            entity = self.control.bindings[source]['entity_id']
            item = states.get(entity, {})
            if item.get('state') in (None, 'unknown', 'unavailable'):
                continue
            attrs = item.get('attributes') or {}
            current = dict(mode=item['state'], temperature=numeric(attrs.get('temperature')), preset=attrs.get('preset_mode'))
            previous = self.data['baseline'].get(entity)
            if previous and self.data['settings']['enabled']:
                for field, value in current.items():
                    if value is None or previous.get(field) is None or value == previous[field]:
                        continue
                    # The latest command may echo its old or desired values while settling.
                    own = next((c for c in records if c['entity_id'] == entity and c.get('sent')
                                and c['sent'] <= now <= c['deadline'] and c['status'] != 'failed'
                                and (c['field'] == field or c['field'] == 'heating' or field == 'preset')), None)
                    expected = False
                    if own:
                        desired = ('heat' if field == 'mode' else own['value']) if own['field'] == 'heating' else own['value']
                        before = own.get('before', {}).get(field)
                        settling = own['status'] in PENDING
                        expected = ((settling or own.get('finished') == now) if field == 'preset' else
                                    value == desired or (settling and value == before))
                    if not expected:
                        changed.append(source)
            self.data['baseline'][entity] = current
        if changed:
            self.pause('Handmatige wijziging via thermostaat of HA (' + ', '.join(sorted(set(changed))) + ').', now)
        door_value = states.get(DOOR, {}).get('state')
        if door_value not in ('on', 'off'):
            door_value = 'unknown'
        old = self.data['door']
        if not self.ready or not old or old['value'] != door_value or now < old['since']:
            self.data['door'] = dict(value=door_value, since=now)
        self.ready = True
        self.save()

    def desired(self, now):
        settings = self.data['settings']
        previous, following = moments(settings, now)
        override = self.data['override']
        if override and override['until'] is not None and now >= override['until']:
            self.data['override'] = None
            self.data['action'] = None
            self.save()
        return previous, following

    def gate(self, now, config):
        settings = self.data['settings']
        self.desired(now)
        if not settings['enabled']:
            return 'Schema staat uit.'
        if self.data['override']:
            return self.data['override']['reason']
        if self.data['fault']:
            return self.data['fault']
        bad = next((c for c in self.control.records() if c['source'] in ('cv', 'beneden')
                    and c['created'] > self.data.get('recovered_at', 0)
                    and c['status'] in ('failed', 'timed_out', 'interrupted')), None)
        if bad:
            return 'Een eerdere opdracht is niet bevestigd. Controleer de bron en kies HC hervatten.'
        if not self.ready or not self.control.connected or now - (self.control.received or 0) > config['stale_seconds']:
            return 'Wachten op actuele HA-gegevens.'
        other = 'beneden' if settings['source'] == 'cv' else 'cv'
        other_entity = self.control.bindings.get(other, {}).get('entity_id')
        if self.control.states.get(other_entity, {}).get('state') not in ('off', 'fan_only'):
            return 'Zet de andere warmtebron beneden eerst uit; HC schakelt deze niet zelf om.'
        zone = next(z for z in config['zones'] if z['id'] == 'beneden')
        sample = observation(zone.get('temperature', ''), self.control.states, now, True, '°C')
        if sample['quality'] != 'available':
            return 'Wachten op een gekoppelde, bruikbare temperatuursensor beneden.'
        sensor = self.control.states.get(zone.get('temperature'), {})
        try:
            reported = timestamp(sensor.get('last_reported') or sensor.get('last_updated'))
        except (ValueError, TypeError):
            return 'Temperatuursensor heeft geen bruikbare meettijd.'
        if not 0 <= now - reported <= settings['sensor_max_age_seconds']:
            return 'Temperatuurmeting beneden is verouderd; geen nieuwe schemaopdracht.'
        if zone.get('minimum') is None or zone.get('maximum') is None:
            return 'Stel eerst minimum en maximum voor beneden in.'
        return None

    def target(self, now):
        previous, _ = moments(self.data['settings'], now)
        if not previous:
            return None
        settings = self.data['settings']
        door = self.data['door'] or dict(value='unknown', since=now)
        blocked = settings['source'] == 'beneden' and (
            door['value'] == 'unknown' or
            (door['value'] == 'on' and now-door['since'] >= settings['door_open_seconds']) or
            (door['value'] == 'off' and now-door['since'] < settings['door_close_seconds']))
        return dict(slot=previous['at'], source=settings['source'], field='mode' if blocked else 'heating',
                    value='off' if blocked else previous['temperature'])

    def tick(self, config, now=None):
        now = time.time() if now is None else now
        self.reason = self.gate(now, config)
        if self.reason:
            return
        target = self.target(now)
        if not target:
            self.reason = 'Geen schemamoment beschikbaar.'
            return
        pending = [c for c in self.control.records() if c['source'] in ('cv', 'beneden') and c['status'] in PENDING]
        stop_preempts = target['field'] == 'mode' and not any(c['field'] == 'mode' and c['value'] == 'off' for c in pending)
        if pending and not stop_preempts:
            self.reason = 'Wachten op terugmelding; geen nieuwe schemaopdracht.'
            return
        action = self.data['action']
        if action and action['target'] == target:
            command = next((c for c in self.control.records() if c['id'] == action['id']), None)
            if not command or command['status'] not in ('confirmed', 'already_set'):
                self.data['fault'] = 'Schemaopdracht niet bevestigd. Controleer de bron en kies HC hervatten.'
                self.save()
            self.reason = self.data['fault'] or ('Achterdeur blokkeert airco beneden.' if target['field'] == 'mode' else 'Schema-instelling bevestigd.')
            return
        zone = next(z for z in config['zones'] if z['id'] == 'beneden')
        if target['field'] == 'heating' and not zone['minimum'] <= target['value'] <= zone['maximum']:
            self.reason = 'Schemadoel ligt buiten de comfortgrenzen beneden.'
            return
        if target['field'] == 'mode' and not action:
            self.reason = 'Achterdeur nog niet bevestigd dicht; geen verwarming gestart.'
            return
        action = dict(id=str(uuid.uuid4()), target=target)
        self.data['action'] = action
        self.save()  # Never dispatch an unrecorded action, even on process termination.
        def guard():
            fresh = time.time()
            reason = self.gate(fresh, config)
            if reason or self.target(fresh) != target:
                raise ValueError(reason or 'Schemamoment is gewijzigd; geen opdracht verstuurd.')
        try:
            command = self.control.submit(dict(request_id=action['id'], source=target['source'],
                field=target['field'], value=target['value']), config['stale_seconds'], origin='schedule', guard=guard)
            self.reason = 'Achterdeur blokkeert airco beneden.' if target['field'] == 'mode' else 'Schemadoel verstuurd; wachten op terugmelding.'
            if command['status'] == 'failed':
                raise ValueError(command['error'])
        except ValueError as exc:
            self.data['fault'] = str(exc) + ' Controleer en kies HC hervatten.'
            self.save()
            self.reason = self.data['fault']

    def view(self, now):
        previous, following = moments(self.data['settings'], now)
        return dict(settings=copy.deepcopy(self.data['settings']), revision=self.data['revision'],
                    override=copy.deepcopy(self.data['override']), fault=self.data['fault'],
                    reason=('Schema staat uit.' if not self.data['settings']['enabled'] else
                            self.data['override']['reason'] if self.data['override'] else self.data['fault'] or self.reason),
                    current=previous, next=following, door=copy.deepcopy(self.data['door']))
