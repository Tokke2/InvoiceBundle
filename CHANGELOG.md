# Ändringslogg / Changelog

## Ej släppt / Unreleased

### Svenska
- **Bevakade mappar + original i betal-PDF:en** — lägg en bevakad mapp per leverantör i Import-fliken (t.ex. Pilkington, Direktglas): nya fakturafiler tolkas och registreras automatiskt, ofullständiga parkeras för granskning och samma fil importeras aldrig två gånger (innehålls-hash + dubblettkoll mot registret). Originalen kopieras till `data/attachments/<leverantör>/` och kan läggas efter betal-PDF:en (Inställningar → 📎 Inkludera originalfakturor) med avdelarsida per faktura.
- **Riktig Dashboard** — startsidan är inte längre en platshållare: fyra nyckeltalskort (ATT BETALA, FÖRFALLET, FÖRFALLER 7 DAGAR, LEVERANTÖRER) i marinblått/guld plus listan "Förfaller snart" med dubbelklick direkt till Fakturor. Samma statusregler och beloppsformat som Fakturor-fliken.

### English
- **Watched folders + originals in the payment PDF** — add one watched folder per supplier in the Import tab (e.g. Pilkington, Direktglas): new invoice files are parsed and registered automatically, incomplete ones are parked for review, and the same file is never imported twice (content hash + duplicate check against the register). Originals are copied to `data/attachments/<supplier>/` and can be appended after the payment PDF (Settings → 📎 Include original invoices) with a divider page per invoice.
- **A real Dashboard** — the start page is no longer a placeholder: four stat cards (TO PAY, OVERDUE, DUE IN 7 DAYS, SUPPLIERS) in navy/gold plus a "Due soon" list with double-click straight to Invoices. Same status rules and amount format as the Invoices tab.


## v1.0.0 — 2026-10-14 (uppdaterad / updated)

### Svenska
- **Ny appikon överallt** — faktura med guldbock på marinblått, samma motiv i `.ico` (aktivitetsfältet), `.png` (fönster, flikrubriker, PDF-export, Linux `.desktop`) och handgjord `.svg`. Donationsdialogen och loggfliken bär nu också ikonen, och vyernas rubriker är enhetliga (17 pt + 28 px-ikon) via nya `ui/design.py`.
- **Kodstädning** — gemensam designmodul i stället för kopierade ikonsökvägar i fyra vyer; oanvända importer och döda variabler borttagna (pyflakes: 28 → 0 fynd förutom en avsiktlig fallback-import).
- **Egen loggflik** (🪵 Logg, Ctrl+8) för felsökning: historik från `logs/app.log` även från föregående sessioner, felbanner med genväg till senaste felet, 🔖 markering + kopiera-efter-markering och ett **felsökningspaket** som kopieras med ett klick.
- **Multi-OS + autostart utan VBS** — appen körs på Windows, macOS och Linux. Ny autostart-metod i Inställningar-menyn: **Direkt** (standard, OS startar Python direkt — ingen VBS/startfil) eller **Startfil** (klassiska `start_hidden`-filen som väntar på disken, för portabla installationer). Windows = register/pythonw, Linux = XDG-autostart, macOS = LaunchAgent.

### English
- **New app icon everywhere** — invoice with a gold checkmark on navy, the same artwork in `.ico` (taskbar), `.png` (window, tab headers, PDF export, Linux `.desktop`) and a hand-made `.svg`. The donate dialog and Log tab now also carry the icon, and view headers are unified (17 pt + 28 px icon) via the new `ui/design.py`.
- **Code cleanup** — shared design module instead of copied icon paths in four views; unused imports and dead variables removed (pyflakes: 28 → 0 findings apart from one intentional fallback import).
- **Dedicated Log tab** (🪵 Log, Ctrl+8) for troubleshooting: history from `logs/app.log` including previous sessions, an error banner with a jump-to-latest-error shortcut, 🔖 markers with copy-after-marker, and a one-click **diagnostics bundle**.
- **Multi-OS + autostart without VBS** — the app runs on Windows, macOS and Linux. New autostart method choice in the Settings menu: **Direct** (default; the OS starts Python directly — no VBS/launcher file) or **Launcher file** (the classic `start_hidden` file that waits for the disk, for portable installs). Windows = registry/pythonw, Linux = XDG autostart, macOS = LaunchAgent.

Första officiella releasen, uppdaterad med allt nedan. / First official release, updated with everything below.

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
