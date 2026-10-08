import json
import unittest
from datetime import UTC, datetime, timedelta
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

from picot_energy_devices.regulation import (
    PowerReport,
    RegulationObserver,
    RegulationSnapshotStore,
    create_regulation_api,
)


class RegulationAPITests(unittest.TestCase):
    def result(self, now):
        return RegulationObserver().evaluate(
            PowerReport(-800, now), PowerReport(0, now), PowerReport(2000, now), now=now
        )

    def test_three_ready_observations_and_cache_expiry(self):
        now = datetime.now(UTC)
        store = RegulationSnapshotStore(control_enabled=True)
        for _ in range(2):
            store.update(self.result(now))
            self.assertIsNone(store.read(now=now))
        store.update(self.result(now))
        self.assertEqual(store.read(now=now)["total_act_power"], -800)
        self.assertIsNone(store.read(now=now + timedelta(seconds=4)))
        store.update(dict(self.result(now), status="blocked", candidate_w=None))
        self.assertIsNone(store.read(now=now))
        store.update(self.result(now))
        self.assertIsNone(store.read(now=now))

    def test_disabled_api_returns_raw_not_corrected(self):
        now = datetime.now(UTC)
        store = RegulationSnapshotStore(control_enabled=False)
        result = self.result(now)
        result.update(raw_grid_w=1200, candidate_w=0)
        store.update(result)
        self.assertEqual(store.read(now=now)["total_act_power"], 1200)
        self.assertFalse(store.read(now=now)["control_enabled"])

    def test_producer_gap_requires_three_fresh_checks_after_recovery(self):
        now = datetime.now(UTC)
        store = RegulationSnapshotStore(control_enabled=True)
        for _ in range(3):
            store.update(self.result(now))
        resumed = now + timedelta(seconds=10)
        for index in range(3):
            when = resumed + timedelta(seconds=index)
            store.update(self.result(when))
            self.assertEqual(store.read(now=when) is not None, index == 2)

    def test_http_compatible_json_and_503_without_measurements(self):
        store = RegulationSnapshotStore(control_enabled=True)
        server = create_regulation_api(store, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/rpc/EM.GetStatus?id=0"
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(url, timeout=2)
            self.assertEqual(error.exception.code, 503)
            now = datetime.now(UTC)
            for _ in range(3):
                store.update(self.result(now))
            with urlopen(url, timeout=2) as response:
                self.assertEqual(json.loads(response.read())["total_act_power"], -800)
            with self.assertRaises(HTTPError):
                urlopen(url.replace("/rpc/EM.GetStatus", "/api/write"), timeout=2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
