# HC/HEMS: maximaal vijf energievoorstellen beoordelen

Lokale beoordelingslaag, aansluitend op de energierichtlijn. Geen release,
commit, push, HA-publicatie of wijziging aan live apparaten uitgevoerd.

## Contract en afbakening

HC kan één aanvraag met 1 tot 5 alternatieven aanbieden via
`sensor.picot_hc_energy_proposals` (`hc-energy-proposals:v1`). HEMS antwoordt
via `sensor.picot_hc_energy_assessment` (`hc-energy-assessment:v1`).

Ieder alternatief bevat uitsluitend een opaque plan-ID, maximaal 12
niet-overlappende energietijdvakken en geschatte extra niet-elektrische kosten.
De tijden hebben een UTC-offset. Energie en kosten moeten eindig en niet
negatief zijn. De aanvraag bevestigt dat de alternatieven gelijkwaardig
comfort leveren; die verantwoordelijkheid blijft bij HC.

Deze versie accepteert uitsluitend **extra verbruik boven op de genoemde
HEMS-prognose**, met `demand_basis=additional_to_forecast`. Totale
verwarmingsenergie blind toevoegen is verboden: die kan al in de
huisverbruiksprognose zitten. Apparaatvelden en onbekende contractvelden
worden afgewezen. MEP krijgt geen temperatuur-, bron- of apparaatkennis.

Deze stap maakt nog geen automatische HC-energieprognoses. De automatische
generatie/publicatie van voorstellen vereist eerst een betrouwbare HC-raming
en reconciliatie met het verwarmingsaandeel in de HEMS-basislast. De tests
leveren expliciete energievoorstellen aan op de echte beoordelingsroute.

## Berekening

- Alle alternatieven krijgen dezelfde bewaarde HEMS-snapshot en behouden
  batterijroute. Geen nieuwe batterijroute, extra laadsessie of commitment.
- Extra energie wordt exact over de onderliggende prognose-intervallen
  verdeeld; intervalgrenzen worden waar nodig gesplitst. Bestaande
  batterij-uitgesloten belasting blijft correct geschaald behouden.
- De bestaande haalbaarheidscontrole toetst de behouden route, waaronder
  dagdoelen, herstel en exportdoelen. Ook de eindvoorraad mag niet onder de
  oorspronkelijke projectie komen: toekomstige batterij-energie is niet gratis.
- De bestaande financiële afrekening vergelijkt de hele behouden horizon,
  inclusief laad-/ontlaadverliezen en toepasselijke tariefregels. Alle prijzen
  voor die horizon moeten bekend zijn. HC's extra niet-elektrische kosten
  worden bij de extra elektriciteitskosten opgeteld.
- HEMS kiest maximaal één goedkoopste haalbare kandidaat. Gelijke kosten
  worden deterministisch op plan-ID beslist. Alternatieven worden onafhankelijk
  beoordeeld; ze delen geen afzonderlijk toegekend budget.

De scope is uitdrukkelijk `additional_demand_on_retained_route`, geen globaal
economisch optimum. Een ander batterijplan of extra netladen kan een nu
afgewezen verwarmingsprofiel later alsnog mogelijk maken, maar wordt hier
nog niet onderzocht. Er is ook nog geen reservering van energie of toets van
alle elektrische eindgroepgrenzen. Elke uitkomst bevat
`execution_authorized=false`.

## Voorwaarden bij afwijzing

Bij een onhaalbaar energieprofiel worden hoogstens twee kleinere profielen
getoetst: 50% en 25%, met dezelfde tijden en verhoudingen. De grootste van die
bewezen varianten wordt teruggegeven. Anders geldt 0 extra energie, waarvan
de basisroute vooraf is bewezen.

De reactie bevat tijdvak, oorspronkelijke plan-ID, `verified_profile_scale`,
`verified_profile_energy_wh`, de oorzaak en `requires_hc_comfort_recheck=true`.
Dit is een concreet herplanningsvoorstel, niet een exact gevonden maximum en
niet een vrij te verdelen kWh-budget. `maximum_not_searched=true` en
`budgets_additive=false` maken dat expliciet. HC moet er nieuwe, thermisch
haalbare voorstellen van maken; automatisch schalen/uitvoeren gebeurt niet.

Ontbrekende toekomstprijzen leveren een vereiste prijshorizon op. Een plan
buiten de behouden horizon krijgt een uiterste eindtijd terug. Onbekende
prognosebasis vraagt om een nieuwe energierichtlijn en herindiening.

## Geldigheid en uitvoering

De bestaande energierichtlijnworker verwerkt ook de batchaanvraag, maximaal
één worker tegelijk en eenmaal per minuut. Hij bewaart maximaal twee recent
gepubliceerde snapshots, hoogstens 120 seconden oud. Zo mag HC nog antwoorden
op de vorige richtlijn terwijl de volgende al verschijnt.

Aanvraag-ID, revisie, prognose-ID en een SHA-256 van de volledige aanvraag
koppelen antwoord en voorstel. Na rekenen wordt de aanvraag opnieuw gelezen:
vervangen of ingetrokken voorstellen worden niet gepubliceerd. Een antwoord
verloopt uiterlijk 120 seconden na opname van de gebruikte prognose. Dezelfde
ongewijzigde aanvraag wordt niet telkens opnieuw berekend. Er is nog geen
automatische herindienlus; die moet later expliciet worden begrensd.

HC toont uitsluitend een passend, actueel antwoord. Noch de uitkomst noch
de kosten zijn aangesloten op de verwarmingsregelaar. Een geselecteerd advies
is dus geen apparaatopdracht of definitief door HEMS gereserveerd plan.

## Verificatie

Nieuwe tests draaien met de echte behouden-routeprojectie, financiële
afrekening en commitmentopslag. Gedekt zijn selectie, niet-elektrische kosten,
gelijke kosten, maximaal vijf alternatieven, zes afwijzen, foute input,
dubbeltelling voorkomen via expliciete grondslag, volledig bekende prijzen,
exportbehoud, bescherming van eindvoorraad, bewezen kleinere profielen,
transportgrootte, revisie/fingerprint, annulering, vervallen antwoord en de
vorige prognosebasis. De commitmentopslag blijft ongewijzigd.

Een eerste afwijzingsproef bleek terecht haalbaar doordat netimport in dat
tijdvak de extra vraag kon leveren. De proef is gericht op het bestaande
exportvenster, waar de behouden exportverplichting daadwerkelijk wordt geraakt.
De productiecontrole is daarvoor niet aangescherpt of versoepeld.

De gedeeltelijke checkout gebruikt dezelfde test-importopzet als de vorige
stap. Live HA-transport, browsercontrole en integratie in de volledige
repository blijven releasevoorwaarden. Automatische HC-planvorming,
basislastreconciliatie, extra laden en definitieve reservering/uitvoering
zijn nog niet geïmplementeerd.

Eindcontrole: 63 tests geslaagd (19 nieuwe portfolio-tests plus de 44 tests
uit de vorige koppeling/regressies). Ruff op de nieuwe HEMS-code en tests,
Python-syntax, JavaScript-syntax en git diff --check geslaagd. Het dashboard
toont per aangeleverd voorstel extra totaalkosten of de herplanningsvoorwaarde.
