# Laadroute kiezen via de Home Assistant-app

HEMS blijft automatisch plannen. Een aangeboden PV-alternatief kan via de
telefoon gekozen worden. Een klik is een verzoek: pas de bevestiging van HEMS
betekent dat het alternatief met actuele gegevens is gecontroleerd en vastgelegd.
De automatisering bedient geen batterijmodus en bepaalt geen laadroute.

## Eenmalige instelling

1. Maak in Home Assistant onder **Instellingen → Apparaten en diensten → Helpers**
   een **Tekst**-helper, bijvoorbeeld `input_text.picot_route_choice_response`.
   Gebruik maximale lengte **255**. Laat de beginwaarde leeg; het is geen geheim
   of wachtwoord.
2. Vul die exacte entiteit bij de PicoT HEMS-app in als
   `route_choice_response_entity`. Herstart de app na aanpassen van de appoptie.
3. Importeer `blueprints/automation/picot_route_choice.yaml` uit de repository en
   maak er één automatisering van. Kies je iPhone en dezelfde teksthelper.
   Gebruik voor deze koppeling een eigen helper, niet een teksthelper voor andere
   automatiseringen.
4. Laat de bestaande gezondheidsmeldingen actief. Routevoorstellen zijn een
   aparte automatisering; de fout- en herstelmeldingen blijven beschikbaar.

Er zijn geen nieuwe open poorten, lange toegangstokens of REST-opdrachten in
`configuration.yaml` nodig. Home Assistant ontvangt de telefoonactie en schrijft
het verzoek in de helper. HEMS haalt die in de achtergrond ongeveer iedere vijf
seconden op. De bestaande HA-appverbinding moet beschikbaar zijn.

## Verwacht gedrag

- Zonder reactie blijft het automatisch gekozen plan geldig.
- Een oude melding kan geen verlopen of vervangen alternatief activeren.
- De keuze geldt voor één laadopdracht, niet voor alle volgende dagen.
- Bij de opdracht kan **Laat PicoT weer kiezen** de voorkeur opheffen.
- Een herstart van HA beëindigt geen wachtende automatisering: er wordt niet in
  een lange `wait_for_trigger` gewacht. Een al ontvangen antwoord blijft in de
  helper staan. HEMS moet dubbele of herhaalde antwoorden op identiteit afwijzen.
- Als de helper niet is ingesteld verstuurt HEMS alleen informatieve meldingen,
  zonder knoppen die geen antwoord kunnen terugsturen.

De helper is uitsluitend berichtentransport. HEMS blijft verantwoordelijk voor
geldigheid, planversies, het accepteren van de keuze en noodzakelijk herstel.

## Controle na installatie

Controleer bij een echt aangeboden alternatief dat de telefoonmelding verschijnt,
dat een klik de helper wijzigt en dat HEMS daarna acceptatie of afwijzing meldt.
De helperwijziging alleen bewijst niet dat de route geaccepteerd is. Controleer
vervolgens de status van de laadopdracht op het PicoT-dashboard.
