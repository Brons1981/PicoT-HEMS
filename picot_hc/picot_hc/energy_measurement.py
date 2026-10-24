"""Publish the confirmed downstairs meter; never infer missing power as zero."""
import hashlib
import math
from datetime import datetime, timezone
from threading import Lock, Thread

from .control import ha_request

ENTITY = 'sensor.picot_hc_load_measurement'


def measurement(config, states, now):
    zone = next((z for z in config['zones'] if z['id'] == 'beneden'), {})
    result = dict(contract='controlled-load-measurement:v1', status='unavailable',
                  generated_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  source_id=None, measured_at=None, power_w=None)
    # This physical scope was explicitly confirmed by the installation owner.
    # Another meter requires a new scope confirmation; a label is not evidence.
    if (zone.get('power') != 'sensor.kwh_meter_airco_vermogen'
            or zone.get('energy') != 'sensor.kwh_meter_airco_energie_import'):
        return result
    identity = '|'.join(str(zone.get(k, '')) for k in ('power', 'energy', 'device'))
    result['source_id'] = hashlib.sha256(identity.encode()).hexdigest()
    item = states.get(zone['power']) or {}
    try:
        raw = item.get('state')
        if isinstance(raw, bool):
            return result
        power = float(raw)
        stamp = item.get('last_reported') or item.get('last_updated')
        when = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if (when.utcoffset() is None or not 0 <= now-when.timestamp() <= 60
                or not math.isfinite(power) or not 0 <= power <= 20000
                or (item.get('attributes') or {}).get('unit_of_measurement') != 'W'):
            return result
        return dict(result, status='available', measured_at=when.isoformat(), power_w=power)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return result


class MeasurementPublisher:
    def __init__(self, url, token):
        self.url, self.token = url, token
        self.lock = Lock()

    def submit(self, value):
        if not self.lock.acquire(blocking=False):
            return

        def work():
            try:
                ha_request(self.url, self.token, '/states/' + ENTITY,
                           dict(state=value['status'], attributes=value))
            except Exception:
                pass  # Meter TTL makes failed publication unknown to HEMS.
            finally:
                self.lock.release()

        try:
            Thread(target=work, name='hc-energy-measurement', daemon=True).start()
        except Exception:
            self.lock.release()
