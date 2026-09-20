# 20 september — oorspronkelijke tijdnotatie in historisch bewijs

Status: geïmplementeerd en geverifieerd vanaf dev.265; dev.266 wordt na akkoord
van Alex voorbereid voor publicatie via PR en geslaagde CI.

## Verandercontract

Eerste foutgrens: incidentserialisatie normaliseert datetime naar UTC voordat
zowel de diagnose als de passieve opname de tekst ontvangen. Bestaande MEP-ID's
gebruiken onder meer repr van tijdsintervallen. Gelijke tijdstippen met een andere
offset leveren daardoor verschillende afgeleide ID's bij replay.

Eigenaar: incident-/bewijsopslag. Canonical Pipeline Contract, ADR-017 en ADR-028
blijven leidend: historie heeft geen planningsautoriteit en gebruikt de bestaande
begrensde opname. MEP, Candidate/Evaluation/Plan Builder, commitment, HA en
uitvoering vallen buiten scope. Invariant: bronnotatie behouden, zonder andere
triggerfrequentie, nieuwe opslagronde of wijziging aan bestaande ID-algoritmen.
Terugval: alleen de nieuwe recordserializer terugzetten; oude bestanden behouden.

## Wijziging

Een afzonderlijke recordserializer bewaart datetime.isoformat() met de bestaande
offset in incidentregels en de pre-reductiecallback. De bestaande UTC-serializer
blijft voor fingerprints behouden. Expliciet benoemde captured_at_utc/local-velden
blijven gelijk. Oude JSON-strings, bestanden en digests worden niet herschreven.
Het is ISO-offsetbehoud, geen opslag van de Python tzinfo-klasse, ZoneInfo-sleutel
of fold. Deze wijziging certificeert geen universele replay van elke tijdzonevorm.

## Bewijs

De diagnose van 20 september 08:55 bevat drie intacte dev.264-proefrecords en de
originele beslissing van 19 september 17:08 (dev.263). Offline indexverwerking
slaagt. De oorspronkelijke plan-/snapshot-/evaluation-koppeling is teruggevonden.

De 124 oorspronkelijke prijs-ID's reproduceren met +02:00 (124/124), niet met UTC
(0/124). Na herstel van deze bewezen bronnotatie levert dev.263 exact dezelfde
82 canonieke kandidaatuitkomsten, EvaluationRecord en plan-d03be5bef26df437.
Het volledige canonieke plan stemt overeen na vergelijking van gelijke tijdstippen.
Dit omvat geen opnieuw uitgevoerde HA-aansturing of certificering van alle dagen.

De nieuwe opslagregressie faalt vóór de wijziging op +02:00 versus UTC. Na de
wijziging slagen 65 gerichte tests voor incidentregistratie, opslag, proefopname,
export, diagnose en architectuur. Ruff slaagt. De echte gereconstrueerde snapshot
is vervolgens via de aangepaste opslag geschreven en teruggelezen: bronnotatie,
alle 82 uitkomsten, EvaluationRecord en plan-ID blijven exact gelijk. Deze lokale
proef gebruikt uitsluitend de aangeleverde gegevens, geen HA-verbinding.

Historische koppelingen gebruiken de opgeslagen oorspronkelijke ID's. Deze
worden niet vervangen door replay-ID's. Geen permanente opname geactiveerd;
vervolgwerk voor bewaartermijn, actieve plandependencies en langere praktijkproef
blijft afzonderlijk. Releaseversie voorbereid als dev.266; geen live wijziging uitgevoerd.

Typecontrole: mypy slaagt op alle 223 bronbestanden met een aparte cachemap.
De eerste runs strandden op een corrupte lokale SQLite-cache (database disk
image is malformed), ook met --no-incremental; geen broncodefout.
