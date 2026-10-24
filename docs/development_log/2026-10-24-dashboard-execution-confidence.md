# Uitvoeringsmelding en consistente planningskleuren

Status: lokaal hersteld op gepubliceerde dev.318 / commit
2712969e2335108418742377c02bfa3d8701c48e. Geen nieuwe release of livewijziging.

## Contract

Alex meldt een gele 0%-planningszekerheidsbalk die zegt dat het plan niet wordt
uitgevoerd, en vraagt rood voor netladen zodat kleuren overal overeenkomen.
De eerste foute grens is Projection/UI: ontbrekende nieuwe kandidaatscores bij
planbehoud werden nul en vervolgens een verzonnen uitvoeringsblokkade.
Het canonical pipeline contract en V2ADR-061 blijven leidend: alleen Execution
bepaalt de uitvoeringsstatus, de UI rapporteert de records. MEP, Evaluation,
Plan Store, dispatch, reservegrenzen, HC en configuratie blijven gelijk.
Terugvalgrens is uitsluitend deze dashboard/projectiepatch; geen migratie of
herberekening van het plan vereist.

## Diagnose en reproduceerbaar bewijs

Bron: picot-diagnostics - 2026-10-24T234615.766.zip. Laatste geregistreerde
plannerpoll: 2026-10-24T21:40:21.211667+00:00, dev.318,
run-15ae9076b17a0cf7. Evaluation is plan_retained, zonder nieuwe kandidaten of
uitkomsten. Plan plan-079c3ecd0827380d is aanwezig; Execution live_plan_ready,
primitive boundary en vendor result already_active, geen blockers of vendorfout.
De keuzestand is Standby en past bij het opgeslagen segment. Dit is bewijs van
de teruggelezen HA-keuzestand, niet van fysieke omvormerwerking. De eerstvolgende
andere primitive in dit opgenomen plan is NOM op 25 oktober 08:00 CET.
De HC-belastingsbron is in deze poll beschikbaar.

Een offline projectiereplay van deze exacte poll reproduceert de onjuiste melding
op dev.318. Na de patch: confidence_percent=null, status=already_active,
warning_nl=null, blockers leeg. Dezelfde plan- en uitvoeringsrecords blijven
intact. Dit is een projectiereplay, geen herplanning of live-uitvoeringsproef.

## Wijziging

- Ontbrekende planningsscore blijft onbekend. Een nul of afgeronde nul mag geen
  uitvoeringsblokkade scheppen. Readiness volgt de primitive boundary en echte
  vendorfouten, inclusief hun concrete reden; planbehoud wordt als behoud benoemd.
- De planvergelijking en historie gebruiken dezelfde kleuren als de prijsbalk:
  netladen rood #df5c57, NOM groen #35a862, slim ontladen blauw #3994e6,
  stand-by geel #e3aa45 en terugleveren grijs #aab2bd. Ook de arcering voor slim
  ontladen gebruikt de bestaande blauwe kleur.
- Bestaande API-envelop blijft; confidence_percent kan null zijn waar geen score
  beschikbaar is. Er wordt geen minimumzekerheidsbeleid aan de UI toegevoegd.

## Verificatie

Zeven nieuwe gevallen falen op dev.318 om de bedoelde redenen: drie gezonde
uitvoeringsstatussen zonder nieuwe scores, twee echte blokkades, een vendorfout
en de kleuren. De eerste gerichte run na herstel: 35 geslaagd. Een extra
DOM-regressie controleert dat de foutbalk verdwijnt na herstel en een echte
vendorfout wel toont. Ruff, mypy en de uitgevoerde JavaScript-syntax zijn groen.
De brede testuitslag volgt hieronder. Geen browser- of HA-livevalidatie uitgevoerd.

Brede controle: 96 tests geslaagd; 8 HTTP-tests uit test_route_choice_web konden
niet uitvoeren door Windows-sandbox WinError10013 bij socketverbindingen. Deze
blijven expliciet onverifieerd en moeten in GitHub CI draaien voor publicatie.
De geslaagde set omvat echte canonical planselectie/planbehoud, foutprojectie,
routekeuzerendering, historie, actuele status en de nieuwe regressies. De run
had exitcode 1 wegens de acht omgevingsfouten; geen volledig groene HTTP-claim.
