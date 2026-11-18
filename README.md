# Fakturabunten / InvoiceBundle

<img src="brand/fakturabunten-logotyp.svg" alt="Fakturabunten" width="420">


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
- Mall-/leverantörsmatchning kan använda giltigt organisationsnummer eller exakt etiketterat BG/bankgiro; OCR-numret är frivilligt och behövs inte för matchning eller registrering. Appen sparar automatiskt verifierade fakturamallar direkt vid manuell matchning (upp till max 15 mallvarianter per leverantör, där den äldsta rensas ut när en 16:e läggs till) och lär fortlöpande av dina uttryckligt bekräftade matchningar, men automatisk leverantörskoppling kräver minst fem bekräftelser och ett återkommande, unikt kännetecken. Tvetydiga eller motstridiga träffar lämnas alltid för ditt val.
- Exporterar en betallista som PDF med betalningsdatum och bankgiro.
  - Betalningsdatumet väljs **vid varje export** i en kalender med snabbval (Idag, +7, +14, +30 dagar, månadsslut) — och nollställs efteråt.
  - Välj om PDF:en ska innehålla alla originalsidor, bara första PDF-sidan eller inga original; valet sparas och gäller även autoexport.
- Bevakade fakturamappar skannas rekursivt vid start och återkommande, även när filer lagts till medan appen varit stängd. Rotmappar och undermappar bevakas; nya/ändrade filer måste vara oförändrade i två sekunder innan de öppnas. Import-vyn visar senaste kontroll, filer som fortfarande skrivs, saknade mappar, läsfel och en tydlig progress bar vid både bevakad och manuell inläsning (samt avbrytknapp vid manuell filskanning). **Skanna nu / försök igen** prövar även väntande/parkerade filer om när mallar, leverantörer eller minne uppdaterats, och motstridiga organisationsnummer blockerar tysta gissningar även i leverantörskopplade mappar. Skanning och tolkning (PDF/OCR med sidtimeout och trådlås) körs helt i bakgrunden utan att frysa fönstret, och oförändrade original hashas bara en gång per filversion. Efter lyckad registrering flyttas originalet till `<bevakad mapp>/<fakturans år>/`; ofullständiga och osäkra filer ligger kvar för granskning. Saknat/ogiltigt fakturadatum ger en fråga om år vid import; Avbryt lämnar originalet kvar på källplatsen.
- Fyra teman (mörkt, ljust, auto, system), systemfältsikon, autostart och automatisk backup. **Krysset och minimera-knappen kan gömma appen till systemfältet** — båda beteendena slås på/av i Inställningar-menyn *eller* direkt i tray-menyn, och kryssrutorna hålls i synk. Saknas systemfältet (t.ex. ett Linux-skrivbord utan AppIndicator) stannar fönstret kvar i aktivitetsfältet och appen säger till i statusraden i stället för att försvinna.
- All data lagras lokalt som JSON i programmappen (`data/`). Ingenting skickas över nätet.

## Språk

Gränssnittet finns på **svenska** (standard) och **engelska**.
Byt i menyn **🌐 Språk → Svenska / English** eller på fliken **Inställningar** — bytet gäller direkt, utan omstart, och sparas till nästa start.

## Plattformar

Appen körs på **Windows, macOS och Linux** (Python + PySide6) med samma funktioner och samma gränssnitt. Varje normal start börjar minimerad i systemfältet; om systemfält saknas visas fönstret så att appen inte blir oåtkomlig.

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Systemfält | Aktivitetsfältets systemfält (färgad ikon) | Menyraden (monokrom **template-ikon** som OS:et färgar självt) | Statusfält via AppIndicator/SNI (färgad ikon) |
| Minimera/stäng till fältet | ✅ kryss + minimera | ✅ kryss + minimera | ✅ kryss + minimera |
| Autostart | Genväg med appikonen i Autostart-mappen | LaunchAgent (`launchctl bootstrap`, äldre `load` som reserv) | XDG `.desktop` med citerad `Exec`, `StartupWMClass` och appikon |
| Typsnitt | Segoe UI Variable / Segoe UI | SF Pro / Helvetica Neue | Inter / Noto Sans / Ubuntu / Cantarell |
| Öppna och skriva ut | `os.startfile`, `print` | `open`, `lpr` | `xdg-open`, `lp` |

**Autostart** väljer du i Inställningar-menyn med två metoder: **Direkt** (standard — Windows använder en ikonbärande genväg i Autostart-mappen, Linux XDG `.desktop`, macOS LaunchAgent) eller **Startfil** (en `start_hidden`-fil i appmappen som väntar tills disken är redo — bra för portabla USB-installationer). Båda behåller arbetsmappen satt till appmappen. Saknar Linux-skrivbordet AppIndicator-stöd (vanligt i ren GNOME) visas ingen tray-ikon — då stannar fönstret i aktivitetsfältet och statusraden förklarar varför.

## Logotyp och ikon

All grafik finns som **vektorgrafik (SVG)** i [`brand/`](brand/README.md): ikon, tryckversion med 5 mm bleed, monokrom ikon för menyraden samt liggande logotyp för ljus bakgrund, mörk bakgrund och svartvitt tryck. Filerna ligger **inuti programpaketet** (release-zipen) — de följer med varje nedladdning och uppdatering och behöver aldrig hämtas separat. Bokstäverna är omvandlade till banor (Poppins, SIL OFL), så filerna kräver inget installerat typsnitt och kan skalas hur stort som helst. Filerna i appens rot (`app_icon.svg/.png/.ico`, `app_icon_tray.png`) är byggda ur samma motiv.

## Gratis — med frivillig donation

Programmet är gratis att använda, både privat och kommersiellt. En donation krävs inte och låser inte upp något.

Vill du stödja utvecklingen öppnar du **Hjälp → 💖 Donationer…** (eller använder guldknappen i verktygsfältet, knappen i statusfältet, högerklick på flikraden, Om-dialogen eller fliken Inställningar). Dialogen visar snabbknappar, valfritt belopp, nyttokort, förtroendemärken och vanliga frågor direkt inne i appen utan separat webbsida. Mottagaruppgifterna är låsta och går inte att ändra:

- 💚 **Swish:** Swish-QR enligt Swish-standard i appens donationsruta (mottagaren är låst och numret visas aldrig i klartext)
- 💙 **PayPal:** https://paypal.me/Rickard3dPrint (direktknapp i appen, följer valt belopp)
- ☕ **Ko-fi:** https://ko-fi.com/tokke2 (direktknapp i appen för engångs- eller månadsstöd)

Betalningen sker via Swish, PayPal eller Ko-fi. Programmet ser inga betalningsuppgifter.

## Kom igång (Windows)

1. Lägg hela mappen där du vill, till exempel `D:\Program\Fakturabunten`. Sökvägen spelar ingen roll.
2. Dubbelklicka på **`Starta Fakturabunten.bat`**. Startfilen söker efter systeminstallerad Python, även utanför PATH. Finns Python startar appen utan att fråga om installation. Saknas Python erbjuder den att öppna Python.orgs sida för den senaste stabila versionen; du installerar själv och startar sedan filen igen. Hittas bara en gammal eller trasig Python visas ett fel i stället för ett installationserbjudande. Appen kräver en fungerande Python 3.10 eller nyare.
3. Appen använder en systeminstallerad Python (per användare eller dator), aldrig en kopia i appmappen. Den provar installerade tolkar med appens beroenden och Qt-runtime, sparar en fungerande sökväg/version i `data/python_runtime_selection.json` och återtestar valet vid senare starter. Den börjar minimerad i systemfältet; öppna den från tray-ikonen. Om ikonen inte syns direkt, kontrollera Windows dolda ikoner (`^`) vid klockan.

Saknade Python-paket (`PySide6`, `reportlab`, `pypdf`, `pytesseract`) hämtas automatiskt vid start, bara om de behövs. `pytesseract` är Python-gränssnittet; för OCR av skannade PDF:er och bilder krävs dessutom Tesseract-programmet (med svensk eller engelsk språkdata). Om OCR-motorn saknas visas en varning i Import — fakturan registreras inte tyst med påhittade uppgifter.

**Veckovis paketuppdatering:** appen kontrollerar måndag kl. 08 lokal tid och köar en uppdatering av `requirements.txt` tills appen har avslutats. Missas tiden köas den vid nästa start. På alla operativsystem används den aktiva Python-miljön: själva Python installeras, uppdateras eller tas inte bort av den nya veckokontrollen. Paket som uppdateras i en delad Python-miljö kan däremot påverka andra program som använder samma paket. Ingen virtuell miljö eller OS-schemalagd uppgift skapas. Status sparas i `data/python_update_state.json`. Obs: en Windows-worker som redan köats av en äldre version kan fortfarande uppdatera eller ta bort Python när den äldre appen stängs; filuppdateringen stoppar inte en redan startad process.

## Kom igång (macOS och Linux)

1. Lägg hela mappen där du vill. På **macOS** öppnar du `Starta Fakturabunten.command`. På **Linux** kör du `sh 'Starta Fakturabunten.sh'` i mappen, eller väljer Kör som program i filhanteraren.
2. Startfilen använder en system-Python om en sådan hittas och frågar då aldrig om Pythoninstallation. Bara om Python saknas erbjuds du att öppna den officiella nedladdningssidan; installera där och starta filen igen. En gammal eller trasig hittad Python ger ett fel utan installationserbjudande. På Linux kan distributionens pakethanterare ha en äldre version än den senaste på Python.org.
3. Appen behöver Python 3.10 eller nyare och hämtar saknade appberoenden vid behov. Den börjar minimerad i systemfältet; klicka på ikonen för att öppna fönstret. Om en uppackare har tagit bort körrättigheten på macOS, kör `chmod u+x 'Starta Fakturabunten.command'` en gång.

- **Linux:** systemfältet kräver AppIndicator/StatusNotifier-stöd (finns i KDE, Xfce, Cinnamon, MATE och GNOME med tillägget *AppIndicator and KStatusNotifierItem Support*). Saknas stödet visas inget fält — då stannar fönstret kvar i aktivitetsfältet och statusraden säger till. Filer öppnas med `xdg-open`, utskrift går via `lp` (CUPS). Autostart skrivs som `~/.config/autostart/Fakturabunten.desktop`.
- **macOS:** ikonen läggs i menyraden som en monokrom *template*-bild, så den följer ljust/mörkt läge automatiskt. Filer öppnas med `open`, utskrift går via `lpr`. Autostart läggs som en LaunchAgent i `~/Library/LaunchAgents` och laddas med `launchctl bootstrap` (äldre macOS: `load`). Första gången kan macOS fråga om åtkomst till mappen — godkänn det, annars kan appen inte läsa eller flytta fakturor.

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

Fakturabunten (InvoiceBundle) är gratis att installera och använda, både **privat och kommersiellt**, i hela världen. Se den övergripande licensfilen [`LICENSE`](LICENSE). Ändring, bearbetning och vidare spridning kräver särskilt tillstånd från rättighetshavaren (detta är inte en öppen källkodslicens). Tredjepartsberoenden och typsnittet Poppins (SIL OFL 1.1) omfattas av sina egna licenser. Donation är frivillig.

© 2026 Rickard Längkvist

---

# 🇬🇧 English

## What the app does

- Registers supplier invoices and credit notes.
- Supplier register with live search, favourites (★), payment terms and CSV/JSON export.
- Totals **Invoices (+)**, **Credits (−)** and **TO PAY**.
- Imports scanned invoices (PDF/image), reading amounts, OCR references and dates.
- Template/supplier matching can use a valid organization number or an exact, labelled BG/bankgiro; the invoice OCR reference is optional and is not required for matching or registration. The app saves verified invoice templates immediately upon manual matching (up to 15 saved template variants per supplier, evicting the oldest when a 16th is added) and keeps learning from your explicitly confirmed matches, but automatic supplier linking requires at least five confirmations and a recurring, unique identifier. Ambiguous or conflicting matches are always left for you to choose.
- Exports a payment list as PDF with payment date and bankgiro details.
  - The payment date is chosen **at every export** in a calendar with quick picks (Today, +7, +14, +30 days, end of month) — and reset afterwards.
  - Choose whether PDFs include every original page, only the first PDF page, or no originals; the saved choice also applies to automatic exports.
- Watched invoice folders are scanned recursively at startup and on a schedule, including files added while the app was closed. Root folders and subfolders are monitored; new/changed files must remain unchanged for two seconds before they are opened. The Import view shows the last check, files still being written, missing folders, read errors, and a clear progress bar for both watched and manual scanning (plus a Cancel button during manual file scans). **Scan now / retry** also re-evaluates parked/waiting items when templates, suppliers, or match memory change, and conflicting organization numbers guard against silent guesses even inside supplier-assigned folders. Scanning and parsing (PDF/OCR with page timeout and thread lock) run in the background without freezing the window, and unchanged originals are hashed only once per file version. After successful registration, originals move into `<watched folder>/<invoice year>/`; incomplete and uncertain files stay for review. If the invoice date is missing or invalid, import asks for an archive year; Cancel leaves the original at its source path.
- Four themes (dark, light, auto, system), system tray icon, autostart and automatic backups. **The close button and the minimize button can hide the app to the system tray** — both behaviours are switched in the Settings menu *or* directly in the tray menu, and the checkboxes stay in sync. If the desktop has no tray (e.g. Linux without AppIndicator) the window stays in the taskbar and the status line explains why, instead of disappearing.
- All data is stored locally as JSON in the app folder (`data/`). Nothing is sent over the network.

## Language

The interface is available in **Swedish** (default) and **English**.
Switch via the **🌐 Language** menu or the **Settings** tab — the change applies instantly, needs no restart, and is remembered for the next launch.

## Platforms

The app runs on **Windows, macOS and Linux** (Python + PySide6) with the same features and the same interface. Every normal launch starts minimized to the system tray; if no tray is available, the window stays visible so the app cannot become inaccessible.

| | Windows | macOS | Linux |
| --- | --- | --- | --- |
| System tray | Taskbar tray (colour icon) | Menu bar (**monochrome template icon**, tinted by the OS) | Status notifier via AppIndicator/SNI (colour icon) |
| Minimize/close to tray | ✅ close + minimize | ✅ close + minimize | ✅ close + minimize |
| Autostart | Icon-bearing shortcut in the Startup folder | LaunchAgent (`launchctl bootstrap`, `load` as fallback) | XDG `.desktop` with quoted `Exec`, `StartupWMClass` and app icon |
| Fonts | Segoe UI Variable / Segoe UI | SF Pro / Helvetica Neue | Inter / Noto Sans / Ubuntu / Cantarell |
| Open and print | `os.startfile`, `print` | `open`, `lpr` | `xdg-open`, `lp` |

**Autostart** is chosen in the Settings menu with two methods: **Direct** (default — Windows uses an icon-bearing shortcut in the Startup folder, Linux uses XDG `.desktop`, macOS uses a LaunchAgent) or **Launcher file** (a `start_hidden` file in the app folder that waits until the disk is ready — good for portable USB installs). Both keep the working folder set to the app folder. If a Linux desktop lacks AppIndicator support (common in plain GNOME) no tray icon appears — the window then stays in the taskbar and the status line explains why.

## Logo and icon

All artwork ships as **vector graphics (SVG)** in [`brand/`](brand/README.md): the icon, a print version with 5 mm bleed, a monochrome menu-bar icon, and a horizontal logo for light backgrounds, dark backgrounds and black-and-white print. The files live **inside the program package** (the release zip) — they come with every download and update and never have to be fetched separately. Letterforms are converted to outlines (Poppins, SIL OFL), so the files need no installed fonts and scale to any size. The files in the app root (`app_icon.svg/.png/.ico`, `app_icon_tray.png`) are built from the same artwork.

## Free — with a voluntary donation

The app is free to use for both private and commercial purposes. A donation is never required and unlocks nothing.

If you would like to support development, open **Help → 💖 Donations…** inside the app (or use the gold toolbar button, the status-bar button, right-clicking the tab bar, the About dialog, or the Settings tab). The dialog includes quick actions, optional amount chips, impact cards, trust badges, and collapsible FAQs directly inside the app with no separate webpage. Recipient details are locked inside the app and cannot be changed:

- 💚 **Swish:** Swish QR code following the Swish standard inside the app dialog (the recipient is locked and the number is never shown in plain text)
- 💙 **PayPal:** https://paypal.me/Rickard3dPrint (direct button in the app, carrying over any selected SEK amount)
- ☕ **Ko-fi:** https://ko-fi.com/tokke2 (direct button in the app for one-time or monthly support)

Payment takes place via Swish, PayPal or Ko-fi. The app never sees any payment details.

## Getting started (Windows)

1. Put the whole folder wherever you like, e.g. `D:\Program\InvoiceBundle`. The path does not matter.
2. Double-click **`Starta Fakturabunten.bat`**. The launcher looks for an installed system Python, including outside PATH. If Python is present, it starts the app without offering installation. Only when no Python is found does it offer to open Python.org's latest stable download page; install it yourself and start the file again. An old or broken detected Python produces an error rather than an installation offer. The app needs a working Python 3.10 or newer.
3. The app uses a system-installed interpreter (per-user or machine-wide), never a Python copy in the app folder. It tests installed interpreters against the app dependencies and Qt runtime, remembers a working path/version in `data/python_runtime_selection.json`, and retests it on later starts. The app starts minimized in the system tray; open it from the tray icon. If it is not visible immediately, check Windows' hidden tray icons (`^`) by the clock.

Missing Python packages (`PySide6`, `reportlab`, `pypdf`, `pytesseract`) are fetched automatically at startup, only if needed. `pytesseract` is the Python interface; OCR for scanned PDFs and images also requires the native Tesseract program and Swedish or English language data. If the OCR engine is missing, Import shows a warning instead of silently inventing invoice values.

**Weekly package update:** the app checks on Monday at 08:00 local time and queues a `requirements.txt` update until the app has exited. If the time was missed, it queues the update at the next launch. On every platform the active Python environment is used: the new weekly check does not install, update or remove the Python interpreter itself. Updated packages in a shared Python environment may nevertheless affect other programs using those packages. No virtual environment or OS scheduled task is created. Status is stored in `data/python_update_state.json`. Note: a Windows worker already queued by an older version can still update or remove Python when the old app exits; the file update does not stop an already running process.

## Getting started (macOS and Linux)

1. Put the whole folder wherever you like. On **macOS**, open `Starta Fakturabunten.command`. On **Linux**, run `sh 'Starta Fakturabunten.sh'` in that folder, or choose Run as a program in the file manager.
2. The launcher uses a system Python if found and never offers to install Python in that case. Only when no Python is found does it offer to open the official download page; install it there and start the file again. An old or broken detected Python produces an error without an installation offer. On Linux the distribution's package manager may provide a version older than the latest on Python.org.
3. The app needs Python 3.10 or newer and obtains missing app dependencies when needed. It starts minimized to the system tray; click the icon to open the window. If an extractor removed execute permission on macOS, run `chmod u+x 'Starta Fakturabunten.command'` once.

- **Linux:** the tray needs AppIndicator/StatusNotifier support (present in KDE, Xfce, Cinnamon, MATE, and GNOME with the *AppIndicator and KStatusNotifierItem Support* extension). Without it no tray appears — the window then stays in the taskbar and the status line says so. Files open with `xdg-open`, printing goes through `lp` (CUPS). Autostart is written to `~/.config/autostart/Fakturabunten.desktop`.
- **macOS:** the icon sits in the menu bar as a monochrome *template* image, so it follows light/dark mode automatically. Files open with `open`, printing goes through `lpr`. Autostart is a LaunchAgent in `~/Library/LaunchAgents`, loaded with `launchctl bootstrap` (`load` on older macOS). On first run macOS may ask for folder access — allow it, otherwise the app cannot read or move invoices.

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

Fakturabunten (InvoiceBundle) is free to install and use, for both **private and commercial** purposes, worldwide. See the overarching [`LICENSE`](LICENSE) file. Modification, adaptation, and redistribution require separate permission from the rights holder (this is not an open source licence). Third-party dependencies and the Poppins font (SIL OFL 1.1) remain subject to their respective licences. Donations are voluntary.

© 2026 Rickard Längkvist

---

Se [CHANGELOG.md](CHANGELOG.md) för versionshistorik. / See [CHANGELOG.md](CHANGELOG.md) for version history.
