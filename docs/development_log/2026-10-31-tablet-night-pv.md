# Tablet: huisvermogen bij slapende omvormer

Reparatie op verzoek van Alex na installatie HC dev.25 (PR #735).
Alleen de tabletprojectie wijzigt; geen HEMS-planning, HC-regeling of configuratie.

Oorzaak gereproduceerd: PV ontbreekt of rapporteert langer dan 30 seconden niet;
de vereiste balansinput wordt None en daarmee verdwijnt huisvermogen.
Vijf regressiegevallen falen voor de reparatie (ontbrekend, unavailable, unknown,
verouderde nul en oude positieve PV).

De bestaande verse HA-snapshot bevat sun.sun. Alleen bij below_horizon wordt
ongeldige/ontbrekende/verouderde PV door 0 W vervangen. Een verse geldige PV-meting
blijft leidend. Geen vaste nachturen; geen wijziging aan de HA-entiteit zelf.
Ontbrekende zonnestatus of daglicht geeft geen nulaanname. Net en batterij blijven
onder de bestaande versheidscontrole. EnergyReader verwijdert de gehele snapshot
bij verbindingsverlies of ontvangst ouder dan 20 seconden, inclusief zonnestatus.

Gerichte verificatie: test_tablet.py en test_tablet_temperature.py:
20 tests en 35 subtests geslaagd. Ook dag/ontbrekende zon, verse positieve PV,
ontbrekende net/batterij en verlopen HA-snapshot gecontroleerd.

Nog niet gepubliceerd of live geinstalleerd. Geen versiebump in deze reparatie.

Brede verificatie: pytest picot_hc/tests: 457 passed, 65 subtests passed,
1 failed in 183.76s. test_weather.test_redirect_does_not_forward_credentials
kreeg Windows ConnectionAbortedError 10053 bij de lokale HTTP-testserver, voor
de verwachte redirectrespons. De ongewijzigde weer-suite afzonderlijk: 5 passed
in 2.76s. De brede run was dus niet volledig groen; lokale netwerkflakiness blijft
een verificatiebeperking. Geen weerproductiecode of bestaande tests aangepast.
node tests/tablet-ui.cjs: alle 17 gedragstests geslaagd.
