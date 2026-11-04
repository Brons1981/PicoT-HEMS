"""Door ventilation adjustment through durable, feedback-confirmed commands."""
import copy
import json
import time
import uuid

from .control import DOWNSTAIRS_FAN, PENDING


class DoorFan:
    def __init__(self, heating):
        self.heating = heating
        with heating.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_door_fan (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_door_fan WHERE id=1').fetchone()
        self.data = json.loads(row[0]) if row else dict(active=False, request=None, option=None)

    def save(self):
        with self.heating.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO hc_door_fan VALUES (1, ?)',
                       (json.dumps(self.data, allow_nan=False),))

    def desired(self, config, now, plan=None):
        heating = self.heating
        plan = heating.plan(config, now) if plan is None else plan
        view = heating.schedule.view(now)
        source = plan['sources']['beneden']
        if (not plan['enabled'] or 'beneden' not in heating.data['owned']
                or 'beneden' in heating.data['faults']
                or 'beneden' in plan.get('data_grace_sources', [])
                or not source['available'] or source['state'] != 'heat' or source['pending']
                or any(h['active'] and 'beneden' in h['zones'] for h in view['overrides'])):
            return None
        door = view['door'] or {}
        elapsed = now - door.get('since', now)
        if door.get('value') == 'on' and elapsed >= view['settings']['door_open_seconds']:
            return 'stil'
        if (self.data['active'] and door.get('value') == 'off'
                and elapsed >= view['settings']['door_close_seconds']):
            return 'auto'
        return None

    def tick(self, config, now):
        heating = self.heating
        records = {c['id']: c for c in heating.control.records()}
        last = records.get(self.data['request'])
        if last and last['status'] in PENDING:
            return
        if last and last['status'] in ('confirmed', 'already_set') and last['value'] == 'auto':
            self.data.update(active=False, request=None, option=None)
            self.save()
        option = self.desired(config, now)
        if option is None:
            return
        fan = heating.control.states.get(DOWNSTAIRS_FAN, {})
        if (fan.get('state') in (None, 'unknown', 'unavailable')
                or option not in (fan.get('attributes') or {}).get('options', [])):
            return
        # Never replay an uncertain command. A changed door decision can issue
        # its own command, but repeated polls of one decision cannot flood HA.
        if self.data['request'] and self.data['option'] == option:
            return
        request_id = str(uuid.uuid4())

        def guard():
            if self.desired(config, time.time()) != option:
                raise ValueError('Achterdeur of bronkeuze gewijzigd; ventilator blijft ongewijzigd.')
            previous = copy.deepcopy(self.data)
            self.data.update(active=True, request=request_id, option=option)
            try:
                self.save()
            except Exception:
                self.data = previous
                raise

        try:
            heating.control.submit(dict(request_id=request_id, source='beneden', field='fan', value=option),
                                   config['stale_seconds'], origin='schedule', guard=guard)
        except ValueError:
            return

    def view(self, config, now, plan):
        option = self.desired(config, now, plan)
        fan = self.heating.control.states.get(DOWNSTAIRS_FAN, {})
        command = next((c for c in self.heating.control.records()
                        if c['id'] == self.data['request']), {})
        reason = None
        if option:
            if (fan.get('state') in (None, 'unknown', 'unavailable')
                    or option not in (fan.get('attributes') or {}).get('options', [])):
                reason = 'Ventilatorselectie niet beschikbaar; airco blijft op zijn bestaande stand.'
            elif command.get('status') in ('failed', 'uncertain', 'timed_out', 'interrupted'):
                reason = 'Ventilatoropdracht niet bevestigd; controleer de ventilatorstand.'
            elif fan.get('state') == option:
                reason = ('Achterdeur open: ventilator stil; airco blijft aan.' if option == 'stil'
                          else 'Achterdeur gesloten: ventilator weer automatisch.')
            else:
                reason = 'Ventilator wacht op bevestiging van stand ' + option + '.'
        return dict(entity_id=DOWNSTAIRS_FAN, option=option, reported=fan.get('state'), reason=reason)
