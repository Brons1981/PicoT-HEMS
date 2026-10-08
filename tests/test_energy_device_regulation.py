"""Standalone observer contract checks, runnable without pytest."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from picot_energy_devices.home_assistant import HomeAssistantClient
from picot_energy_devices.regulation import PowerReport, RegulationObserver, regulation_candidate
from picot_energy_devices.runtime import regulation_poll_once

NOW = datetime(2026, 10, 8, 16, tzinfo=UTC)


def report(watts: float, age: float = 0) -> PowerReport:
    return PowerReport(watts, NOW - timedelta(seconds=age))


class RegulationTests(unittest.TestCase):
    def test_physical_examples(self) -> None:
        for raw, battery, expected in [
            (-800, 0, -800),
            (0, 800, 0),
            (1200, 0, 0),
            (2200, 0, 200),
            (2000, -200, 0),
        ]:
            result = regulation_candidate(report(raw), report(battery), report(2000), now=NOW)
            self.assertEqual(result["candidate_w"], expected)
            self.assertTrue(result["observer_only"])
            self.assertFalse(result["actuation_authority"])

    def test_no_ev_preserves_raw_exactly(self) -> None:
        for watts in [-803, -5, 0, 19, 2200]:
            self.assertEqual(
                regulation_candidate(report(watts), report(537), report(0), now=NOW)["candidate_w"],
                watts,
            )

    def test_old_each_source_and_future_and_skew_block(self) -> None:
        for index in range(3):
            values = [report(0), report(0), report(2000)]
            values[index] = report(values[index].watts, 4)
            result = regulation_candidate(*values, now=NOW)
            self.assertIsNone(result["candidate_w"])
            self.assertEqual(result["reason"], "stale_source")
        self.assertEqual(
            regulation_candidate(report(0, -1), report(0), report(2000), now=NOW)["reason"],
            "future_report",
        )
        self.assertEqual(
            regulation_candidate(report(0, 3), report(0), report(2000), now=NOW)["reason"],
            "source_time_skew",
        )

    def test_quantization_reduces_noise_without_adding_support(self) -> None:
        values = []
        for delta in [-10, -5, 0, 5, 10]:
            result = regulation_candidate(report(2000 + delta), report(-200), report(2000), now=NOW)
            permitted = result["permitted_net_demand_w"]
            self.assertGreaterEqual(permitted, 0)
            self.assertLessEqual(permitted, 200 + delta)
            values.append(result["candidate_w"])
        self.assertLess(len(set(values)), 5)
        # A large step is reflected immediately, with no long averaging.
        self.assertEqual(
            regulation_candidate(report(-800), report(0), report(2000), now=NOW)["candidate_w"],
            -800,
        )

    def test_observer_holds_small_increase_but_passes_reduction_and_large_step(self) -> None:
        observer = RegulationObserver()

        def evaluate(raw):
            return observer.evaluate(report(raw), report(0), report(2000), now=NOW)

        self.assertEqual(evaluate(2185)["candidate_w"], 180)
        self.assertEqual(evaluate(2210)["candidate_w"], 180)
        self.assertEqual(evaluate(2100)["candidate_w"], 100)
        self.assertEqual(evaluate(-800)["candidate_w"], -800)
        self.assertIsNone(
            observer.evaluate(report(0, 4), report(0), report(2000), now=NOW)["candidate_w"]
        )
        self.assertEqual(evaluate(2210)["candidate_w"], 200)

    def test_constant_value_with_new_report_time_remains_usable(self) -> None:
        payload = {
            "state": "200",
            "attributes": {"unit_of_measurement": "W"},
            "last_changed": (NOW - timedelta(days=1)).isoformat(),
            "last_reported": NOW.isoformat(),
        }
        power = PowerReport.from_state(payload)
        self.assertEqual(
            regulation_candidate(power, report(0), report(0), now=NOW)["status"], "ready"
        )

    def test_report_time_required_even_if_fetch_and_change_time_are_present(self) -> None:
        state = {
            "state": "200",
            "attributes": {"unit_of_measurement": "W"},
            "last_changed": NOW.isoformat(),
            "last_updated": NOW.isoformat(),
        }
        with self.assertRaises(ValueError):
            PowerReport.from_state(state)
        state["last_reported"] = NOW.isoformat()
        self.assertEqual(PowerReport.from_state(state).watts, 200)
        state["last_reported"] = NOW.replace(tzinfo=None).isoformat()
        with self.assertRaises(ValueError):
            PowerReport.from_state(state)

    def test_nonfinite_and_negative_ev_rejected(self) -> None:
        with self.assertRaises(ValueError):
            regulation_candidate(report(float("nan")), report(0), report(0), now=NOW)
        self.assertEqual(
            regulation_candidate(report(0), report(0), report(-1), now=NOW)["reason"],
            "negative_ev_power",
        )

    def test_publication_cannot_overwrite_shared_p1(self) -> None:
        client = HomeAssistantClient("test-token")
        with patch.object(client, "_request", return_value={}) as request:
            client.publish_regulation_shadow({"candidate_w": 0, "observer_only": True})
        self.assertEqual(
            request.call_args.args[0].full_url,
            "http://supervisor/core/api/states/sensor.picot_ev_regulation_shadow",
        )

    def test_poll_reads_all_sources_and_publishes_shadow(self) -> None:
        class Client:
            published = None

            def state(self, entity):
                return {
                    "state": {"sensor.raw": "-800", "sensor.battery": "0", "sensor.ev": "2000"}[
                        entity
                    ],
                    "attributes": {"unit_of_measurement": "W"},
                    "last_reported": NOW.isoformat(),
                }

            def publish_regulation_shadow(self, value):
                self.published = value

        client = Client()
        with patch("picot_energy_devices.runtime.datetime") as clock:
            clock.now.return_value = NOW
            regulation_poll_once(
                client=client,
                raw_entity="sensor.raw",
                battery_entity="sensor.battery",
                ev_entity="sensor.ev",
            )
        self.assertEqual(client.published["status"], "ready")
        self.assertEqual(client.published["candidate_w"], -800)
        self.assertFalse(client.published["actuation_authority"])

    def test_poll_marks_missing_report_time_unavailable(self) -> None:
        class Client:
            published = None

            def state(self, entity):
                return {"state": "0", "attributes": {"unit_of_measurement": "W"}}

            def publish_regulation_shadow(self, value):
                self.published = value

        client = Client()
        regulation_poll_once(
            client=client,
            raw_entity="sensor.raw",
            battery_entity="sensor.battery",
            ev_entity="sensor.ev",
        )
        self.assertEqual(client.published["status"], "blocked")
        self.assertIsNone(client.published["candidate_w"])


if __name__ == "__main__":
    unittest.main()
