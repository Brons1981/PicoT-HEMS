# Power comparison HA 400 fix

When one of the source measurements required for the derived household-power or self-supply calculation is unavailable, the derived numeric value remains `None` inside PicoT evidence. The Home Assistant presentation layer must not serialize that value as JSON `null` in the entity `state`; it publishes the valid HA state `unavailable` instead while preserving `calculation_status: unavailable` in attributes.
