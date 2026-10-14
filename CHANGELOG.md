# Ändringslogg / Changelog

## Ej släppt / Unreleased

### Svenska
- **Swish med äkta QR-kod** — donationsdialogen visar nu en QR-kod i Swishs officiella originalformat (`C<nummer>;<belopp>;<meddelande>;<mask>`, numret låst, belopp och meddelande redigerbara) till det riktiga numret **072-181 71 77**, så den kan skannas direkt i Swish-appen. Numret står som bildtext under koden och kan fortfarande kopieras. QR-biblioteket (`qrcode`) installeras automatiskt via ensure_packages; utan det visas kopieringsknappen som förr.
- **Procent i uppdateringsbalken** — nedladdningen visar nu % och MB (t.ex. "62 % · 0.9 MB / 1.5 MB") direkt i förloppsbalken, och installationsfasen visar riktig procent med filräknare ("Installerar … fil 24 av 48") i stället för en ändlös spinner som såg ut som en låsning.
- **Slå ihop markerade fakturor** — markera t.ex. 10 fakturor i Fakturor-fliken och klicka 🧮 Slå ihop markerade: du får totalsumman (krediter avdragna) och förfallodatumet från den faktura som förfaller först, med listan sorterad på förfallodatum, varning för fakturor utan datum, kopierbar sammanfattning — och export av just de markerade till betal-PDF där tidigaste förfallodatumet förifylls som betalningsdatum. Redan vid markering visar statusraden summa + tidigaste förfall.
- **Uppdateraren förbättrad** — appen kollar nu själv efter ny version i bakgrunden vid start (tyst, högst en gång per dygn, avstängbart i Inställningar-menyn) och frågar bara när det faktiskt finns en nyare build — så en gammal kopia kan inte längre vara igång ovetande. Dialogen fick återställning från senaste backupen (↩ i bak/) om en uppdatering skulle strula, och förloppsbalken visar nu även installationsfasen. Dialogen öppnas med resultatet ifyllt vid auto-kollen (ingen dubbel nätkoll).
- **Uppdatering i appen** — Hjälp → 🔄 Sök ny version … hämtar senaste releasen från GitHub, visar noteringarna och kan hämta + installera den med ett klick. Bara programfiler byts: data/, js/, ui/data/, settings.json, loggar och exporter rörs aldrig, och en backup sparas i bak/ innan något ersätts. Jämförelsen sker per commit, så även en uppdaterad v1.0.0-release hittas trots samma versionsnummer.
- **Bevakade mappar + original i betal-PDF:en** — lägg en bevakad mapp per leverantör i Import-fliken (t.ex. Pilkington, Direktglas): nya fakturafiler tolkas och registreras automatiskt, ofullständiga parkeras för granskning och samma fil importeras aldrig två gånger (innehålls-hash + dubblettkoll mot registret). Originalen kopieras till `data/attachments/<leverantör>/` och kan läggas efter betal-PDF:en (Inställningar → 📎 Inkludera originalfakturor) med avdelarsida per faktura.
- **Riktig Dashboard** — startsidan är inte längre en platshållare: fyra nyckeltalskort (ATT BETALA, FÖRFALLET, FÖRFALLER 7 DAGAR, LEVERANTÖRER) i marinblått/guld plus listan "Förfaller snart" med dubbelklick direkt till Fakturor. Samma statusregler och beloppsformat som Fakturor-fliken.

### English
- **Swish with a genuine QR code** — the donation dialog now shows a QR code in Swish's official original format (`C<number>;<amount>;<message>;<mask>`, number locked, amount and message editable) for the real number **072-181 71 77**, scannable directly in the Swish app. The number appears as a caption below the code and can still be copied. The `qrcode` library is installed automatically via ensure_packages; without it the copy button is shown as before.
- **Percentage in the update progress bar** — downloads now show % and MB (e.g. "62 % · 0.9 MB / 1.5 MB") right in the progress bar, and the install phase shows real percentage with a file counter ("Installing … file 24 of 48") instead of an endless spinner that looked like a freeze.
- **Combine selected invoices** — select e.g. 10 invoices in the Invoices tab and click 🧮 Combine selected: you get the total (credits deducted) and the due date of the earliest-due invoice, with the list sorted by due date, warnings for invoices without a date, a copyable summary — and export of exactly those invoices to a payment PDF with the earliest due date prefilled as the payment date. The status bar already shows the sum + earliest due while selecting.
- **Updater improved** — the app now checks for a new version silently in the background at startup (at most once a day, can be turned off in the Settings menu) and only asks when a newer build actually exists — an old copy can no longer keep running unnoticed. The dialog gained restore-from-latest-backup (↩ in bak/) in case an update misbehaves, and the progress bar now also shows the install phase. Auto-checks open the dialog pre-filled (no double network round-trip).
- **In-app updates** — Help → 🔄 Check for updates … fetches the latest release from GitHub, shows the notes and can download + install it in one click. Only program files are replaced: data/, js/, ui/data/, settings.json, logs and exports are never touched, and a backup is saved to bak/ before anything is replaced. Comparison is per commit, so an updated v1.0.0 release is found even with the same version number.
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
