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
                  source_id=None, measured_at=None, power_w=None,
                  source_entity_id=zone.get('power'), source_reported_at=None)

    def unavailable(reason, error):
        return dict(result, reason=reason, error=error)

    # This physical scope was explicitly confirmed by the installation owner.
    if (zone.get('power') != 'sensor.kwh_meter_airco_vermogen'
            or zone.get('energy') != 'sensor.kwh_meter_airco_energie_import'):
        return unavailable('source_scope_unconfirmed', 'De meetbron is niet bevestigd voor deze airco.')
    identity = '|'.join(str(zone.get(k, '')) for k in ('power', 'energy', 'device'))
    result['source_id'] = hashlib.sha256(identity.encode()).hexdigest()
    item = states.get(zone['power']) or {}
    if item.get('hc_report_error'):
        return unavailable('source_report_unavailable',
                           'Actuele bronrapportage van de aircovermogensmeter kon niet worden opgehaald.')
    raw = item.get('state')
    if raw in (None, 'unknown', 'unavailable'):
        return unavailable('source_unavailable', 'De aircovermogensmeter levert geen meting.')
    try:
        if isinstance(raw, bool):
            raise ValueError('boolean power')
        power = float(raw)
        if not math.isfinite(power) or not 0 <= power <= 20000:
            raise ValueError('invalid power')
    except (ValueError, TypeError, OverflowError):
        return unavailable('source_value_invalid', 'De aircovermogensmeter levert geen geldig vermogen.')
    if (item.get('attributes') or {}).get('unit_of_measurement') != 'W':
        return unavailable('source_unit_invalid', 'De aircovermogensmeter rapporteert niet in watt.')
    try:
        stamp = item.get('last_reported') or item.get('last_updated')
        when = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if when.utcoffset() is None:
            raise ValueError('missing timezone')
        result['source_reported_at'] = when.isoformat()
        age = now - when.timestamp()
        if age < 0:
            return unavailable('source_report_future', 'De bronrapportage ligt in de toekomst.')
        if age > 60:
            return unavailable('source_report_stale',
                               'De laatste bronrapportage van de aircovermogensmeter is ouder dan 60 seconden.')
        return dict(result, status='available', measured_at=when.isoformat(), power_w=power,
                    reason=None, error=None)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return unavailable('source_timestamp_invalid', 'De bronrapportage heeft geen geldige tijdstempel.')


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
