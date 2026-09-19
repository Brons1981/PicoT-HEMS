# PicoT History Probe

Tijdelijke, afzonderlijke Home Assistant-app voor een kleine synthetische
belastingproef op de NUC. Geen nieuwe PicoT HEMS-versie.

Na handmatig starten voert deze app één proef uit en stopt. Het JSON-resultaat
verschijnt in het logboek. Een gestopte app is na deze proef dus normaal.
`workload_complete: true` betekent dat vier synthetische records zijn opgeslagen
en verwerkt; het is geen vrijgave van opname in de draaiende planner.

De app vraagt geen Home Assistant-/Supervisor-/Docker-API-toegang, geen
hostnetwerk, extra rechten, poorten of gedeelde directories. Hij gebruikt alleen
zijn eigen `/data` voor tijdelijke proefbestanden. AppArmor blijft ingeschakeld.
De code maakt geen netwerkverbindingen; dit is geen netwerkfirewallgarantie.

Dit pakket is lokaal voorbereid. De containerbouw en uitvoering onder Home
Assistant Supervisor zijn nog niet gecontroleerd. Er is nog niets gepubliceerd,
geïnstalleerd of op de NUC gestart.

Zie [DOCS.md](DOCS.md) voor uitvoering en interpretatie.
