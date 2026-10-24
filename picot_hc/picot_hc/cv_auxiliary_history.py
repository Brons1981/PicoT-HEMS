"""State-based auxiliary history, explicitly modeled rather than measured."""

import hashlib
import json
from datetime import UTC, datetime

from .core import observation, timestamp
from .cv_auxiliary import assumptions
from .cv_load_review import LoadReview


class AuxiliaryHistory:
    def __init__(self):
        self.identity = self.last = self.off_since = None
        self.was_active = None
        self.review = LoadReview()
        self.current = dict(status="unavailable")

    def sample(self, config, states, now):
        empty = dict(contract="modeled-load:v1", status="unavailable")
        self.current = empty
        parameters = assumptions(config)
        if parameters is None:
            self.__init__()
            return empty
        entities = [config.get("cv_status"), config.get("cv_dhw_active")]
        identity = hashlib.sha256(
            json.dumps([entities, parameters, "delayed-subset:v1"], sort_keys=True).encode()
        ).hexdigest()
        if identity != self.identity or self.last is None or not 0 <= now - self.last <= 60:
            self.off_since = self.was_active = None
            self.review = LoadReview()
        self.identity, self.last = identity, now
        active = []
        for entity in entities:
            point = observation(entity, states, now)
            try:
                age = now - timestamp(point["source_reported"] or point["source_updated"])
                if (
                    point["quality"] != "available"
                    or point.get("report_error")
                    or point["value"] not in ("on", "off")
                    or not 0 <= age <= 60
                ):
                    raise ValueError("unknown source")
            except (ValueError, TypeError):
                self.off_since = self.was_active = None
                self.review = LoadReview()
                return empty
            active.append(point["value"] == "on")
        if any(active):
            power = parameters["running_power_w"]
            self.off_since = None
            self.was_active = True
            phase = "active"
        else:
            if self.off_since is None:
                self.off_since = now
            elapsed = now - self.off_since
            if self.was_active is None and elapsed < parameters["postrun_seconds"] + 90:
                return empty  # Restart cannot establish that an earlier pump run has ended.
            if elapsed < parameters["postrun_seconds"]:
                power, phase = parameters["postrun_power_w"], "postrun"
            else:
                power, phase = 0, "idle"
            self.was_active = False
        value = dict(
            contract="modeled-load:v1",
            status="estimated",
            source_id=identity,
            generated_at=datetime.fromtimestamp(now, UTC).isoformat(),
            power_w=power,
            method="configured_auxiliary_state:v1",
            phase=phase,
        )
        value["reviewed_components"] = self.review.observe(
            value, heating=active[0], dhw=active[1], now=now
        )
        self.current = value
        return value
