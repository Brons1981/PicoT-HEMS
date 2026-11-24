# Herstel dagplan na verlopen aanvullende laadopdracht

Op 24 november bereikte de batterij om 04:58 100%. Om 05:01 ging HEMS naar
fallback bij het activeren van de vervolgroute. De opslaglaag vereiste dat een
nog openstaande aanvullende laadopdracht van 14 november in die route werd
overgenomen, hoewel het laadvenster al was verlopen.

De opslaglaag sluit bij het vastleggen van een herstelde route aanvullende
opdrachten uit waarvan het laadvenster op of vóór de aanmaaktijd van het plan
eindigde. De oorspronkelijke registratie en de koppeling aan het oude plan
blijven behouden. Zonder meetbewijs krijgt de opdracht geen voltooiingsstatus.
Lopende en toekomstige opdrachten moeten nog steeds worden behouden.

De diagnose van 24 november is lokaal vóór en na de reparatie afgespeeld.
Dezelfde invoer ging eerst naar fallback en activeerde na de aanpassing de
vervolgroute. De registraties van hoofd- en aanvullende laadopdrachten bleven
gelijk. Alle 92 gerichte tests zijn geslaagd, inclusief venstergrenzen en herstart.

Alleen HEMS krijgt versie 2.0.0-dev.343. Een planreset is niet nodig.
