# P1 bij sluimerverbruik en vertraagd uitschakelen na BMW-eindmelding

Diagnose `energy-devices-diagnostics-20261018T071752Z.zip`, ED dev.11:
de plug meet 2,2–2,3 W zonder laden. De 20 W afronding en deadband blijven actief
bij ieder positief vermogen. Van 09:15:54 tot 09:17:45 lokale tijd blijft de
berekende waarde 20 W terwijl RAW tussen 33,763 en 61,285 W varieert.
De bronmetingen zijn vers; de oude latch is hersteld.

Reparatie in ED RegulationObserver: na 30 seconden aansluitende verse EV-metingen
van maximaal 5 W gaat RAW exact door, zonder aftrek, afronding of deadband.
Exact nul blijft direct doorgeven. Meer dan 5 W heractiveert correctie onmiddellijk.
Oude, ontbrekende of niet-aansluitende metingen bevestigen geen ruststatus.
HEMS krijgt geen apparaatkennis; de laadplanner verandert niet.

Replay op 2171 recente diagnoseregels: 2109 exact RAW, overige regels vallen in
de bevestigingsperiode of het korte bronmeetgat. Alle 94 geselecteerde regels
binnen het gerapporteerde plateau volgen na de reparatie exact RAW.
P1/regulation/guard/API-tests: 42 geslaagd; nieuwe regressietest faalde vooraf
op 20 W versus 33,763 W zoals verwacht.

Aanvullende gebruikersopdracht: BMW meldt laden beëindigd en plug nog aan:
uitschakelen na één minuut. De timer moet herstartbestendig zijn en een oude
eindmelding mag geen nieuwe laadsessie uitschakelen. De geaccepteerde geplande
eindtijd blijft een harde grens. Dit werk is nog niet uitgebracht.

Timer geïmplementeerd: 60 seconden vanaf eerste bevestigde huidige BMW-eindmelding,
ook bij handmatig of eerder afgesloten sessies. De timer blijft bewaard bij herstart;
nieuwe laadactiviteit/plug-inschakeling wist oude intentie. Uitschakeling wordt iedere
10 seconden herhaald totdat de uitstand is bevestigd. Geen uitbreiding laadvenster.
Gecombineerde nieuwe BMW/P1-tests: 32 geslaagd. Bestaande EV-sessie/advice/direct-start
en P1-regressies: 60 geslaagd. Ruff schoon.
