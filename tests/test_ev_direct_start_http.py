import io
import json

from test_ev_sessions import Rig

from picot_energy_devices.store import EnergyDeviceStore
from picot_energy_devices.web_ui import DASHBOARD_HTML, create_web_server


class Connection:
    """In-memory transport; the real HTTP handler parses requests and writes responses."""

    def __init__(self, payload):
        body = json.dumps(payload).encode()
        self.request = io.BytesIO(
            b"POST /api/ev HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        self.response = bytearray()

    def makefile(self, *_args):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


def test_dashboard_request_creates_durable_session_without_probe(tmp_path):
    rig = Rig(tmp_path / "ev")
    server = create_web_server(EnergyDeviceStore(tmp_path / "registry"),
                               host="127.0.0.1", port=0, ev_sessions=rig.manager)

    def post(payload):
        connection = Connection(payload)
        server.RequestHandlerClass(connection, ("127.0.0.1", 0), server)
        header, body = bytes(connection.response).split(b"\r\n\r\n", 1)
        return header, json.loads(body)

    try:
        header, _ = post({"action": "save_profile", "expected_power_w": 2300,
                          "expected_duration_seconds": 14400})
        assert b"200 OK" in header
        header, started = post({"action": "start_now"})
        assert b"200 OK" in header
        assert started["sessions"][0]["recognition_source"] == "user_start"
        assert started["resume_verified"] is False
        rig.tick(None, "off")
        assert rig.commands == [True]
        header, _ = post({"action": "start_now"})
        assert b"400 Bad Request" in header
        assert len(rig.manager.view()["sessions"]) == 1
        assert 'id="ev-now"' in DASHBOARD_HTML
        assert 'action:"start_now"' in DASHBOARD_HTML
        assert "eerst 30 seconden laden" not in DASHBOARD_HTML
    finally:
        server.server_close()


def test_direct_start_over_http_socket(tmp_path):
    from threading import Thread

    from test_energy_device_web_ui import _request

    rig = Rig(tmp_path / "ev")
    server = create_web_server(EnergyDeviceStore(tmp_path / "registry"),
                               host="127.0.0.1", port=0, ev_sessions=rig.manager)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        _request(base + "/api/ev", {"action": "save_profile", "expected_power_w": 2300,
                                    "expected_duration_seconds": 14400})
        _request(base + "/api/ev", {"action": "start_now"})
        rig.tick(None, "off")
        assert rig.commands == [True]
        view = _request(base + "/api/view")
        assert view["ev"]["sessions"][0]["command"] == "turn_on"
        assert view["ev"]["sessions"][0]["remaining_energy_wh"] == 9200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
