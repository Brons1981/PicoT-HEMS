# EV charging advice with household grid fallback

HEMS rejected all charging advice when the retained route could not supply continuous battery support for the house (`household_bridge_unreachable`). The 10 November diagnosis had only this reason: battery support reached its normal floor while the house could use the grid.

Allow household grid fallback only for the EV advice and fresh acceptance checks. Ordinary bridge assessment remains strict by default. The existing full-horizon projection and settlement price the grid import; EV demand remains battery-excluded. Bound main/supplemental charge goals, export commitments, capability and SOC limits, common terminal reserve, freshness, ownership and durable acceptance remain enforced.

ED displays the execute instruction only for an executable advice. The charging-request/advice contract and existing confirmed slots remain unchanged. HEMS 2.0.0-dev.339 and ED 0.4.0-dev.15; HC stays dev.34.

Validation: a regression reproduced blocked advice before the fix; 77 focused tests then passed across advice, acceptance, grid/PV comparisons, bridge behavior, ED exchange, dashboard and end-to-end execution. Ruff passed. Offline replay of the real diagnosis with a synthetic 2.3 kWh / 2.3 kW request returned 11 November 03:15-04:15 Europe/Amsterdam after 108 candidate comparisons (about 105 seconds locally). This is test evidence, not a scheduled live session. Full CI is required before release.
