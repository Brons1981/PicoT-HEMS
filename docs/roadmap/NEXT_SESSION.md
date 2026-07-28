# Next PicoT HEMS Session

## Topic
Capability Source Selection Architecture

## Objective
Produce the authoritative architecture document for deterministic capability source selection before further implementation.

## Scope

1. Define the responsibility and boundaries of the Selection layer.
2. Define the deterministic selection algorithm and tie-breaking rules.
3. Define the complete `SelectionRecord` structure.
4. Define the Capability Mapping Store and persistence model.
5. Define mapping lifecycle states and transitions:
   - `ACTIVE`
   - `TEMPORARILY_UNAVAILABLE`
   - `INVALID`
   - `REDISCOVERY_REQUIRED`
6. Define automatic initial selection versus explicit user confirmation.
7. Define selection and mapping history requirements.
8. Define integration with Explain and Diagnose.
9. Define how planner decisions reference mapping versions.
10. Define a source abstraction that can later support entities, local APIs, event streams, and composed measurements without implementing those features now.

## Constraints

- No new unrelated functionality.
- No automatic source replacement after temporary unavailability.
- Rediscovery remains scoped to one capability.
- Planner consumes capabilities only.
- User-impacting source changes require deliberate confirmation.
- GitHub architecture and ADRs are authoritative.

## Guiding principle

> Architecture future-proof, implementation minimal.
