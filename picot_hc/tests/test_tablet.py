import base64
import copy
import io
import json
import tempfile
import unittest
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from picot_hc.__main__ import Runtime, handler
from picot_hc.core import Store
from picot_hc.tablet import ENERGY_ENTITIES, authorized, energy_view, tablet_view

NOW = 1793448000.0
PASSWORD = "local-test-password"


class Tablet(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (Path(__file__).resolve().parents[1] / "options.example.json").read_text()
        )
        self.config["tablet_password"] = PASSWORD
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Runtime(
            self.config, Store(Path(self.tmp.name) / "hc.db"), "http://fake/api", "secret-ha-token"
        )
        self.runtime.control.connected = True
        self.runtime.control.received = NOW
        self.runtime.heating.data["settings"]["enabled"] = True
        self.runtime.heating.armed = True
        self.runtime.schedule.data["settings"]["thermostat_temperature"] = 20
        zone = next(z for z in self.runtime.config["zones"] if z["id"] == "beneden")
        self.runtime.control.states = {
            zone["temperature"]: self.point(19.4, "\u00b0C"),
            self.runtime.config["outdoor"]: self.point(8.4, "\u00b0C"),
        }
        self.addCleanup(patch.stopall)
        patch("time.time", return_value=NOW).start()

    @staticmethod
    def point(value, unit="W", when=NOW):
        return dict(
            state=str(value),
            attributes={"unit_of_measurement": unit},
            last_reported=datetime.fromtimestamp(when, UTC).isoformat(),
        )

    def energy(self, grid, pv, charge, discharge):
        return {
            ENERGY_ENTITIES[k]: self.point(v, "%" if k == "soc" else "W")
            for k, v in dict(grid=grid, pv=pv, charge=charge, discharge=discharge, soc=64).items()
        }

    def request(self, method, path, payload=None, auth=True, csrf=True, local=True):
        cls = handler(self.runtime, False, tablet_only=local)
        endpoint = cls.__new__(cls)
        endpoint.path = path
        endpoint.client_address = ("127.0.0.1", 1)
        endpoint.headers = Message()
        if auth:
            endpoint.headers["Authorization"] = (
                "Basic " + base64.b64encode(("tablet:" + PASSWORD).encode()).decode()
            )
        if csrf:
            endpoint.headers["X-HC-CSRF"] = self.runtime.csrf_token
        body = json.dumps(payload).encode()
        endpoint.headers["Content-Type"] = "application/json"
        endpoint.headers["Content-Length"] = str(len(body))
        endpoint.rfile, endpoint.wfile = io.BytesIO(body), io.BytesIO()
        statuses = []
        endpoint.send_response = statuses.append
        endpoint.send_error = lambda status, *args: statuses.append(status)
        endpoint.send_header = lambda *args: None
        endpoint.end_headers = lambda: None
        getattr(endpoint, "do_" + method)()
        return statuses[0], endpoint.wfile.getvalue()

    def test_energy_colours_and_balance(self):
        for inputs, expected in [
            ((-1000, 3000, 1200, 0), ("pv", "pv", -1200, 800)),
            ((2000, 0, 1200, 0), (None, "grid", -1200, 800)),
            ((1500, 500, 1200, 0), (None, "mixed", -1200, 800)),
            ((-400, 0, 0, 1200), ("battery", None, 1200, 800)),
            ((-400, 500, 0, 700), ("mixed", None, 700, 800)),
        ]:
            view = energy_view(self.config, self.energy(*inputs), NOW)
            self.assertEqual(
                tuple(view[k] for k in ("grid_source", "battery_source", "battery_w", "home_w")),
                expected,
            )

    def test_bad_or_old_energy_is_not_zero_or_coloured(self):
        states = self.energy(1000, 500, 700, 0)
        for value in ("unavailable", "NaN", "inf"):
            states[ENERGY_ENTITIES["pv"]]["state"] = value
            view = energy_view(self.config, states, NOW)
            self.assertIsNone(view["pv_w"])
            self.assertIsNone(view["battery_source"])
            self.assertIsNone(view["home_w"])
        states = self.energy(1000, 500, 700, 0)
        states[ENERGY_ENTITIES["grid"]] = self.point(1000, when=NOW - 31)
        self.assertIsNone(energy_view(self.config, states, NOW)["grid_w"])
        states = self.energy(1000, 500, 700, 200)
        self.assertIsNone(energy_view(self.config, states, NOW)["battery_w"])

    def test_separate_password_and_restricted_routes(self):
        for header in ("", "Basic invalid!", "Bearer secret-ha-token"):
            self.assertFalse(authorized(header, PASSWORD))
        self.assertEqual(self.request("GET", "/api/tablet", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/api/snapshot")[0], 404)
        self.assertEqual(self.request("POST", "/api/heating", {})[0], 404)
        self.assertEqual(self.request("POST", "/api/tablet/temperature", {}, csrf=False)[0], 403)

    def test_snapshot_and_target_use_real_schedule_without_services(self):
        code, body = self.request("GET", "/api/tablet")
        self.assertEqual(code, 200)
        view = json.loads(body)
        self.assertEqual(view["inside"], 19.4)
        self.assertTrue(view["controllable"])
        self.assertNotIn(b"secret-ha-token", body)
        with patch.object(
            self.runtime.control, "submit", side_effect=AssertionError("Direct dispatch")
        ):
            code, body = self.request(
                "POST", "/api/tablet/temperature", dict(revision=view["revision"], temperature=20.5)
            )
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["target"], 20.5)
        self.assertTrue(self.runtime.poll_now.is_set())
        self.assertEqual(
            self.request(
                "POST", "/api/tablet/temperature", dict(revision=view["revision"], temperature=21)
            )[0],
            400,
        )

    def test_stale_climate_disables_writes_and_hides_values(self):
        self.runtime.control.received = NOW - 10000
        view = tablet_view(self.runtime)
        self.assertTrue(view["stale"])
        self.assertFalse(view["controllable"])
        self.assertIsNone(view["inside"])
        before = copy.deepcopy(self.runtime.schedule.data)
        self.assertEqual(
            self.request(
                "POST", "/api/tablet/temperature", dict(revision=before["revision"], temperature=21)
            )[0],
            400,
        )
        self.assertEqual(self.runtime.schedule.data, before)

    def test_http_access_and_static_assets(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.runtime, False, tablet_only=True)
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:" + str(server.server_port)
            with self.assertRaises(HTTPError) as missing:
                urlopen(url, timeout=3)
            self.assertEqual(missing.exception.code, 401)
            headers = {
                "Authorization": "Basic "
                + base64.b64encode(("tablet:" + PASSWORD).encode()).decode()
            }
            for route, marker in (
                ("/", b"tablet.js"),
                ("/tablet.css", b".screen"),
                ("/tablet.js", b"XMLHttpRequest"),
                ("/api/tablet", b"csrf_token"),
            ):
                with urlopen(Request(url + route, headers=headers), timeout=3) as response:
                    self.assertIn(marker, response.read())
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_disabled_heating_is_not_silently_activated(self):
        self.runtime.heating.data["settings"]["enabled"] = False
        self.assertFalse(tablet_view(self.runtime)["controllable"])
        self.assertEqual(self.request("POST", "/api/tablet/resume", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
