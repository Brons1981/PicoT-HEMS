# Changelog

All notable project changes are recorded in this file.

## [Unreleased]

### DEV.237

- Behoud maximaal één geldige handelsroute per lokale kalenderdag, zodat een
  route voor vandaag en een route voor morgen niet langer om één plek in de
  volledige 36-uursplanning concurreren.
- Combineer deze dagroutes tot één begrensd volledig MEP-pad; de Opportunity
  Engine blijft uitsluitend prijsvensters leveren en Evaluation blijft de
  financieel beste fysiek geldige kandidaat kiezen.
- Voer het laatste gedeeltelijke exportinterval uit als een exacte
  Wh-zandloper: stop zodra het energiebudget op is, ook midden in een
  kwartier, wek de Execution Engine op die grens en hervat direct slimme
  huishoudondersteuning vóór een eventuele nieuwe plannerrun.

### DEV.229

- Beheer persistente gebruikersregels vanuit het Strategie-dashboard.
- Behoud NOM/PV-opvang rond noodzakelijk netladen en laat netenergie alleen
  het resterende opslagtekort aanvullen.
- Begrens handel met de instelbare SoC-zandloper, de technische ondergrens,
  huishoudreserve en 10 procentpunt extra reserve.
- Pas gebruikersregels toe tijdens Candidate-reductie, vóór de financiële
  selectie, en start na iedere wijziging direct een nieuwe planningsrun.

### Added

- Initial GitHub repository structure
- Central project status file
- Project inbox
- Project board
