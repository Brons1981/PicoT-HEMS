# DOC-010 — Project Rules

Copyright © 2026 Alex Brons. All rights reserved.

**Status:** Audit Approved — RC3  
**Document type:** Normative project rules  
**Related ADRs:** ADR-001, ADR-002

## Transparency and Explainability

PicoT HEMS shall never make a silent decision.

Every significant decision must produce a Decision Record and must be explainable, traceable and verifiable. The system shall record what was decided, why the decision was made, which inputs and policies were used, which alternatives were rejected, the expected result, the confidence level, the execution result and any available verification evidence.

A feature or module is not considered complete when its decisions cannot be understood without inspecting source code or YAML.
