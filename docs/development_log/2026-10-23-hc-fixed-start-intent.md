# HC: vaste starttijd voor herbeoordeling

Een lokaal gecontroleerde HEMS-keuze voor een uitgestelde start beneden wordt nu als startvoornemen in SQLite vastgelegd. Nieuwe voorstellen gebruiken diezelfde absolute starttijd, ook als de nieuwe HEMS-basis op een later tijdstip begint. De bestaande vijf alternatieven blijven beschikbaar zolang er nog geen keuze is vastgelegd.

## Gedrag

- Het voornemen bewaart starttijd, doeltemperatuur, comfortvenster, schema- en verwarmingsrevisie, meetidentiteit en de oorspronkelijke geldigheid van de beoordeling.
- Een verlopen beoordeling laat het voornemen bestaan met `needs_assessment`. Alleen een nieuwe gecontroleerde keuze voor dezelfde starttijd en temperatuur kan de beoordelingsgeldigheid vernieuwen. Herhalen van dezelfde request verlengt niets.
- Nieuwe profielen ramen wachten, opwarmen en handhaven opnieuw met de bestaande meetmodellen. Een vaste start vóór het begin van het nieuwe profiel wordt niet verschoven: er komt dan geen passend voorstel.
- Een gewijzigd schema, uitgeschakelde regeling, ontbrekende geldige meting, gewijzigde meetidentiteit, gewijzigde verwarmingsinstellingen, actieve/pending warmtebron, te sterke afkoeling, gewijzigde comfortgrens of bereikte starttijd laat het voornemen vervallen. Runtime levert bij verbindingsverlies geen geldige meetsample aan.
- Na een herstart blijft het opgeslagen voornemen zichtbaar, maar wordt het geannuleerd. Een geannuleerd voornemen wordt voor hetzelfde comfortvenster niet automatisch opnieuw aangemaakt.
- Runtime en de HC-statusweergave tonen het startvoornemen los van de kort geldige HEMS-keuzebevestiging.

## Afbakening

Dit is een vast **voornemen voor herbeoordeling**, geen uitvoeringsafspraak of energiereservering. `execution_authorized` blijft `false`. De normale thermostaat en het bestaande voorverwarmen blijven zelfstandig werken. Er zijn geen nieuwe klimaatopdrachten, MEP-wijzigingen of wijzigingen aan de behouden batterijroute. Boven, garage en badkamer krijgen geen startvoornemen.

De huidige voorstellen beginnen minimaal 120 seconden in de toekomst. Zodra een vaste start buiten dat bereik valt, kan deze adviesroute geen nieuw voorstel meer maken. Een aparte koppeling voor geldige uitvoering en terugval bij de start blijft nodig; oude adviezen mogen daarvoor niet stilzwijgend worden verlengd.

## Verificatie

Gerichte tests gebruiken echte SQLite-opslag, de bestaande gemeten opwarm-/handhaafmodellen en de voorstelgenerator. Ze bewijzen een vaste start over een nieuwe HEMS-basis, afzonderlijk adviesverval, herbeoordeling, annulering, herstart en weigering van verlopen/ingetrokken/niet-passende keuzes. Runtime-status en de bestaande collector-/thermostaatcontroles worden meegenomen in de bredere regressiereeks.

Niet live geactiveerd of uitgerold. Home Assistant-transport is in de runtime-tests vervangen; echte apparaten en een browser zijn niet getest.

Resultaten: brede pytest-reeks 166 geslaagd in 79,73 seconden; de gerichte startvoornemenreeks na toevoeging van vier negatieve gevallen 15 geslaagd in 5,70 seconden (11 overlappen met de brede reeks). Ruff op de nieuwe en gewijzigde energiemodules en tests, F-controles op Runtime en de collectortests, `node --check` voor app.js en `git diff --check` geslaagd. Geen commit of publicatie uitgevoerd.
