# Changelog

All notable PicoT HEMS project changes are recorded in this file.

## [Unreleased]

### Changed

- Renamed the project and repository terminology from HEMS Core to PicoT HEMS.
- Established `picot_hems.*` as the technical namespace convention.
- Defined Markdown as the source format for controlled documentation.
- Started the RC3 architecture migration.
- Updated DOC-000, DOC-001 and DOC-002 to include explicit user authority and the User Control Layer.

### Added

- Capability & Health Layer as an approved and frozen architecture layer.
- Learning Layer as an optional pass-through architecture component.
- Evidence over Assumption as an approved and frozen principle.
- Dynamic Device Capability and Thermal Derating rules.
- Extensible Components rule with transparent pass-through behaviour.
- User Control Layer with preferences, constraints, temporary overrides, manual commands, automation locks and release controls.
- ADR-013 defining the authority order between physical reality, capability, safety, user control, policy and optimization.
- Transparency-first dashboard direction with per-layer online, health, reliability and operating-mode status.
- Copyright requirement for official documentation.

### To migrate

- DOC-010 Project Rules
- Consistency validation of DOC-000 through DOC-002 against ADR-001 through ADR-013
- Home Assistant dashboard and package naming
- Home Assistant terminology and architecture references

## Initial repository foundation

- Initial GitHub repository structure
- Central project status file
- Project inbox
- Project board
