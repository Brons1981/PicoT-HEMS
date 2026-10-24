# HC-integratie op HEMS dev.314

Basis: releasecommit `53d3eedbe9e53f8431af45dc33b50824068c63de` uit midnight-charge-fix. De live reparatie blijft leidend. De oorspronkelijke HC-werkmap en de releasecheckout zijn niet gewijzigd.

Een lokale clone mislukte door de MSYS/Windows-omgeving (NtCreateDirectoryObject, access denied). Daarom is een exacte git archive-export van dev.314 gemaakt in hc-integrated-dev314. Dit is een volledige bronboom, geen nieuwe release of gepubliceerde branch. De herkomst en gewijzigde bestanden staan in integration-manifest.json.

HC-bestanden zijn per bestand drieweg samengevoegd met dev.313 (`9696708`) als gemeenschappelijke basis. Alle wijzigingen pasten zonder inhoudelijk conflict. Drie uitsluitend toegevoegde lege regels in bestaande webbestanden zijn niet overgenomen.

De AST van `_restore_daily_charge_context` is exact gelijk aan dev.314. Alle overige releasebestanden buiten de expliciete HC-wijzigingslijst zijn byte voor byte met de release-export gecontroleerd, inclusief de regressietests van de nachtelijke reparatie. Een aanvankelijke vergelijking met git show verschilde door de archive-regelafbrekingen; de controle vergelijkt daarom met dezelfde git archive-export. Geen gewijzigde daggrens-, verlengings- of voltooiingsregels toegevoegd. Versies blijven dev.314 voor HEMS en dev.22 voor HC tot releasevoorbereiding.

HEMS-wijzigingen omvatten publicatie van energierichtlijnen, beoordeling/selectie van HC-plannen, herleidbare verbruiksvervanging en geaccepteerde/gereserveerde verbruiksprofielen. MEP blijft apparaat-onafhankelijk. De CV-planvorming en uitvoering, volledige economische vergelijking inclusief extra laden en uitbreiding van de leerlogica zijn hiermee niet afgerond; deze integratiestap behoudt de bestaande lokale functionaliteit.

De gecombineerde verificatie gebruikt uitsluitend src en tests uit de nieuwe volledige boom. Er is geen importpad naar ev-deadline-advice of de oude HC-productiecode nodig. Home Assistant-transport in de HC-integratietests is nagebootst; browserbediening, echte HA-communicatie en gerealiseerde SOC zijn niet live geverifieerd.

## Verse verificatie

- Gecombineerde HC/HEMS-reeks inclusief de zes dev.314-nachtregressies en versiecontrole: 337 tests en 13 subtests geslaagd in 99,61 seconden.
- Aangrenzende laadroute-, horizon-, marktbindings-, prognose- en huishistorietests: 61 tests geslaagd in 24,58 seconden.
- Samen: 398 tests en 13 subtests geslaagd.
- F-controle voor live_runtime.py, planning_input.py en household_load_history.py geslaagd.
- Python-syntax van alle gewijzigde Python-bestanden en node --check voor app.js en heating.js geslaagd.
- 932 ongewijzigde release-exportbestanden gecontroleerd; de nachtelijke reparatiefunctie is AST-identiek.

Geen commit, push, release of live activatie uitgevoerd. De nieuwe werkbasis voor vervolgwerk is hc-integrated-dev314; hc-comfort-work blijft de oorspronkelijke ontwikkelbron.

Historisch integratiecheckpoint. Voor de huidige reserveroute, gewijzigde
herstelherkenning en verificatie zie 2026-10-24-hc-type-repair.md en
2026-10-24-hc-reserve-completion.md.
