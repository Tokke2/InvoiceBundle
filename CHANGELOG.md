# Ändringslogg / Changelog

## v1.0.0 — 2026-10-13

Första officiella releasen. / First official release.

### Svenska
- **Leverantörsfliken lagad** — den var helt död på grund av en `ImportError` (vyfunktioner som saknades i hjälpmodulen). Om en vy ändå skulle misslyckas visas nu en felruta med **Försök igen** i stället för en tyst död flik.
- **Två språk** — hela gränssnittet på svenska och engelska, bytbart direkt i menyn 🌐 Språk eller på Inställnings-fliken.
- **Donation** — frivillig stödialog (PayPal / Ko-fi / Swish) med knappar i Hjälp-menyn, verktygsfältet, statusfältet, systemfältet och Inställningar.
- **Bättre kalender vid export** — stor kalender med måndag som första dag, ISO-veckonummer, helgmarkering, dagens datum i guld, snabbval (Idag/Imorgon/+7/+14/+30/Månadsslut) och förhandsvisning i klartext (”fredag 2 oktober 2026 · om 12 dagar”).
- Designputs: gulddetaljer, räknar-chips, kortytor och tydligt tom-läge i leverantörslistan.
- Export av leverantörer med fil-dialog (CSV/JSON).

### English
- **Suppliers tab fixed** — it was completely dead due to an `ImportError` (view helpers missing from the helpers module). If a view ever fails again, an error panel with **Try again** is shown instead of a silent dead tab.
- **Two languages** — the whole interface in Swedish and English, switchable instantly from the 🌐 Language menu or the Settings tab.
- **Donations** — voluntary support dialog (PayPal / Ko-fi / Swish) reachable from the Help menu, toolbar, status bar, system tray and Settings.
- **Better export calendar** — large calendar with Monday first, ISO week numbers, weekend highlighting, today in gold, quick picks (Today/Tomorrow/+7/+14/+30/End of month) and a plain-language preview (“Friday, 2 October 2026 · in 12 days”).
- Design polish: gold accents, count chips, card surfaces and a clear empty state in the supplier list.
- Supplier export with a save dialog (CSV/JSON).
