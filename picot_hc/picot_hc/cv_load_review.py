"""Delay replaceable auxiliary attribution until late DHW reports are covered."""

from datetime import UTC, datetime


class LoadReview:
    def __init__(self):
        self.pending, self.completed = [], []
        self.last = self.source = None
        self.tail_is_dhw = True

    def observe(self, point, *, heating, dhw, now):
        if (
            point.get("status") != "estimated"
            or self.last is None
            or not 0 < now - self.last <= 60
            or self.source != point.get("source_id")
        ):
            self.__init__()
        self.last, self.source = now, point.get("source_id")
        if point.get("status") != "estimated":
            return []
        if dhw:
            self.tail_is_dhw = True
            for old in self.pending:
                old["replaceable_power_w"] = 0
        elif heating:
            self.tail_is_dhw = False
        replaceable = point["power_w"] if not dhw and not self.tail_is_dhw else 0
        self.pending.append(
            dict(time=now, power_w=point["power_w"], replaceable_power_w=replaceable)
        )
        ready = [p for p in self.pending if now - p["time"] >= 90]
        self.pending = [p for p in self.pending if now - p["time"] < 90]
        self.completed = [p for p in self.completed + ready if now - p["time"] <= 1200][-80:]
        return [
            dict(
                sampled_at=datetime.fromtimestamp(p["time"], UTC).isoformat(),
                power_w=p["power_w"],
                replaceable_power_w=p["replaceable_power_w"],
            )
            for p in self.completed
        ]
