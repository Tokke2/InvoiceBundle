# Fakturabunten / InvoiceBundle

<img src="app_icon.png" alt="Fakturabunten icon" width="112" align="right">


**Version 1.0.0** · Windows / Linux / macOS · Svenska & English

Lokalt program som räknar ihop leverantörsfakturor och kreditfakturor till en summa att betala — med leverantörsregister, förfallokoll och PDF-export. Ingen prenumeration. Ingen molntjänst. All data ligger i programmappen på din dator.

A local app that totals supplier invoices and credit notes into one amount to pay — with a supplier register, due-date tracking and PDF export. No subscription. No cloud service. All data stays in the app folder on your computer.

**© 2026 Rickard Längkvist**

---

# 🇸🇪 Svenska

## Vad programmet gör

- Registrerar leverantörsfakturor och kreditfakturor.
- Leverantörsregister med live-sökning, favoriter (★), betalvillkor och export till CSV/JSON.
- Räknar ihop **Fakturor (+)**, **Krediter (−)** och **ATT BETALA**.
- Import av skannade fakturor (PDF/bild) med tolkning av belopp, OCR-referens och datum.
- Mall-/leverantörsmatchning kan använda giltigt organisationsnummer eller exakt etiketterat BG/bankgiro; OCR-numret är frivilligt och behövs inte för matchning eller registrering. Appen lär fortlöpande av dina uttryckligt bekräftade matchningar, men automatisk koppling kräver minst fem bekräftelser och ett återkommande, unikt kännetecken. Tvetydiga eller motstridiga träffar lämnas alltid för ditt val.
- Exporterar en betallista som PDF med betalningsdatum och bankgiro.
  - Betalningsdatumet väljs **vid varje export** i en kalender med snabbval (Idag, +7, +14, +30 dagar, månadsslut) — och nollställs efteråt.
  - Välj om PDF:en ska innehålla alla originalsidor, bara första PDF-sidan eller inga original; valet sparas och gäller även autoexport.
- Bevakade fakturamappar skannas rekursivt vid start och återkommande, även när filer lagts till medan appen varit stängd. Rotmappar och undermappar bevakas; nya/ändrade filer måste vara oförändrade i två sekunder innan de öppnas. Import-vyn visar senaste kontroll, filer som fortfarande skrivs, saknade mappar och läsfel; **Skanna nu / försök igen** startar en ny kontroll direkt. Skanningen och tolkningen (PDF/OCR) körs i bakgrunden så att fönstret aldrig låser sig, och oförändrade original hashas bara en gång per filversion. Efter lyckad registrering flyttas originalet till `<bevakad mapp>/<fakturans år>/`; ofullständiga och osäkra filer ligger kvar för granskning. Saknat/ogiltigt fakturadatum ger en fråga om år vid import; Avbryt lämnar originalet kvar på källplatsen.
- Fyra teman (mörkt, ljust, auto, system), systemfältsikon, autostart och automatisk backup. Högerklicka på tray-ikonen för att bland annat öppna appmappen.
- All data lagras lokalt som JSON i programmappen (`data/`). Ingenting skickas över nätet.

## Språk

Gränssnittet finns på **svenska** (standard) och **engelska**.
Byt i menyn **🌐 Språk → Svenska / English** eller på fliken **Inställningar** — bytet gäller direkt, utan omstart, och sparas till nästa start.

## Plattformar

Appen körs på **Windows, macOS och Linux** (Python + PySide6). Varje normal start börjar minimerad i systemfältet; om systemfält saknas visas fönstret så att appen inte blir oåtkomlig. **Autostart** väljer du i Inställningar-menyn med två metoder: **Direkt** (standard — Windows använder en ikonbärande genväg i Autostart-mappen, Linux XDG `.desktop`, macOS LaunchAgent) eller **Startfil** (en `start_hidden`-fil i appmappen som väntar tills disken är redo — bra för portabla USB-installationer). Båda behåller arbetsmappen satt till appmappen.

## Gratis — med frivillig donation

Programmet är gratis att använda. En donation krävs inte och låser inte upp något.

Vill du stödja utvecklingen finns flera vägar i programmet under
**💖 Stöd Fakturabunten…** (Hjälp-menyn, guldknappen i verktygsfältet, knappen i statusfältet, högerklick på flikraden eller fliken Inställningar):

- 💙 **PayPal:** https://paypal.me/Rickard3dPrint
- ☕ **Ko-fi:** https://ko-fi.com/tokke2
- 📱 **Swish:** knappen i donationsrutan kopierar numret

Betalningen sker hos PayPal/Ko-fi. Programmet ser inga betalningsuppgifter.

## Kom igång (Windows)

1. Lägg hela mappen där du vill, till exempel `D:\Program\Fakturabunten`. Sökvägen spelar ingen roll.
2. Kör `Installera senaste Python.bat` för att kontrollera Python. Appen använder en systeminstallerad Python (per användare eller dator), aldrig en Python-kopia i appmappen. Den provar installerade tolkar i versionsordning med appens beroenden och Qt-runtime, väljer den första som fungerar och sparar sökväg/version i `data/python_runtime_selection.json`. Vid senare starter återtestas det sparade valet; nyare installerade tolkar provas också, och om valet inte längre fungerar väljs nästa godkända systemtolk. Installationsskriptet verifierar en ersättare innan en tidigare minorversion tas bort; om ingen kompatibel systemtolk finns installeras Python 3.14.8 på användarnivå. Okända installationstyper lämnas orörda.
3. Starta `main.pyw` eller genvägen `Fakturabunten.lnk`; appen börjar minimerad i systemfältet. Öppna den från tray-ikonen. Om ikonen inte syns direkt, kontrollera Windows dolda ikoner (`^`) vid klockan; Windows kan lägga den där.

Saknade Python-paket (`PySide6`, `reportlab`, `pypdf`, `pytesseract`) hämtas automatiskt vid start, bara om de behövs. `pytesseract` är Python-gränssnittet; för OCR av skannade PDF:er och bilder krävs dessutom Tesseract-programmet (med svensk eller engelsk språkdata). Om OCR-motorn saknas visas en varning i Import — fakturan registreras inte tyst med påhittade uppgifter.

**Veckovis uppdatering:** appen gör en kontroll måndag kl. 08 lokal tid. Om appen är öppen då köas uppdateringen och körs först när appen stängts; om den är stängd körs den vid nästa start. Python och paketen uppdateras i samma befintliga miljö — ingen virtuell miljö eller separat OS-schemalagd uppgift skapas. På Windows kan den igenkända Python.org-tolken och `requirements.txt` uppdateras. På macOS/Linux uppdateras paketen i appens aktiva Python; själva OS-/pakethanterarstyrda Python-tolken lämnas orörd. Veckostatus sparas i `data/python_update_state.json`.

Utvecklare startar med:

```bash
pip install -r requirements.txt
python main.py
```

## Användning i korthet

1. Skapa minst en leverantör på fliken **Leverantörer** (Ctrl+L). Använder leverantören fakturanumret som OCR-nummer markerar du **OCR-numret är samma som fakturanumret** – då fylls ett tomt OCR-fält automatiskt med fakturanumret vid import och registrering.
2. Registrera fakturor på fliken **Fakturor** (Ctrl+N): fakturanummer + belopp (`+` = faktura, `−` = kreditfaktura). Du kan lämna leverantörsfiltret överst tomt och välja leverantör i dialogen **Ny faktura**.
3. Välj vid export om originalen ska bifogas med alla sidor, bara första sidan eller inte alls; klicka **Exportera ALLA till PDF**, välj betalningsdatum i kalendern och bekräfta.
4. Tidigare exporter finns under **Exporthistorik** om något behöver återställas.

## Tester

```bash
pytest tests/              # eller utan pytest:
python tests/test_core.py
```

## Loggar

Allt som appen skriver hamnar i `<appmapp>/logs/`: `app.log` (huvudlogg), `felsamling.log` (alla fel på ett ställe, utan dubbletter) och autostartloggen. Felsamlingen visar samma fel en gång även om det både speglats direkt och skördats ur äldre loggar; status och antal träffar finns i `logs/felstatus.json`.

## Licens

Ingen öppen licens är vald. Fritt att använda. Inte fritt att kopiera, ändra eller sälja vidare. Donation är frivillig.

© 2026 Rickard Längkvist

---

# 🇬🇧 English

## What the app does

- Registers supplier invoices and credit notes.
- Supplier register with live search, favourites (★), payment terms and CSV/JSON export.
- Totals **Invoices (+)**, **Credits (−)** and **TO PAY**.
- Imports scanned invoices (PDF/image), reading amounts, OCR references and dates.
- Template/supplier matching can use a valid organization number or an exact, labelled BG/bankgiro; the invoice OCR reference is optional and is not required for matching or registration. The app keeps learning from your explicitly confirmed matches, but automatic linking requires at least five confirmations and a recurring, unique identifier. Ambiguous or conflicting matches are always left for you to choose.
- Exports a payment list as PDF with payment date and bankgiro details.
  - The payment date is chosen **at every export** in a calendar with quick picks (Today, +7, +14, +30 days, end of month) — and reset afterwards.
  - Choose whether PDFs include every original page, only the first PDF page, or no originals; the saved choice also applies to automatic exports.
- Watched invoice folders are scanned recursively at startup and on a schedule, including files added while the app was closed. Root folders and subfolders are monitored; new/changed files must remain unchanged for two seconds before they are opened. The Import view shows the last check, files still being written, missing folders and read errors; **Scan now / retry** starts an immediate rescan. Scanning and parsing (PDF/OCR) run in the background so the window never freezes, and unchanged originals are hashed only once per file version. After successful registration, originals move into `<watched folder>/<invoice year>/`; incomplete and uncertain files stay for review. If the invoice date is missing or invalid, import asks for an archive year; Cancel leaves the original at its source path.
- Four themes (dark, light, auto, system), system tray icon, autostart and automatic backups. Right-click the tray icon for options including opening the app folder.
- All data is stored locally as JSON in the app folder (`data/`). Nothing is sent over the network.

## Language

The interface is available in **Swedish** (default) and **English**.
Switch via the **🌐 Language** menu or the **Settings** tab — the change applies instantly, needs no restart, and is remembered for the next launch.

## Platforms

The app runs on **Windows, macOS and Linux** (Python + PySide6). Every normal launch starts minimized to the system tray; if no tray is available, the window stays visible so the app cannot become inaccessible. **Autostart** is chosen in the Settings menu with two methods: **Direct** (default — Windows uses an icon-bearing shortcut in the Startup folder, Linux uses XDG `.desktop`, macOS uses a LaunchAgent) or **Launcher file** (a `start_hidden` file in the app folder that waits until the disk is ready — good for portable USB installs). Both keep the working folder set to the app folder.

## Free — with a voluntary donation

The app is free to use. A donation is never required and unlocks nothing.

If you would like to support development, use
**💖 Support InvoiceBundle…** inside the app (Help menu, the gold toolbar button, the status-bar button, right-clicking the tab bar, or the Settings tab):

- 💙 **PayPal:** https://paypal.me/Rickard3dPrint
- ☕ **Ko-fi:** https://ko-fi.com/tokke2
- 📱 **Swish:** the button in the donation dialog copies the number

Payment takes place at PayPal/Ko-fi. The app never sees any payment details.

## Getting started (Windows)

1. Put the whole folder wherever you like, e.g. `D:\Program\InvoiceBundle`. The path does not matter.
2. Run `Installera senaste Python.bat` to check Python. The app uses a system-installed interpreter (per-user or machine-wide), never a Python copy inside the app folder. It probes installed interpreters in version order against the app dependencies and Qt runtime, selects the first working one, and remembers its path/version in `data/python_runtime_selection.json`. On later starts it retests the saved choice and also tests newly installed newer interpreters; if the saved choice stops working, it selects the next passing system interpreter. The installer verifies a replacement before removing an older minor version; if no compatible system interpreter exists, it installs Python 3.14.8 per-user. Unknown installation types are left untouched. *(Installer script name is in Swedish.)*
3. Start `main.pyw` or the `Fakturabunten.lnk` shortcut; the app starts minimized in the system tray. Open it from the tray icon. If it is not immediately visible, check Windows' hidden tray icons (`^`) by the clock; Windows may place it there.

Missing Python packages (`PySide6`, `reportlab`, `pypdf`, `pytesseract`) are fetched automatically at startup, only if needed. `pytesseract` is the Python interface; OCR for scanned PDFs and images also requires the native Tesseract program and Swedish or English language data. If the OCR engine is missing, Import shows a warning instead of silently inventing invoice values.

**Weekly update:** the app checks on Monday at 08:00 local time. If the app is open then, it queues the update and waits until the app closes; if it is closed, the update runs at the next launch. Python and packages stay in the same existing environment—no virtual environment or separate OS scheduled task is created. On Windows, the recognized Python.org interpreter and `requirements.txt` can be updated. On macOS/Linux, packages are updated in the app's active Python; the OS/package-manager-managed interpreter is left untouched. Weekly status is stored in `data/python_update_state.json`.

Developers start with:

```bash
pip install -r requirements.txt
python main.py
```

## Usage in short

1. Create at least one supplier on the **Suppliers** tab (Ctrl+L). If the supplier uses the invoice number as its OCR number, tick **The OCR number is the same as the invoice number**; an empty OCR field is then filled with the invoice number during import and registration.
2. Register invoices on the **Invoices** tab (Ctrl+N): invoice number + amount (`+` = invoice, `−` = credit note). Leave the top supplier filter blank if you want; choose the supplier in the **New Invoice** dialog.
3. Choose whether originals should include all pages, only the first page, or none; click **Export ALL to PDF**, pick the payment date in the calendar and confirm.
4. Previous exports are available under **Export history** if anything needs restoring.

## Tests

```bash
pytest tests/              # or without pytest:
python tests/test_core.py
```

## Logs

Everything the app writes ends up in `<app folder>/logs/`: `app.log` (main log), `felsamling.log` (all errors in one place, without duplicates) and the autostart log. The error journal lists a given error once even if it was both mirrored directly and harvested from older logs; status and hit counts are kept in `logs/felstatus.json`.

## Licence

No open licence has been chosen. Free to use. Not free to copy, modify or resell. Donations are voluntary.

© 2026 Rickard Längkvist

---

Se [CHANGELOG.md](CHANGELOG.md) för versionshistorik. / See [CHANGELOG.md](CHANGELOG.md) for version history.
