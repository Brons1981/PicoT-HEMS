# PicoT HEMS Project Constitution

## Status
Accepted

## Purpose
This document defines the stable architectural principles that guide PicoT HEMS. These principles take precedence over informal chat history and temporary implementation ideas.

## Core principles

1. PicoT HEMS runtime contains no AI, language model, or self-learning decision logic.
2. Runtime behaviour is deterministic, rule-based, reproducible, and explainable.
3. The planner consumes logical capabilities only and never depends directly on Home Assistant entity identifiers or vendor-specific integrations.
4. Discovery identifies candidate sources. It is not a continuous runtime fallback mechanism.
5. Semantic validation must occur before capability selection.
6. A validated capability mapping remains persistent until objective evidence proves it invalid.
7. Temporary unavailability does not make a mapping invalid.
8. Rediscovery is performed per capability, never globally unless the affected capabilities are individually invalid.
9. PicoT never silently replaces a source when that replacement can influence behaviour. User confirmation is required where applicable.
10. Every planner decision must be traceable to the capability mapping version and source values used at that moment.
11. Configuration ownership must be explicit. PicoT may only write settings that are explicitly owned by PicoT.
12. Diagnostic data and layer statuses must be exportable when expected information is missing or inconsistent.
13. GitHub is the project source of truth. Accepted architecture documents and ADRs take precedence over remembered chat context.
14. Stored ideas and roadmap items are not accepted architecture until explicitly promoted to a decision.
15. Development follows the principle: architecture future-proof, implementation minimal.

## Change policy
A principle in this document may only be changed deliberately and must be accompanied by an Architecture Decision Record explaining the reason and consequences.
