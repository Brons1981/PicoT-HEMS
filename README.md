# PicoT HEMS

**Planning, Intelligence, Coordination, Orchestration & Transparency**

PicoT HEMS is a modular, explainable Home Energy Management System for Home Assistant.

## Current phase

Phase 3 — Discovery, Canonical Data Model and dependency-risk analysis.

## Active work

- Home Assistant Discovery Tool
- Canonical Data Model
- Integration and dependency health assessment
- Architecture review and fallback design

## Core principles

- Robust and verifiable before clever or extensive
- Modular architecture
- Hardware and vendor independence
- Transparency and explainability
- Reliability and graceful degradation
- Minimal unnecessary battery relay switching

## Local Discovery setup

1. Clone this repository.
2. Copy `.env.example` to `.env`.
3. Add your Home Assistant Long-Lived Access Token to `.env`.
4. Install dependencies with `python -m pip install -r requirements.txt`.
5. Run `python src/main.py`.

The real `.env` file is ignored by Git and must never be committed. Generated Discovery output is written to `output/` and is also ignored by default.
