# PicoT HEMS

**Planning, Intelligence, Coordination, Orchestration & Transparency**

> [!WARNING]
> **ALPHA / DEVELOPMENT SOFTWARE — NOT PRODUCTION READY**
>
> PicoT HEMS is under active development and validation. Interfaces, entities, configuration, planning behaviour and internal architecture may change without backwards compatibility. This repository is public to support the current Home Assistant development and installation workflow; public visibility does **not** mean the project is released as open source or approved for general production use.

PicoT HEMS is a modular, explainable Home Energy Management System for Home Assistant.

## Current status

PicoT HEMS is currently intended for development, technical validation and controlled testing. It must not be relied on as a safety, alarm or protection system. Behaviour depends on Home Assistant, integrations, communications and connected hardware, and no guarantee is made that commands can always be executed.

Use outside the project owner's controlled test environment is unsupported at this stage.

## Intellectual property and repository use

Unless explicitly stated otherwise, the source code, architecture, documentation, designs, naming and project materials in this repository are proprietary and all rights are reserved by the copyright holder.

No open-source licence is granted by the public availability of this repository. You may view the repository through GitHub, but copying, modifying, redistributing, republishing, sublicensing or commercially exploiting the project or substantial parts of it is not permitted without prior written permission from the copyright holder, except where applicable law or GitHub's platform terms require otherwise.

The repository being public is therefore **not** permission to create derivative products, redistribute PicoT HEMS, or present its code or documentation as your own work.

See [`LICENSE`](LICENSE) for the applicable rights notice.

## Current phase

Late Phase 3 — Core architecture implemented; authoritative observation ingestion and closed-loop Home Assistant integration remain the primary validation focus.

## Active work

- authoritative direct-source observation design and validation;
- atomic Home Assistant planning-input snapshot wiring;
- integrated observe → plan → execute → observe/replan flow;
- controlled dry-run/live Home Assistant execution validation;
- architecture consistency, diagnostics and traceability review.

See [`docs/architecture/CLOSED_LOOP_READINESS_AUDIT_2026-08-12.md`](docs/architecture/CLOSED_LOOP_READINESS_AUDIT_2026-08-12.md) for the current readiness assessment.

## Core principles

- Robust and verifiable before clever or extensive
- Modular architecture
- Hardware and vendor independence
- Transparency and explainability
- Reliability and graceful degradation
- Minimal unnecessary battery relay switching

## Local Discovery setup

The steps below document the project owner's development setup. They are not a general public installation or support commitment.

1. Clone this repository.
2. Copy `.env.example` to `.env`.
3. Add your Home Assistant Long-Lived Access Token to `.env`.
4. Install dependencies with `python -m pip install -r requirements.txt`.
5. Run `python src/main.py`.

The real `.env` file is ignored by Git and must never be committed. Generated Discovery output is written to `output/` and is also ignored by default.

## Security and secrets

Never commit Home Assistant access tokens, `.env` files, `secrets.yaml`, Home Assistant runtime databases, logs containing secrets, or other credentials. The repository `.gitignore` excludes the main known local secret and runtime files, but contributors remain responsible for reviewing changes before publishing.

## Disclaimer

PicoT HEMS is experimental software. It is provided without warranties of availability, suitability, performance or fitness for a particular purpose. Energy-control decisions can affect connected equipment and energy costs. Test changes carefully and retain independent hardware and platform safeguards where appropriate.
