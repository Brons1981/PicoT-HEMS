"""Command-line commissioning for the first Home Assistant capability."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

from picot.adapters.home_assistant_dry_run import build_zendure_manual_power_dry_run

DEFAULT_BASE_URL = "http://192.168.6.26:8123"
DEFAULT_POWER_W = 1200.0


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic commissioning command parser."""
    parser = argparse.ArgumentParser(
        prog="picot-commission",
        description="Preview PicoT's first Home Assistant service call without sending it.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PICOT_HA_BASE_URL", DEFAULT_BASE_URL),
        help="Home Assistant base URL.",
    )
    parser.add_argument(
        "--power-w",
        type=float,
        default=DEFAULT_POWER_W,
        help="Requested manual charge power in watts.",
    )
    return parser


def main() -> int:
    """Print the exact dry-run call; never perform network traffic."""
    args = build_parser().parse_args()
    preview = build_zendure_manual_power_dry_run(
        base_url=args.base_url,
        requested_power_w=args.power_w,
        created_at=datetime.now(UTC),
    )
    print("PicoT Home Assistant commissioning")
    print("mode: DRY_RUN")
    print(f"endpoint: {preview.endpoint}")
    print(f"payload: {preview.payload_json}")
    print(f"status: {preview.dispatch_result.status.value}")
    print(f"command_id: {preview.service_call.command_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
