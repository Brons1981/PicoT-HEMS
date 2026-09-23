# 23 september — onafhankelijke netbalans bij PV-API-uitval

Status: release dev.269 voorbereid vanaf `7e49bf9` (dev.268). Alex heeft
publicatie aangevraagd; de wijziging gaat via PR en CI naar main. Installatie
en liveverificatie volgen afzonderlijk. Contract en gerichte
aanvullingen op ADR-037.12/.15 staan in ADR-037.17.

## Gedrag en eigenaarschap

Terugvalbesluit Alex, 23 september: de huidige uitgebrachte **2.0.0-dev.268**,
commit `7e49bf9eff507e7f277f5007d400bac731b07f25`, is vanaf nu de eerste
terugvalbasis. De nieuwe netbalansfunctie valt daar niet onder. Dev.254 blijft
uitsluitend een ouder historisch checkpoint; overige stopafspraken blijven gelden.

`net_balance.py` verrijkt Planning Input met een vijfminutenbewijs bij ontbrekende
actuele PV, onder de in ADR-037.17 vastgelegde grenzen. Het gebruikt getekend
netvermogen en gevalideerd werkelijk opslagvermogen; SOC en mapping blijven
onderdeel van de herkomst. Een directionele nul vereist bij een oude
wijzigingstijd expliciet actueel HA-leesbewijs. Net en getekend opslagvermogen
moeten verse telemetrie houden. Herstart bouwt het bewijs opnieuw op.

Material Replanning en MEP gebruiken hetzelfde bewijs en dezelfde
NOM-vervangingsproef. Alleen een compleet fysiek haalbaar pad kan worden
geselecteerd. Een onbekende huisbelasting mag onder dit bewijs de beoordeling
niet blokkeren; actief bewezen extra belasting behoudt haar bescherming.
Een vervallen bewijs opent geen nieuwe vermindering. De zelfstandige
tekortcontrole en eventuele herstelplanning blijven iedere poll actief.

De Planning Input-diagnostiek bevat `net_balance_status` en
`net_balance_surplus`, met samples, brontijden, bewijs-ID en scope/SOC.
De revisiereden is `net_balance_allows_grid_reduction` en de trigger verwijst
naar het onafhankelijke bewijs. PV-actuals en huishoudelijke meetgeschiedenis
worden niet aangevuld. De vergelijking blijft bij meetgaten `partial`, met
onbekende energievelden. Oude grid-review-identiteiten blijven zonder netbewijs
ongewijzigd. De bestaande opslag van opdrachten en oorspronkelijke PV-basis
krijgt geen schemawijziging.

## Regressie en diagnose-replay

De regressie faalde vóór de toelatingswijziging: bij ontbrekende PV, onbekende
huisbelasting, 90% SOC en onafhankelijk overschot bleef de trigger leeg.
Na de wijziging selecteert dezelfde canonieke keten minder netladen, zowel
vóór als tijdens het bestaande laadblok. Vrijgekomen netlaadintervallen zijn
NOM en komen overeen met het geselecteerde Energy Path.

De aangeleverde diagnose van 23 september is lokaal opnieuw beoordeeld:
bronpolls vanaf 13:15 Nederlandse tijd, werkelijke SOC-historie en het volledige
planningssnapshot van 13:25:09. Op dat moment: SOC 86%, opslagladen 1.898 W,
netvermogen -438,431 W, RTE 81,62%, onvolledige PV-vergelijking en onbekende
huisbelasting. Het vermogensverschil is 2.336,431 W overschot vóór opslag.
De nieuwe HA-uitleesmetadata voor de ongewijzigde directionele nul is in deze
historische replay gereconstrueerd uit de geregistreerde assemblagetijd;
dev.268 bewaarde die leestijd nog niet voor deze rol.

De replay levert aanhoudend netbewijs, een geldige vervangingsproef en vijf
haalbare kandidaatvensters (`pv_only_covers_main_goal`). Dit toont kandidaat-
haalbaarheid op de oorspronkelijke prognoses, geen historische besparing of
bewezen live-schakelmoment. Het oorspronkelijke 100%-doel blijft 8.160 Wh.
Persoonlijke diagnosebestanden zijn niet aan de repository toegevoegd.

## Verificatie en vervolg

- 21 gerichte regressies: meetvenster, herhaalde poll, herstart, actuele nul,
  brongaten, stale/skew, foutieve eenheden/waarden, inconsistent opslagvermogen,
  dalende SOC, alleen batterij-export, onvoldoende overschot, mappingwissel,
  terugkerende PV, canonieke lineage, minder netladen en NOM-continuïteit.
- Actieve belasting en onhaalbaar dagdoel blokkeren vermindering; de
  zelfstandige tekortcontrole blijft herstel vragen. Monitor blijft read-only.
- Ruff op `src/picot` plus de nieuwe tests slaagt; mypy op 225 bronbestanden
  slaagt. Een beschadigde lokale mypy-cache is omzeild met een afzonderlijke
  cachemap; er zijn geen typefouten genegeerd.
- Definitieve volledige suite: `python -m pytest -q` — 1.705 geslaagd,
  1 overgeslagen, exit 0 (266,72 s). Inclusief de architectuurcontroles en
  bestaande canonieke end-to-endscenario's. `git diff --check` schoon.

Publicatie, CI en installatie volgen afzonderlijk. Live nog te bevestigen:
de vijfminutenbewijsopbouw, eventuele routeherziening en uiteindelijke dagelijkse
voltooiing. Forecastonzekerheid blijft bestaan; de netmeting wordt niet als
toekomstige productie geëxtrapoleerd. Rollback verwijdert de nieuwe bewijs-
toelating en runtimeverrijking, zonder bestaande opgeslagen plannen te migreren.
