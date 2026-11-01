# Normale wachtstand op de SOC-ondergrens

Opdracht: repareer execution_soc_below_segment_minimum zonder de ontlaadgrens
te verlagen of het bestaande laadvenster te verschuiven.
Basis: main cb99c5897330aeef993f7375cff513702267fdcc (HEMS dev.327).
Werkmap: soc-minimum-wait-fix; bronmap bridge-elapsed-main-fix ongemoeid.

Diagnose: picot-diagnostics - 2026-11-01T094926.021.zip, planning incident
run-fa4ed19ae3dd162e. SOC 0.10, segmentminimum 0.10; ontlaadsegment
09:15-11:15 Europe/Amsterdam, gepland laden 11:15-14:45. De controle gebruikt <=,
hoewel de oude fouttekst alleen 'below' zegt. De runtime vroeg ontladen aan en
blokkeerde dit; bij een reeds actieve ontlaadmodus werd eerder voor die controle
al already_active teruggegeven.

Wijziging in de uitvoeringslaag: de bestaande SOC-controle vertaalt uitsluitend
een ontlaadverzoek op/onder het segmentminimum naar STANDBY, voor mapping en
modusfeedback. Beide dispatchroutes gebruiken dezelfde ondergrenscontrole.
Geen opgeslagen plan, segmenttijd, opdracht, SOC-grens of laadvermogen gewijzigd.
NOM, PV-laadmodus, herstel/netladen, bovengrens en EV/marktbeveiliging behouden
hun bestaande gedrag. De wachtstand vereist een geldige standby-mapping en,
voor de dagelijkse route, aanwezige standby-capability. Handmatige bediening,
BMS, uitvoeringsautorisatie, foutmeldingen en feedbacktimeout blijven gelden.

Normale status: execution_soc_minimum_reached. Dashboard meldt dat standby is
gevraagd om verder ontladen te voorkomen en dat het laadvenster ongewijzigd is.
Een mislukte opdracht of ontbrekende mapping blijft een echte fout.

Verificatie:
- Regressietest faalde voor de wijziging: reeds actieve ontlading bleef actief.
- Gerichte suite: 109 tests geslaagd (reserve, dispatch, EV, herstel, dagplan, markt).
- Tests bevestigen standby, geen herhaalde opdracht na feedback, intacte SOC-grens,
  ongewijzigd opgeslagen plan en vervolgens laden in hetzelfde geplande segment.
- Beide ontlaadprimitieven getest op en onder minimum; boven minimum blijft
  ontladen actief. Ontbrekende SOC/mapping wordt niet als normale wachtstand gezien.
- Dashboard: 39 tests geslaagd; syntaxiscontrole apart geslaagd met PYTHONUTF8=1.
  De eerste syntaxisproef strandde op Windows cp1252, niet op JavaScript-syntaxis.
- Ruff op alle gewijzigde Pythonbestanden geslaagd.
- Mypy met Linux-doelplatform en Python 3.12: geen fouten in 131 bronbestanden.
  Gebruikt Python 3.14-host met bijpassende bestaande mypy-dependencies; eerdere
  lokale pogingen hadden een Python/dependency- of Windows-doelplatformmismatch.
- Na expliciete typevernauwing in de dispatchroute: 17 gerichte regressietests
  opnieuw uitgevoerd; alle geslaagd. Ruff opnieuw groen.

Geen publicatie, versiebump of live installatie uitgevoerd.
