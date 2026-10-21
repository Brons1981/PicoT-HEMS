"""One route's consent is durable, revocable and never authority for another day."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from picot.v2.daily_charge_assignment import (
    DailyChargeAssignment,
    DailyChargeRevisionReason,
    DailyChargeSegment,
)
from picot.v2.daily_recalculation import DailyMainRecalculationTrigger
from picot.v2.plan_commitment_store import ActivePlanCommitmentStore


class RouteChoiceStoreTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "plans.json"
        self.store = ActivePlanCommitmentStore(self.path)
        self.at = datetime(2026, 10, 20, 14, tzinfo=UTC)
        self.owner = DailyChargeAssignment(
            "battery",
            (self.at + timedelta(days=1)).date(),
            "UTC",
            self.at,
        ).bind_main_route(
            plan_id="original",
            segments=(
                DailyChargeSegment(
                    "night", self.at + timedelta(hours=10), self.at + timedelta(hours=12)
                ),
            ),
            at=self.at,
            reason=DailyChargeRevisionReason.INITIAL,
            evidence_id="original-evaluation",
        )
        self.store.save_daily_assignment(self.owner)
        self.offer = self.store.offer_route_choice(
            assignment_id=self.owner.assignment_id,
            plan_id="original",
            revision=1,
            offer={"alternative": {"fingerprint": "daytime", "pv_storage_wh": 2000}},
            created_at=self.at,
            expires_at=self.at + timedelta(hours=8),
        )

    def request(self):
        return self.store.request_route_choice(
            token=self.offer["token"], action="pv", requested_at=self.at + timedelta(minutes=1)
        )

    def accept(self):
        self.request()
        request = self.store.load_daily_recalculation_request()
        at = self.at + timedelta(minutes=2)
        trigger = DailyMainRecalculationTrigger(
            self.owner.assignment_id,
            self.owner.route_plan_id,
            self.owner.revision,
            "original",
            "fresh",
            at,
            8160,
            request,
        )
        bound = self.owner.bind_main_route(
            plan_id="selected",
            segments=(
                DailyChargeSegment(
                    "pv", self.at + timedelta(hours=22), self.at + timedelta(hours=24)
                ),
            ),
            at=at,
            reason=trigger.revision_reason,
            evidence_id="user-evaluation",
        )
        # Exercise the same payload transition used by the atomic plan binder.
        payload = self.store._load_payload()
        self.store._accept_route_choice(
            payload, trigger, bound, SimpleNamespace(plan_id="selected", created_at=at)
        )
        self.store._finish_daily_recalculation(
            payload,
            request_id=request.request_id,
            assignment_id=bound.assignment_id,
            status="replanned",
            reason="explicit_user_route_choice",
            plan_id="selected",
            snapshot_id="fresh",
        )
        self.store._write(payload)
        self.store.save_daily_assignment(bound)
        self.owner = bound
        return bound

    def test_request_is_exactly_one_owner_and_survives_restart(self):
        tomorrow = DailyChargeAssignment(
            "battery", self.owner.delivery_date + timedelta(days=1), "UTC", self.at
        )
        self.store.save_daily_assignment(tomorrow)
        result = self.request()
        self.assertEqual(result["status"], "pending")
        restored = ActivePlanCommitmentStore(self.path)
        request = restored.load_daily_recalculation_request()
        self.assertEqual(request.assignment_ids, (self.owner.assignment_id,))
        self.assertEqual(request.route_choice_token, self.offer["token"])
        before = self.path.read_bytes()
        self.assertEqual(self.request(), result)
        self.assertEqual(self.path.read_bytes(), before)

    def test_accept_release_and_duplicate_response(self):
        self.accept()
        status = self.store.active_route_choice(
            self.owner.assignment_id, self.at + timedelta(hours=1)
        )
        self.assertEqual(status["accepted_plan_id"], "selected")
        released = self.store.release_route_choice(
            assignment_id=self.owner.assignment_id,
            requested_at=self.at + timedelta(hours=1),
            request_id="release-once",
        )
        self.assertEqual(released["status"], "released")
        self.assertIsNone(self.store.active_route_choice(self.owner.assignment_id, self.at))
        request = self.store.load_daily_recalculation_request()
        self.assertEqual(request.assignment_ids, (self.owner.assignment_id,))
        self.assertIsNone(request.route_choice_token)
        self.assertEqual(self.request()["status"], "released")

    def test_lock_survives_repair_but_not_completion_or_next_day(self):
        self.accept()
        repaired = self.owner.bind_main_route(
            plan_id="repair",
            segments=self.owner.main_segments,
            at=self.at + timedelta(hours=1),
            reason=DailyChargeRevisionReason.RESERVE,
            evidence_id="actual-reserve-shortfall",
        )
        self.store.save_daily_assignment(repaired)
        self.assertIsNotNone(
            self.store.active_route_choice(repaired.assignment_id, self.at + timedelta(hours=2))
        )
        status = self.store.route_choice_status(self.at + timedelta(hours=2))["choices"][0]
        self.assertEqual(status["current_revision"], 3)
        self.assertEqual(status["current_revision_reason"], "projected_reserve_shortfall")
        completed = replace(
            repaired,
            completed_at=repaired.main_segments[0].starts_at,
            completion_evidence_id="measured-full",
            completion_segment_id=repaired.main_segments[0].segment_id,
        )
        self.store.save_daily_assignment(completed)
        self.assertIsNone(
            self.store.active_route_choice(repaired.assignment_id, completed.completed_at)
        )
        self.assertIsNone(self.store.active_route_choice("different-assignment", self.at))
        self.assertEqual(
            self.store.route_choice_status(repaired.ends_at)["choices"][0]["status"], "expired"
        )

    def test_rejection_retains_original_and_consumes_request(self):
        self.request()
        result = self.store.reject_route_choice(
            token=self.offer["token"], reason="alternative_no_longer_feasible", at=self.at
        )
        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(self.store.load_daily_recalculation_request())
        self.assertEqual(self.store.load_daily_assignments(), (self.owner,))
        self.assertIsNone(self.store.active_route_choice(self.owner.assignment_id, self.at))

    def test_stale_expired_unknown_actions_and_pending_conflicts(self):
        for token, action, at in [
            ("bad", "pv", self.at),
            (self.offer["token"], "bad", self.at),
            (self.offer["token"], "pv", self.at + timedelta(hours=9)),
        ]:
            with self.assertRaises(ValueError):
                self.store.request_route_choice(token=token, action=action, requested_at=at)
        changed = self.owner.bind_main_route(
            plan_id="changed",
            segments=self.owner.main_segments,
            at=self.at,
            reason=DailyChargeRevisionReason.LOAD,
            evidence_id="new-load",
        )
        self.store.save_daily_assignment(changed)
        with self.assertRaises(ValueError):
            self.request()

    def test_reoffer_never_overwrites_pending_or_selected(self):
        self.request()
        repeated = self.store.offer_route_choice(
            assignment_id=self.owner.assignment_id,
            plan_id="original",
            revision=1,
            offer={"alternative": {"fingerprint": "another"}},
            created_at=self.at,
            expires_at=self.at + timedelta(hours=7),
        )
        self.assertEqual(repeated["token"], self.offer["token"])
        self.assertEqual(repeated["status"], "pending")

    def test_keep_automatic_does_not_queue_planner_change(self):
        result = self.store.request_route_choice(
            token=self.offer["token"], action="automatic", requested_at=self.at
        )
        self.assertEqual(result["status"], "declined")
        self.assertIsNone(self.store.load_daily_recalculation_request())
        self.assertIsNone(self.store.active_route_choice(self.owner.assignment_id, self.at))

    def test_notice_is_deduplicated_without_changing_preference(self):
        self.accept()
        at = self.at + timedelta(hours=1)
        notice = self.store.record_route_choice_notice(
            assignment_id=self.owner.assignment_id,
            key="financial:proposal",
            message="Another route",
            at=at,
        )
        self.assertEqual(notice["status"], "selected")
        before = self.path.read_bytes()
        self.store.record_route_choice_notice(
            assignment_id=self.owner.assignment_id,
            key="financial:proposal",
            message="Another route",
            at=at + timedelta(seconds=1),
        )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(
            self.store.active_route_choice(self.owner.assignment_id, at)["accepted_plan_id"],
            "selected",
        )

    def test_informational_offer_cannot_be_selected(self):
        payload = self.store._load_payload()
        payload["route_choices"][self.offer["token"]]["offer"]["alternative"] = None
        self.store._write(payload)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "no selectable"):
            self.request()
        self.assertEqual(before, self.path.read_bytes())
        result = self.store.request_route_choice(
            token=self.offer["token"], action="automatic", requested_at=self.at
        )
        self.assertEqual(result["status"], "declined")
