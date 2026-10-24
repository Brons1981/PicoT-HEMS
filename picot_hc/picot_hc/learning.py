"""Bounded downstairs start-time, setback and coast learning; no economic optimizer.

Only complete preheat attempts tune start time and setback; cooling evidence gates coasting.
Runtime serializes access with Control.lock. Reads never mutate the model.
"""
import copy
import json

from .cooling import Cooling
from .thermal_weather import comparable


DEFAULTS = dict(learning_enabled=False, initial_preheat_minutes=45, max_preheat_minutes=180,
                adaptive_setback_enabled=False, coast_enabled=False, max_coast_minutes=60)


class Learning:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_learning (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_learning WHERE id=1').fetchone()
        self.data = json.loads(row[0]) if row else dict(signature=None, lead=None, outcomes=[])
        # Never train across a restart, missing observations or an edited schedule.
        self.session = None
        self.cooling = Cooling(store)

    @staticmethod
    def signature(view):
        return json.dumps(view['settings'], sort_keys=True)

    def status(self, view, context=None):
        settings = dict(DEFAULTS, **view['settings'])
        matches = self.data['signature'] == self.signature(view)
        lead = self.data['lead'] if matches and self.data['lead'] is not None else settings['initial_preheat_minutes']
        outcomes = self.data['outcomes'] if matches else []
        weather = (context or {}).get('weather')
        weather_outcomes = [o for o in outcomes if comparable(o, context or {})]
        depth = self.data.get('depth', 1) if matches else 1
        if weather is not None or any(o.get('weather') is not None for o in outcomes):
            if len(weather_outcomes) >= 3:
                lead = max(o['next_lead_minutes'] for o in weather_outcomes[-3:])
                depth = min(o.get('next_depth', 1) for o in weather_outcomes[-3:])
            else:
                lead = max(lead, settings['initial_preheat_minutes'])
                depth = min(depth, 1)
        return dict(enabled=settings['enabled'] and settings['learning_enabled'],
            lead_minutes=min(lead, settings['max_preheat_minutes']),
            outcomes=copy.deepcopy(self.data['outcomes'] if matches else []),
            setback_depth=depth, weather=copy.deepcopy(weather), weather_samples=len(weather_outcomes),
            method='deadline_feedback', economic_optimization=False)

    def recommendation(self, view, now, enabled, context=None):
        status = self.status(view, context)
        window = view['next']
        active = view['current']
        # An existing comfort window keeps its own bounds and target.
        preheat = bool(enabled and status['enabled'] and not active and window
                       and window['starts_at']-status['lead_minutes']*60 <= now < window['starts_at'])
        settings = view['settings']
        estimate = self.cooling.estimate(context, now)
        phase, target = ('preheat', window['target']) if preheat else ('comfort' if active else 'fixed', None)
        if enabled and status['enabled']:
            if not active and not preheat and window and settings.get('adaptive_setback_enabled'):
                depth = status['setback_depth'] if estimate['cooling_rate'] is not None else min(1, status['setback_depth'])
                target = max(settings['setback_temperature'], window['target']-depth)
                phase = 'setback'
            if (active and settings.get('coast_enabled') and not active['hard']
                    and active['target']-active['minimum'] >= .5
                    and 0 < active['ends_at']-now <= settings['max_coast_minutes']*60
                    and self.cooling.blocked != (view['revision'], active['ends_at'])
                    and context and context['valid'] and estimate['cooling_rate'] is not None
                    and settings['setback_temperature'] <= active['target']-.5
                    and not (window and window['starts_at'] <= active['ends_at']+status['lead_minutes']*60
                             and window['target'] > active['target']-.5)):
                predicted = context['indoor']-estimate['cooling_rate']*(active['ends_at']-now)/3600
                if predicted >= active['minimum']+.15:
                    phase, target = 'coast', active['target']-.5
        return dict(status, **estimate, phase=phase, preheating=preheat, target=target)

    def observe(self, view, plan, now, max_gap, context=None):
        if context is not None:
            self.cooling.observe(context, plan, view, now, max_gap)
        status = self.status(view, context)
        door = view['door'] or {}
        down = plan['zones']['beneden']
        valid = (plan['enabled'] and status['enabled'] and plan['price'] is not None
                 and door.get('value') == 'off'
                 and now-door.get('since', now) >= view['settings']['door_close_seconds']
                 and down['reason'] in ('Warmtevraag.', 'Temperatuur handhaven.',
                                       'Temperatuur bereikt; geen warmtevraag.'))
        signature = self.signature(view)
        session = self.session
        if not valid or session and (session['signature'] != signature
                                    or not 0 < now-session['last'] <= max_gap
                                    or not comparable(session, context or {})):
            self.session = None
            return
        if session and now >= session['deadline']:
            self.session = None
            if now-session['deadline'] > max_gap or not session['heated']:
                return
            lead = session['lead']
            reached = session['reached'] if down['temperature'] >= session['target'] else None
            if down['temperature'] < session['minimum']:
                result, lead = 'late', min(view['settings']['max_preheat_minutes'], lead+15)
            elif reached is not None and session['deadline']-reached >= 15*60:
                result, lead = 'early', max(15, lead-5)
            else:
                result = 'on_time'
            outcome = dict(deadline=session['deadline'], result=result, temperature=down['temperature'],
                           target=session['target'], lead_minutes=session['lead'], next_lead_minutes=lead,
                           sources=sorted(session['sources']), weather=copy.deepcopy(session.get('weather')))
            same = self.data['signature'] == signature
            depth = status['setback_depth']
            prior = status['outcomes'][-1] if status['outcomes'] else {}
            successes = self.data.get('successes', 0) if same and comparable(prior, session) else 0
            if view['settings'].get('adaptive_setback_enabled'):
                if result == 'late':
                    depth, successes = max(.5, depth-.5), 0
                elif plan['learning_status']['cooling_rate'] is not None:
                    successes += 1
                    if successes >= 3:
                        depth, successes = min(max(.5, session['target']-view['settings']['setback_temperature']), depth+.5), 0
                        lead = max(lead, session['lead'])  # Change one experiment parameter at a time.
                        outcome['next_lead_minutes'] = lead
            outcome['next_depth'] = depth
            updated = dict(signature=signature, lead=lead, depth=depth, successes=successes,
                           outcomes=(status['outcomes']+[outcome])[-32:])
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO hc_learning VALUES (1, ?)', (json.dumps(updated, allow_nan=False),))
            self.data = updated
            return
        if session is None:
            window = view['next']
            if not plan['preheating'] or not window:
                return
            start = window['starts_at']-status['lead_minutes']*60
            # Late activation is useful for comfort, but cannot calibrate a full lead time.
            if now-start > max_gap or down['temperature'] >= window['target']:
                return
            session = dict(signature=signature, deadline=window['starts_at'], target=window['target'],
                           minimum=window['minimum'], lead=status['lead_minutes'],
                           heated=False, sources=set(), reached=None, last=now,
                           weather=copy.deepcopy((context or {}).get('weather')))
            self.session = session
        session['last'] = now
        session['sources'].update(s for s in ('beneden', 'cv') if s in plan['desired'])
        session['heated'] |= any(plan['sources'][s]['state'] == 'heat' for s in session['sources'])
        if down['temperature'] >= session['target']:
            if session['reached'] is None:
                session['reached'] = now
        else:
            session['reached'] = None
