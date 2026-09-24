# 24 september — overbruggingscontrole bij samengesteld plan

Status: release dev.270 voorbereid op dev.269 na Alex’ opdracht. Publicatie via
PR en CI; installatie en liveverificatie volgen afzonderlijk.

## Contract

De eerste fout zit in `IndependentDailyReferenceAdapter.bridge_assessment`:
zonder volgende hoofdlaadsessie veronderstelde deze een directe koppeling tussen
het actieve plan-ID en `DailyChargeAssignment.route_plan_id`. Een gevalideerd
samengesteld marktplan heeft echter een eigen ID en bewaart de laadherkomst in
zijn segmenten. De Store bewaart die relatie correct.

Autoriteit: ADR-037.9 (onbekende vervolgsessie, behoud geldige uitvoering),
ADR-033 (behoud segmentherkomst) en het canonieke pipelinecontract.
Verantwoordelijke grens: de bestaande overbruggingsbeoordeling in de dagelijkse
referentieadapter. Prijsselectie, Candidate/Evaluation-beleid, marktroute,
Plan Builder, Store, uitvoering, PV-terugval en HA-configuratie blijven gelijk.
Geen opslagschemamigratie, planreset of nieuwe laadopdracht. Dev.268 blijft de
gebruikersafspraak voor terugval, maar bevat deze bestaande fout eveneens.

## Herstel

De controle accepteert zowel de directe laadroute als een bewaarde
`main_assignment_id` met `retained_execution_origin.plan_id` naar de laadroute,
steeds binnen dezelfde uitvoeringsscope. Deze opdracht is de ingang van de
bestaande simulatie van alle behouden opdrachten en het volledige actieve plan;
zij vervangt of herbindt het samengestelde plan niet.

Een ontbrekende relatie geeft `DailyReferenceInputError` met
`bridge_retained_plan_owner_missing`, in plaats van ongecontroleerde
`StopIteration`. De bestaande pipelinefoutafhandeling blijft verantwoordelijk;
in de geteste optionele beoordeling blijft het bestaande plan behouden met een
expliciete foutreden. Geen nieuw algemeen exceptionvangnet toegevoegd.

## Bewijs

De ZIP van 24 september bevat het samengestelde actieve plan, zijn oorspronkelijke
laadroute en de voltooiing om 12:21:46 lokale tijd. De laatste vastgelegde
pre-voltooiingscontext plus de bewaarde voltooiing reproduceren de oorspronkelijke
StopIteration. Het volledige crashsnapshot ontbreekt: dit is een reconstructie.

Na herstel doorloopt dezelfde reconstructie de echte adapter en simulator:
`next_session_unknown`, geen trigger of fictieve volgende deadline. De replay
gebruikt de eerdere forecasts, de vastgelegde 100%-voltooiing en RTE 0,8136;
lees-/capturetijden zijn naar het gereconstrueerde beoordelingsmoment gezet.
Dit bewijst herstel van deze codegrens, geen exacte historische financiële replay.
De persoonlijke ZIP en tijdelijke decoder zijn niet aan de repository toegevoegd.

De bestaande canonieke no-next-session-test is uitgebreid met een samengesteld
marktplan en herstart uit echte opslag. Vóór herstel: gewone route slaagt,
samengestelde route faalt met dezelfde StopIteration. Na herstel: beide behouden
het actieve plan, de segmenten in de Store en de voltooide dagopdrachten. Een
opzettelijk ontbrekende segmentverwijzing geeft de expliciete foutreden zonder
crash of wijziging van de opgeslagen plannen/opdrachten.

Gerichte overbruggings-, marktbindings- en marktselectiesuite: 36 geslaagd.
Aanvullende negatieve controle plus beide no-next-session-varianten: geslaagd.
Ruff op gewijzigde code/tests geslaagd; mypy op 225 bronbestanden geslaagd.
Volledige suite: 1.706 geslaagd, 1 overgeslagen, exit 0 (293,27 s).
De laatste aanscherping van de herstarttest (ook nieuwe pipeline-instantie) is
afzonderlijk opnieuw geslaagd. Ruff op heel `src/picot` en de gewijzigde tests
slaagt; `git diff --check` is schoon. Geen publicatie of live-validatie uitgevoerd.
