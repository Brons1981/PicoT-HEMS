"""Acknowledge a freshly checked advisory choice; never authorize execution."""

import copy
import json

from .energy_portfolio import REQUEST_ENTITY, RESPONSE_ENTITY, read_assessment
from .energy_proposals import stamp

ENTITY = "sensor.picot_hc_energy_selection"


class Selection:
    def __init__(self, store, publisher):
        self.store, self.publisher = store, publisher
        self.current = None
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS hc_energy_selection "
                "(id TEXT PRIMARY KEY, time REAL, payload TEXT NOT NULL)"
            )

    def withdraw(self, reason):
        self.current = None
        self.publisher.submit(dict(state="withdrawn", attributes=dict(reason=reason)))

    def tick(self, states, proposals, now, connected):
        request, local = proposals.pending, proposals.local
        feedback = read_assessment(states, now, connected)
        if (
            not request
            or not local
            or now >= local["expires"]
            or states.get(REQUEST_ENTITY, {}).get("attributes") != request
            or feedback["status"] != "selected"
        ):
            self.withdraw("Geen actuele, lokaal geldige HEMS-keuze.")
            return
        chosen = feedback["selected_plan_id"]
        recipe = next((p for p in local.get("candidates", []) if p["plan_id"] == chosen), None)
        if local["action"] == "maintain_temperature" and chosen == "maintain":
            recipe = dict(
                target=local["target"], starts_at=local["starts_at"], ends_at=local["ends_at"]
            )
        if recipe is None:
            self.withdraw("HEMS-keuze heeft geen bijbehorend lokaal plan.")
            return
        answer = states[RESPONSE_ENTITY]["attributes"]
        expiry = min(feedback["valid_until"], local["expires"])
        if (
            self.current
            and self.current["request_id"] == request["request_id"]
            and self.current["selected_plan_id"] == chosen
            and self.current["valid_until"] == expiry
            and self.current["message"]["request_fingerprint"] == answer["request_fingerprint"]
            and self.current["recipe"] == recipe
        ):
            self.publisher.submit(dict(state="confirmed", attributes=self.current["message"]))
            return
        message = dict(
            contract="hc-energy-selection:v1",
            request_id=request["request_id"],
            revision=request["revision"],
            basis_snapshot_id=request["basis_snapshot_id"],
            replacement_basis_id=request.get("replacement_basis_id"),
            request_fingerprint=answer["request_fingerprint"],
            selected_plan_id=chosen,
            generated_at=stamp(now),
            valid_until=stamp(expiry),
            execution_authorized=False,
        )
        current = dict(
            status="confirmed",
            source=recipe.get("source", local.get("source", "beneden")),
            request_id=request["request_id"],
            selected_plan_id=chosen,
            target=recipe["target"],
            heat_starts_at=recipe.get("heat_starts_at"),
            valid_until=expiry,
            message=message,
            recipe=copy.deepcopy(recipe),
            execution_authorized=False,
        )
        with self.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO hc_energy_selection VALUES (?, ?, ?)",
                (request["request_id"], now, json.dumps(current, allow_nan=False)),
            )
            db.execute(
                "DELETE FROM hc_energy_selection WHERE id NOT IN "
                "(SELECT id FROM hc_energy_selection ORDER BY time DESC LIMIT 96)"
            )
        self.current = current
        self.publisher.submit(dict(state="confirmed", attributes=message))

    def view(self, now):
        if not self.current or now >= self.current["valid_until"]:
            return dict(status="waiting", execution_authorized=False)
        return {
            k: copy.deepcopy(v) for k, v in self.current.items() if k not in ("message", "recipe")
        }
