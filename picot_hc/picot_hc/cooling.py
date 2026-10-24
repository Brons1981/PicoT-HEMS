"""Conservative empirical cooling estimates, only for downstairs.

Twenty-minute intervals after fifteen minutes without reported heating.
No extrapolation to substantially different indoor/outdoor temperatures.
"""
import json

from .thermal_weather import comparable


class Cooling:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS hc_cooling (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            row = db.execute('SELECT payload FROM hc_cooling WHERE id=1').fetchone()
        self.samples = json.loads(row[0]) if row else []
        self.segment = None
        self.coasting = None
        self.blocked = None

    def estimate(self, context, now):
        if not context or not context['valid']:
            return dict(cooling_samples=0, cooling_rate=None)
        indoor, outdoor = context['indoor'], context['outdoor']
        samples = [s for s in self.samples if 0 <= now-s['end'] <= 7*86400
                   and s['identity'] == context['identity'] and comparable(s, context)
                   and abs(s['outdoor']-outdoor) <= 3 and abs(s['indoor']-indoor) <= 2]
        rate = None
        if len(samples) >= 3 and indoor-outdoor >= 3:
            rate = max(s['coefficient'] for s in samples)*(indoor-outdoor)*1.5+.1
        return dict(cooling_samples=len(samples), cooling_rate=rate)

    def observe(self, context, plan, view, now, max_gap):
        active = view['current']
        window = (view['revision'], active['ends_at']) if active else None
        phase = plan['learning_status']['phase']
        if self.coasting == window and window is not None and phase != 'coast':
            self.blocked = window  # Do not repeatedly retry after restoring comfort.
        self.coasting = window if phase == 'coast' else None
        if window != self.blocked:
            self.blocked = None
        allowed = context['valid'] and context['idle'] and plan['learning'] and plan['enabled']
        if not allowed:
            self.segment = None
            return
        segment = self.segment
        key = (context['identity'], view['revision'])
        if (segment is None or segment['key'] != key or not 0 < now-segment['last'] <= max_gap
                or not comparable(segment, context)
                or abs(context['outdoor']-segment['outdoor']) > 2
                or context['indoor'] > segment['previous']+.1):
            self.segment = dict(key=key, last=now, idle_since=now, start=None,
                                previous=context['indoor'], outdoor=context['outdoor'], weather=context.get('weather'))
            return
        segment['last'], segment['previous'] = now, context['indoor']
        if now-segment['idle_since'] < 15*60:
            return
        if segment['start'] is None:
            segment.update(start=now, indoor=context['indoor'], outdoor=context['outdoor'])
            return
        elapsed = now-segment['start']
        if elapsed < 20*60:
            return
        drop = segment['indoor']-context['indoor']
        delta = segment['indoor']-segment['outdoor']
        if .05 <= drop <= 2 and delta >= 3 and drop*3600/elapsed <= 3:
            sample = dict(end=now, indoor=segment['indoor'], outdoor=segment['outdoor'],
                          coefficient=drop*3600/elapsed/delta, identity=context['identity'], weather=segment.get('weather'))
            samples = ([s for s in self.samples if 0 <= now-s['end'] <= 7*86400]+[sample])[-64:]
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO hc_cooling VALUES (1, ?)', (json.dumps(samples, allow_nan=False),))
            self.samples = samples
        segment.update(start=now, indoor=context['indoor'], outdoor=context['outdoor'])
