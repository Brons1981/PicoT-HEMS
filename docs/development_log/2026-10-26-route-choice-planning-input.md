# Routekeuze als vaste planninginput

Lokale vervolgstap op de herstelvereenvoudiging, op verzoek van Alex (vervolg).
Basis: dev.321 plus de lokale wijziging voor huidige uitvoeringscontinuiteit.
Geen versieophoging, release of liveopdracht.

## Probleem

De pipeline las pending en selected routekeuzes rechtstreeks uit Store nadat
Planning Input al was samengesteld. De hoofdroute en de handelsroute konden daardoor
keuzes uit andere leesmomenten gebruiken. Deze wijziging sluit dat gat; ze bewijst
niet dat routekeuze de oorzaak was van de eerder waargenomen storingen.

## Wijziging

- Planning Input bevat alleen de benodigde routekeuzegegevens: token, eigenaar,
  pending/selected, antwoordtermijn en onveranderlijke laadvensters.
- Store leest de relevante keuzes samen uit een payload. Aanbiedingen zonder keuze,
  vrijgegeven keuzes en keuzes van afgelopen of voltooide eigenaren worden niet
  als beperkingen meegenomen. De antwoordtermijn geldt alleen voor pending;
  een geselecteerde keuze blijft tot voltooiing, dageinde of expliciete vrijgave gelden.
- De hoofdroute en handelsroute gebruiken dezelfde vastgelegde keuzes. De bestaande
  pure toelatingspolicy krijgt een losse kopie van de benodigde velden.
- Een aangevraagde keuze zonder overeenkomend vastgelegd token mag geen andere route
  toelaten. Beschadigde relevante keuzegegevens blokkeren de inputopbouw met reden.
- De planninghandtekening bevat de keuzes, zodat acceptatie/vrijgave zichtbaar wordt
  als gewijzigde input. Tussentijdse wijzigingen herschrijven geen bestaande snapshot.
- Store blijft eigenaar van acceptatie, intrekking en definitieve vastlegging. De
  bestaande publicatiebarriere en controles bij het binden blijven intact. Dit is
  geen nieuwe transactie voor alle bestaande Store-reads tijdens inputopbouw.

ADR-034 en de canonieke immutable Planning Input blijven het uitgangspunt.
Gebruikerskeuze blijft een toelatingsvoorwaarde; Evaluation kiest de winnaar.
De economische berekening en fysieke herstelbevoegdheid zijn niet gewijzigd.
Er is geen nieuw opslagformaat of migratie van bestaande routekeuzes nodig.
Diagnoses bevatten voortaan de daadwerkelijk gebruikte routekeuzegegevens.

## Bewijs

De nieuwe integratietest faalde eerst doordat de planner pending consent opnieuw
uit Store las. Na de wijziging slaagt hij met echte kandidaatselectie en planbinding,
terwijl extra consent-reads in de planning verboden zijn.

De tien routekeuze-integratietests controleren: bestaande acceptatie/vrijgave,
verdwenen alternatief, fysieke reparatie, economische beperking, snapshotgebruik,
onveranderlijkheid/vrijgave, ontbrekende consent, herstart/dageinde en beschadigde input.
Ruff en mypy voor de vijf betrokken productiemodules zijn groen.
De brede testaanroep met webtests liep vast bij de Node-dashboardtest na acht
lokale HTTP-testfouten en is afgebroken. Een losse HTTP-callbacktest faalt met
WinError 10013 (loopback sockettoegang geweigerd), zowel op deze wijziging als
op de ongewijzigde dev.321-basis. De webmodule is niet gewijzigd. HTTP/Node-tests
worden daarom niet als geslaagd meegeteld en blijven te verifiëren in release-CI.
De afzonderlijke brede suite zonder webmodule slaagt: 180 tests in 192,52 seconden.
Deze omvat routekeuzemeldingen, policy, Store, runtime, tijdlijn, beide lokale
vereenvoudigingen, fysieke guards, reset, bridge, livepolling en architectuurgrenzen.
Na de laatste invoervalidatie slagen alle 10 routekeuze-integratietests (64,12 seconden).
Met overlap verwijderd zijn 181 unieke tests geslaagd. De 10 tests van de webmodule
zijn niet in dat succesgetal opgenomen. Geen volledige release-CI uitgevoerd.

## Afbakening

Dit voltooit de lokale vervolgstap voor routekeuze-input. De eerdere herstelwijziging
blijft behouden. Niet alle andere hersteluitzonderingen zijn hiermee opgeschoond.
Er is geen nieuwe functie of gewijzigde prijs-/PV-voorkeur toegevoegd.
