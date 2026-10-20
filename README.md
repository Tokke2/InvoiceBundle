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
- Import av skannade fakturor (PDF/bild) med tolkning av belopp, OCR och datum.
- Exporterar en betallista som PDF med betalningsdatum och bankgiro.
  - Betalningsdatumet väljs **vid varje export** i en kalender med snabbval (Idag, +7, +14, +30 dagar, månadsslut) — och nollställs efteråt.
- Fyra teman (mörkt, ljust, auto, system), systemfältsikon, autostart och automatisk backup.
- All data lagras lokalt som JSON i programmappen (`data/`). Ingenting skickas över nätet.

## Språk

Gränssnittet finns på **svenska** (standard) och **engelska**.
Byt i menyn **🌐 Språk → Svenska / English** eller på fliken **Inställningar** — bytet gäller direkt, utan omstart, och sparas till nästa start.

## Plattformar

Appen körs på **Windows, macOS och Linux** (Python + PySide6). **Autostart** väljer du i Inställningar-menyn med två metoder: **Direkt** (standard — operativsystemet startar Python direkt, helt utan VBS/startfil; Windows: register + pythonw, Linux: XDG `.desktop`, macOS: LaunchAgent) eller **Startfil** (en `start_hidden`-fil i appmappen som väntar tills disken är redo — bra för portabla USB-installationer). Båda startar appen gömd i systemfältet med arbetsmappen satt till appmappen.

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
2. Saknas Python: kör `Installera senaste Python.bat` en gång. Den installerar senaste stabila Python på datorn.
3. Starta `main.pyw`, eller genvägen `Fakturabunten.lnk` som skapas vid första starten.

Saknade Python-paket (`PySide6`, `reportlab`, `pypdf`) hämtas automatiskt vid start, bara om de behövs.

Utvecklare startar med:

```bash
pip install -r requirements.txt
python main.py
```

## Användning i korthet

1. Skapa minst en leverantör på fliken **Leverantörer** (Ctrl+L).
2. Registrera fakturor på fliken **Fakturor** (Ctrl+N): fakturanummer + belopp (`+` = faktura, `−` = kreditfaktura).
3. Klicka **Exportera ALLA till PDF**, välj betalningsdatum i kalendern och bekräfta.
4. Tidigare exporter finns under **Exporthistorik** om något behöver återställas.

## Tester

```bash
pytest tests/              # eller utan pytest:
python tests/test_core.py
```

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
- Exports a payment list as PDF with payment date and bankgiro details.
  - The payment date is chosen **at every export** in a calendar with quick picks (Today, +7, +14, +30 days, end of month) — and reset afterwards.
- Four themes (dark, light, auto, system), system tray icon, autostart and automatic backups.
- All data is stored locally as JSON in the app folder (`data/`). Nothing is sent over the network.

## Language

The interface is available in **Swedish** (default) and **English**.
Switch via the **🌐 Language** menu or the **Settings** tab — the change applies instantly, needs no restart, and is remembered for the next launch.

## Platforms

The app runs on **Windows, macOS and Linux** (Python + PySide6). **Autostart** is chosen in the Settings menu with two methods: **Direct** (default — the operating system starts Python directly, with no VBS/launcher file at all; Windows: registry + pythonw, Linux: XDG `.desktop`, macOS: LaunchAgent) or **Launcher file** (a `start_hidden` file in the app folder that waits until the disk is ready — good for portable USB installs). Both start the app hidden in the system tray with the working folder set to the app folder.

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
2. If Python is missing: run `Installera senaste Python.bat` once. It installs the latest stable Python. *(Installer script name is in Swedish.)*
3. Start `main.pyw`, or the `Fakturabunten.lnk` shortcut created on first launch.

Missing Python packages (`PySide6`, `reportlab`, `pypdf`) are fetched automatically at startup, only if needed.

Developers start with:

```bash
pip install -r requirements.txt
python main.py
```

## Usage in short

1. Create at least one supplier on the **Suppliers** tab (Ctrl+L).
2. Register invoices on the **Invoices** tab (Ctrl+N): invoice number + amount (`+` = invoice, `−` = credit note).
3. Click **Export ALL to PDF**, pick the payment date in the calendar and confirm.
4. Previous exports are available under **Export history** if anything needs restoring.

## Tests

```bash
pytest tests/              # or without pytest:
python tests/test_core.py
```

## Licence

No open licence has been chosen. Free to use. Not free to copy, modify or resell. Donations are voluntary.

© 2026 Rickard Längkvist

---

Se [CHANGELOG.md](CHANGELOG.md) för versionshistorik. / See [CHANGELOG.md](CHANGELOG.md) for version history.
