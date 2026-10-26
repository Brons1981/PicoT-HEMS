"""Immutable consent evidence captured before candidate planning."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RouteChoiceInput:
    token: str
    assignment_id: str
    status: str
    expires_at: datetime
    main_signature: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        if (not isinstance(self.token, str) or not self.token
                or not isinstance(self.assignment_id, str) or not self.assignment_id
                or self.status not in {"pending", "selected"}
                or self.expires_at.utcoffset() is None
                or not isinstance(self.main_signature, tuple)):
            raise ValueError("invalid captured route choice")
        for item in self.main_signature:
            if (not isinstance(item, tuple) or len(item) != 3
                    or not all(isinstance(value, str) for value in item)):
                raise ValueError("route choice signature must be immutable triples")
            start, end, intent = item
            a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if a.utcoffset() is None or b.utcoffset() is None or a >= b or not intent:
                raise ValueError("invalid route choice interval")

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "RouteChoiceInput":
        try:
            return cls(record["token"], record["assignment_id"], record["status"],
                       datetime.fromisoformat(record["expires_at"]),
                       tuple(tuple(row) for row in
                             record["offer"]["alternative"]["main_signature"]))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError("stored route choice input is invalid") from exc

    def policy_record(self) -> dict[str, Any]:
        """Detached compatibility view for the existing pure admission policy."""
        return {"token": self.token, "assignment_id": self.assignment_id,
                "status": self.status, "expires_at": self.expires_at.isoformat(),
                "offer": {"alternative": {"main_signature": [list(row)
                                                            for row in self.main_signature]}}}
