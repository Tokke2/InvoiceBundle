# -*- coding: utf-8 -*-
"""
Fakturabunten — språkmodul (svenska / engelska)
================================================
Hela appen finns på svenska (standard) och engelska.

* Språket sparas i settings.json (``"language": "sv" | "en"``) och
  byts direkt i menyn 🌐 Språk — ingen omstart behövs.
* Moduler hämtar texter med ``tr("nyckel")``. Dialoger som byggs
  vid öppning (Donate, Om, Leverantör …) får automatiskt aktuellt
  språk; fasta vyer implementerar ``retranslate()`` som
  MainWindow anropar vid språkbyte.
* Saknas en översättning faller texten tillbaka på svenska —
  aldrig på en rå nyckel mitt i GUI:t (nyckeln loggas i stället).

Inga Qt-beroenden: modulen kan importeras i tester och i ren
logik. GUI:t kopplar lyssnare med ``on_language_changed()``.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger("i18n")

#: Språk som stöds, i menyordning.
LANGUAGES: tuple[str, ...] = ("sv", "en")

#: Mänskliga namn (visas i språkmenyn, alltid på eget språk).
LANGUAGE_NAMES: dict[str, str] = {"sv": "Svenska", "en": "English"}

_current: str = "sv"
_listeners: list[Callable[[str], None]] = []


# ═════════════════════════════════════════════════════════════════════
#  ÖVERSÄTTNINGAR   nyckel → {sv, en}
# ═════════════════════════════════════════════════════════════════════

_STRINGS: dict[str, dict[str, str]] = {
    # ── App / gemensamt ──────────────────────────────────────────────
    "app.name": {"sv": "Fakturabunten", "en": "InvoiceBundle"},
    "common.close": {"sv": "Stäng", "en": "Close"},
    "common.cancel": {"sv": "Avbryt", "en": "Cancel"},
    "common.save": {"sv": "Spara", "en": "Save"},
    "common.add": {"sv": "Lägg till", "en": "Add"},
    "common.edit": {"sv": "Redigera", "en": "Edit"},
    "common.delete": {"sv": "Ta bort", "en": "Delete"},
    "common.duplicate": {"sv": "Duplicera", "en": "Duplicate"},
    "common.export": {"sv": "Exportera", "en": "Export"},
    "common.refresh": {"sv": "Uppdatera", "en": "Refresh"},
    "common.ready": {"sv": "Redo", "en": "Ready"},

    # ── Flikar ───────────────────────────────────────────────────────
    "tab.dashboard": {"sv": "🏠  Dashboard", "en": "🏠  Dashboard"},
    "tab.invoices": {"sv": "🧾  Fakturor", "en": "🧾  Invoices"},
    "tab.suppliers": {"sv": "🏢  Leverantörer", "en": "🏢  Suppliers"},
    "tab.payments": {"sv": "💳  Betalningar", "en": "💳  Payments"},
    "tab.import_tab": {"sv": "📥  Import", "en": "📥  Import"},
    "tab.reports": {"sv": "📊  Rapporter", "en": "📊  Reports"},
    "tab.settings_tab": {"sv": "⚙️  Inställningar", "en": "⚙️  Settings"},
    "tab.dashboard.sub": {"sv": "Översikt och nyckeltal", "en": "Overview and key figures"},
    "tab.invoices.sub": {"sv": "Hantera inkommande fakturor", "en": "Manage incoming invoices"},
    "tab.suppliers.sub": {"sv": "Leverantörsregister", "en": "Supplier register"},
    "tab.payments.sub": {"sv": "Betalbatcher och betalhistorik", "en": "Payment batches and history"},
    "tab.import_tab.sub": {"sv": "Importera fakturor via PDF / e-post", "en": "Import invoices via PDF / e-mail"},
    "tab.reports.sub": {"sv": "Månads- och leverantörsrapporter", "en": "Monthly and supplier reports"},
    "tab.settings_tab.sub": {"sv": "Program- och företagsinställningar", "en": "App and company settings"},

    # ── Menyer ───────────────────────────────────────────────────────
    "menu.file": {"sv": "&Arkiv", "en": "&File"},
    "menu.view": {"sv": "&Visa", "en": "&View"},
    "menu.theme": {"sv": "&Tema", "en": "&Theme"},
    "menu.language": {"sv": "🌐  &Språk", "en": "🌐  &Language"},
    "menu.settings": {"sv": "&Inställningar", "en": "&Settings"},
    "menu.help": {"sv": "&Hjälp", "en": "&Help"},
    "menu.new_supplier": {"sv": "🏢  Ny leverantör", "en": "🏢  New supplier"},
    "menu.new_invoice": {"sv": "🧾  Ny faktura", "en": "🧾  New invoice"},
    "menu.backup_now": {"sv": "💾  Skapa backup nu", "en": "💾  Create backup now"},
    "menu.open_exports": {"sv": "📁  Öppna exportmapp", "en": "📁  Open export folder"},
    "menu.open_log": {"sv": "📋  Öppna loggfil", "en": "📋  Open log file"},
    "menu.minimize_tray": {"sv": "🙈  Minimera till systemfältet", "en": "🙈  Minimize to system tray"},
    "menu.quit": {"sv": "❌  Avsluta programmet helt", "en": "❌  Quit completely"},
    "menu.show_all_tabs": {"sv": "👁  Visa alla flikar", "en": "👁  Show all tabs"},
    "menu.hide_tab": {"sv": "🙈  Dölj denna flik", "en": "🙈  Hide this tab"},
    "menu.show_hidden": {"sv": "👁  Visa dold flik …", "en": "👁  Show hidden tab …"},
    "menu.theme_dark": {"sv": "🌙  Mörkt", "en": "🌙  Dark"},
    "menu.theme_light": {"sv": "☀️  Ljust", "en": "☀️  Light"},
    "menu.theme_auto": {"sv": "🔄  Auto (tidbaserat)", "en": "🔄  Auto (time-based)"},
    "menu.theme_system": {"sv": "💻  System", "en": "💻  System"},
    "menu.autostart": {"sv": "🚀  Starta med operativsystemet", "en": "🚀  Start with operating system"},
    "menu.close_to_tray": {"sv": "🙈  Stäng till systemfältet (kryss-knappen)", "en": "🙈  Close to system tray (X button)"},
    "menu.trace": {"sv": "🔬  Logga varje tryck (TRACE-nivå)", "en": "🔬  Log every click (TRACE level)"},
    "menu.clean_cache": {"sv": "🧹  Töm cache vid avslut (Smart Cache)", "en": "🧹  Clear cache on exit (Smart Cache)"},
    "menu.about": {"sv": "ℹ️  Om programmet", "en": "ℹ️  About"},
    "menu.donate": {"sv": "💖  Stöd Fakturabunten…", "en": "💖  Support InvoiceBundle…"},
    "menu.diagnostics": {"sv": "🩺  Kopiera diagnostik", "en": "🩺  Copy diagnostics"},
    "menu.language_changed": {"sv": "🌐  Språk: Svenska", "en": "🌐  Language: English"},

    # ── Verktygsfält / status ────────────────────────────────────────
    "toolbar.new_supplier": {"sv": "🏢  Ny leverantör", "en": "🏢  New supplier"},
    "toolbar.new_invoice": {"sv": "🧾  Ny faktura", "en": "🧾  New invoice"},
    "toolbar.refresh": {"sv": "🔄  Uppdatera", "en": "🔄  Refresh"},
    "toolbar.backup": {"sv": "💾  Backup", "en": "💾  Backup"},
    "toolbar.exports": {"sv": "📁  Exporter", "en": "📁  Exports"},
    "toolbar.dark": {"sv": "🌙  Mörkt", "en": "🌙  Dark"},
    "toolbar.light": {"sv": "☀️  Ljust", "en": "☀️  Light"},
    "toolbar.minimize": {"sv": "🙈  Minimera", "en": "🙈  Minimize"},
    "toolbar.quit": {"sv": "❌  Avsluta", "en": "❌  Quit"},
    "toolbar.donate_tip": {"sv": "Fakturabunten är gratis. Stöd utvecklingen med en frivillig donation.", "en": "InvoiceBundle is free. Support development with a voluntary donation."},
    "status.donate": {"sv": "💖  Stöd", "en": "💖  Support"},

    # ── Inställningsfliken ───────────────────────────────────────────
    "settings.title": {"sv": "⚙️  Programinställningar", "en": "⚙️  Settings"},
    "settings.shortcuts": {"sv": "⌨️  Kortkommandon (sparas i shortcuts.json)", "en": "⌨️  Keyboard shortcuts (saved in shortcuts.json)"},
    "settings.save_shortcuts": {"sv": "💾  Spara kortkommandon", "en": "💾  Save shortcuts"},
    "settings.reset_shortcuts": {"sv": "↩️  Återställ standard", "en": "↩️  Reset to defaults"},
    "settings.shortcuts_hint": {"sv": "Klicka i fältet och tryck önskad tangentkombination. Tomt fält = ingen tangent.", "en": "Click a field and press the desired key combination. Empty = no shortcut."},
    "settings.plugins": {"sv": "🧩  Plugins (3-strikes-recovery)", "en": "🧩  Plugins (3-strikes recovery)"},
    "settings.reenable_plugins": {"sv": "♻️  Återställ avaktiverade plugins", "en": "♻️  Re-enable disabled plugins"},
    "settings.language": {"sv": "🌐  Språk / Language", "en": "🌐  Language / Språk"},
    "settings.language_hint": {"sv": "Byts direkt — ingen omstart behövs.", "en": "Applied instantly — no restart needed."},
    "settings.donate_group": {"sv": "💖  Stöd Fakturabunten (frivilligt)", "en": "💖  Support InvoiceBundle (voluntary)"},
    "settings.donate_text": {"sv": "Programmet är gratis och utan reklam. En donation hjälper utveckling och underhåll — men appen fungerar exakt lika bra utan.", "en": "The app is free with no ads. A donation helps development and maintenance — but the app works exactly the same without one."},
    "settings.donate_open": {"sv": "💖  Donationsalternativ …", "en": "💖  Donation options …"},
    "settings.note": {"sv": "Övriga inställningar (tema, autostart, stäng till tray, visa/dölj flikar, logga varje tryck/TRACE, töm cache vid avslut) finns i menyerna ovan. Alla data lagras lokalt i JSON-filer i appmappen.", "en": "Other settings (theme, autostart, close to tray, show/hide tabs, TRACE logging, clear cache on exit) are in the menus above. All data is stored locally in JSON files in the app folder."},

    # ── Vy-fel (när en flik inte kan laddas) ──────────────────────────
    "view.load_failed_title": {"sv": "⚠  Vyn kunde inte laddas", "en": "⚠  The view could not be loaded"},
    "view.load_failed_body": {"sv": "Fliken är inte trasig data — programmet kunde bara inte starta vyn.\nFelet nedan kan klistras in i en felrapport.", "en": "Your data is not broken — the app just could not start this view.\nThe error below can be pasted into a bug report."},
    "view.retry": {"sv": "🔄  Försök igen", "en": "🔄  Try again"},

    # ── Leverantörer ─────────────────────────────────────────────────
    "suppliers.title": {"sv": "🏢  Leverantörer", "en": "🏢  Suppliers"},
    "suppliers.search_ph": {"sv": "🔍  Sök namn, org.nr, e-post, kontakt …", "en": "🔍  Search name, org no., e-mail, contact …"},
    "suppliers.new": {"sv": "➕  Ny leverantör", "en": "➕  New supplier"},
    "suppliers.edit": {"sv": "✏️  Redigera", "en": "✏️  Edit"},
    "suppliers.duplicate": {"sv": "📋  Duplicera", "en": "📋  Duplicate"},
    "suppliers.delete": {"sv": "🗑  Ta bort", "en": "🗑  Delete"},
    "suppliers.export": {"sv": "📄  Exportera", "en": "📄  Export"},
    "suppliers.count": {"sv": "Leverantörer: {n}", "en": "Suppliers: {n}"},
    "suppliers.count_of": {"sv": "Leverantörer: {shown} av {total}", "en": "Suppliers: {shown} of {total}"},
    "suppliers.empty_title": {"sv": "Inga leverantörer ännu", "en": "No suppliers yet"},
    "suppliers.empty_body": {"sv": "Klicka på ”➕  Ny leverantör” för att lägga till den första.\nFakturor kan inte registreras förrän minst en leverantör finns.", "en": "Click “➕  New supplier” to add the first one.\nInvoices cannot be registered until at least one supplier exists."},
    "suppliers.empty_search": {"sv": "Ingen leverantör matchar sökningen.", "en": "No supplier matches your search."},
    "supplier.columns": {"sv": "Namn|Org.nr|Bankgiro|Plusgiro|IBAN|BIC|Villkor|Kontakt|E-post|Telefon|Adress|Notering", "en": "Name|Org no.|Bankgiro|Plusgiro|IBAN|BIC|Terms|Contact|E-mail|Phone|Address|Note"},
    "supplier.new_title": {"sv": "Ny leverantör", "en": "New supplier"},
    "supplier.edit_title": {"sv": "Redigera leverantör", "en": "Edit supplier"},
    "supplier.name": {"sv": "Namn *:", "en": "Name *:"},
    "supplier.org": {"sv": "Org.nummer:", "en": "Org number:"},
    "supplier.required_ph": {"sv": "Obligatoriskt", "en": "Required"},
    "supplier.favorite": {"sv": "⭐  Favorit (hamnar överst i fakturavyn)", "en": "⭐  Favourite (shown first in the invoice view)"},
    "supplier.terms_days": {"sv": "  dagar", "en": "  days"},
    "supplier.name_required": {"sv": "Namn är obligatoriskt.", "en": "Name is required."},
    "supplier.validation": {"sv": "Validering", "en": "Validation"},
    "supplier.duplicate_title": {"sv": "Möjlig dublett", "en": "Possible duplicate"},
    "supplier.duplicate_body": {"sv": "'{name}' finns redan.\nLägg till ändå?", "en": "'{name}' already exists.\nAdd anyway?"},
    "supplier.delete_title": {"sv": "Ta bort leverantör", "en": "Delete supplier"},
    "supplier.delete_body": {"sv": "Ta bort '{name}'?\nKan inte ångras.", "en": "Delete '{name}'?\nThis cannot be undone."},
    "supplier.saved": {"sv": "✅  Leverantör '{name}' sparad.", "en": "✅  Supplier '{name}' saved."},
    "supplier.updated": {"sv": "✅  Leverantör '{name}' uppdaterad.", "en": "✅  Supplier '{name}' updated."},
    "supplier.deleted": {"sv": "🗑  Leverantör '{name}' borttagen.", "en": "🗑  Supplier '{name}' deleted."},
    "supplier.export_none": {"sv": "Inga leverantörer att exportera.", "en": "No suppliers to export."},
    "supplier.export_done": {"sv": "✅  {n} leverantörer exporterade.", "en": "✅  Exported {n} suppliers."},

    # ── Fakturor (vyns krom — datavärden översätts inte) ─────────────
    "invoices.title": {"sv": "🧾  Registrerade leverantörsfakturor", "en": "🧾  Registered supplier invoices"},
    "invoices.choose_supplier": {"sv": "🏢  Välj leverantör:", "en": "🏢  Choose supplier:"},
    "invoices.choose_ph": {"sv": "— välj leverantör —", "en": "— choose supplier —"},
    "invoices.search_ph": {"sv": "🔍  Sök fakturanummer, leverantör, OCR, referens …", "en": "🔍  Search invoice number, supplier, OCR, reference …"},
    "invoices.add": {"sv": "➕  Registrera faktura", "en": "➕  Register invoice"},
    "invoices.edit": {"sv": "✏️  Redigera", "en": "✏️  Edit"},
    "invoices.delete": {"sv": "🗑  Ta bort", "en": "🗑  Delete"},
    "invoices.duplicate": {"sv": "📋  Duplicera", "en": "📋  Duplicate"},
    "invoices.mark_paid": {"sv": "✅  Markera betald", "en": "✅  Mark paid"},
    "invoices.export_all": {"sv": "📄  Exportera ALLA till PDF", "en": "📄  Export ALL to PDF"},
    "invoices.history": {"sv": "📚  Exporthistorik", "en": "📚  Export history"},
    "invoices.open_export_folder": {"sv": "📂  Öppna exportmapp", "en": "📂  Open export folder"},
    "invoices.card_invoices": {"sv": "Fakturor  +", "en": "Invoices  +"},
    "invoices.card_credits": {"sv": "Krediter  −", "en": "Credits  −"},
    "invoices.card_total": {"sv": "ATT BETALA", "en": "TO PAY"},
    "invoices.all_types": {"sv": "Alla typer", "en": "All types"},
    "invoices.active_only": {"sv": "Aktiva (ej arkiv)", "en": "Active (not archived)"},
    "invoices.all_statuses": {"sv": "Alla statusar", "en": "All statuses"},
    "invoices.all_suppliers": {"sv": "Alla leverantörer", "en": "All suppliers"},
    "invoices.columns": {"sv": "Typ|Leverantör|Fakturanr|OCR|Datum|Förfaller|Betaldatum|Belopp|Valuta|Status|Kategori|Referens|Notering", "en": "Type|Supplier|Invoice no.|OCR|Date|Due|Payment date|Amount|Currency|Status|Category|Reference|Note"},

    # ── Import (skannade fakturor) ───────────────────────────────────
    "scan.title": {"sv": "📥  Importera skannade fakturor", "en": "📥  Import scanned invoices"},
    "scan.info": {"sv": "Läs in PDF eller bild (skannad faktura), kontrollera vad som tolkades och bekräfta.\nInget registreras förrän du klickar Skapa faktura — appens summor räknas som vanligt.", "en": "Load a PDF or image (scanned invoice), check what was read and confirm.\nNothing is registered until you click Create invoices — totals are calculated as usual."},
    "scan.step1": {"sv": "1.  Välj fakturafiler", "en": "1.  Choose invoice files"},
    "scan.pick": {"sv": "📂  Välj filer …", "en": "📂  Choose files …"},
    "scan.clear": {"sv": "🗑  Rensa lista", "en": "🗑  Clear list"},
    "scan.no_files": {"sv": "Inga filer valda", "en": "No files chosen"},
    "scan.scan": {"sv": "🔍  Läs in och tolka", "en": "🔍  Read and interpret"},
    "scan.step2": {"sv": "2.  … eller klistra in fakturatext (fallback)", "en": "2.  … or paste invoice text (fallback)"},
    "scan.parse": {"sv": "🧠  Tolka texten", "en": "🧠  Interpret the text"},
    "scan.auto_open": {"sv": "Öppna fakturadialogen direkt", "en": "Open the invoice dialog directly"},
    "scan.step3": {"sv": "3.  Tolkade fakturor  (dubbelklicka för att rätta)", "en": "3.  Interpreted invoices  (double-click to correct)"},
    "scan.create": {"sv": "✅  Skapa fakturor (markerade)", "en": "✅  Create invoices (selected)"},
    "scan.open_dialog": {"sv": "✏️  Öppna i fakturadialogen", "en": "✏️  Open in invoice dialog"},
    "scan.remove_row": {"sv": "🗑  Ta bort rad", "en": "🗑  Remove row"},

    # ── Donation ─────────────────────────────────────────────────────
    "donate.title": {"sv": "💖 Stöd Fakturabunten", "en": "💖 Support InvoiceBundle"},
    "donate.window_title": {"sv": "Fakturabunten — Stöd projektet", "en": "InvoiceBundle — Support the project"},
    "donate.body_html": {
        "sv": "<p><b>Fakturabunten är gratis och utan reklam.</b> Om programmet hjälper dig i vardagen är en donation ett frivilligt tack som hjälper mig att fortsätta utveckla och underhålla det.</p><ul><li>Ingen reklam, ingen inloggning, inga prenumerationer.</li><li>Donationer går direkt till utveckling och underhåll.</li><li>Appen fungerar exakt lika bra utan donation.</li></ul><p style='color:#8a8a9e;font-size:11px'>Betalningen sker hos PayPal, Ko-fi eller Swish. Fakturabunten ser inga betalningsuppgifter.</p>",
        "en": "<p><b>InvoiceBundle is free and ad-free.</b> If the app helps you in everyday life, a donation is a voluntary thank-you that helps me keep developing and maintaining it.</p><ul><li>No ads, no sign-up, no subscriptions.</li><li>Donations go directly to development and maintenance.</li><li>The app works exactly the same without a donation.</li></ul><p style='color:#8a8a9e;font-size:11px'>Payment takes place at PayPal, Ko-fi or Swish. InvoiceBundle never sees any payment details.</p>",
    },
    "donate.paypal": {"sv": "💙 Donera via PayPal", "en": "💙 Donate with PayPal"},
    "donate.kofi": {"sv": "☕ Bjud på en kaffe (Ko-fi)", "en": "☕ Buy me a coffee (Ko-fi)"},
    "donate.swish": {"sv": "📱 Kopiera Swish-nummer", "en": "📱 Copy Swish number"},
    "donate.swish_copied": {"sv": "💙  Swish-nummer kopierat: {number}", "en": "💙  Swish number copied: {number}"},
    "donate.open_failed": {"sv": "Kunde inte öppna länken — adressen finns i knappens verktygstips.", "en": "Could not open the link — the address is in the button tooltip."},

    # ── Om-dialogen ──────────────────────────────────────────────────
    "about.title": {"sv": "Om {app}", "en": "About {app}"},
    "about.donate_btn": {"sv": "💖  Stöd projektet", "en": "💖  Support the project"},
    "about.close": {"sv": "✖  Stäng", "en": "✖  Close"},

    "about.body_html": {
        "sv": "<h2 style='color:#58a6ff'>{app}</h2><p><b>Version {version}</b> · Modern lokal fakturahantering för Windows, Linux och macOS.</p><p><b>© {year} Rickard Längkvist</b></p><hr><h3>Vad programmet gör</h3><p>Registrerar leverantörsfakturor och kreditfakturor, summerar Fakturor (+) / Krediter (−) / <b>ATT BETALA</b>, håller koll på förfallodatum och exporterar betallistor till PDF — helt lokalt på din dator, utan prenumeration.</p><h3>Hur det funkar</h3><ol><li>Välj leverantör i rullistan (favoriter ★ överst).</li><li>Registrera faktura: fakturanummer + belopp. ＋ = faktura, − = kreditfaktura.</li><li>Exportera ALLA aktiva till PDF — betalningsdatum frågas alltid innan export och nollställs efteråt.</li><li>Exporthistorik: återställ arkiverade fakturor, öppna PDF eller mapp.</li></ol><h3>Stöd utvecklingen 💖</h3><p>💙 Swish: <b>{swish}</b> (knappen kopierar numret)<br>🅿️ PayPal: {paypal}<br>☕ Ko-fi: {kofi}</p><hr><p style='color:#888;font-size:11px;'>Plattform: {platform} · Python {python} · Autostart: {autostart}</p>",
        "en": "<h2 style='color:#58a6ff'>{app}</h2><p><b>Version {version}</b> · Modern local invoice handling for Windows, Linux and macOS.</p><p><b>© {year} Rickard Längkvist</b></p><hr><h3>What the app does</h3><p>Registers supplier invoices and credit notes, totals Invoices (+) / Credits (−) / <b>TO PAY</b>, keeps track of due dates and exports payment lists to PDF — entirely locally on your computer, no subscription.</p><h3>How it works</h3><ol><li>Choose a supplier in the list (favourites ★ first).</li><li>Register an invoice: invoice number + amount. ＋ = invoice, − = credit note.</li><li>Export ALL active invoices to PDF — the payment date is always asked before export and reset afterwards.</li><li>Export history: restore archived invoices, open the PDF or folder.</li></ol><h3>Support development 💖</h3><p>💙 Swish: <b>{swish}</b> (the button copies the number)<br>🅿️ PayPal: {paypal}<br>☕ Ko-fi: {kofi}</p><hr><p style='color:#888;font-size:11px;'>Platform: {platform} · Python {python} · Autostart: {autostart}</p>",
    },

    # ── Tray ─────────────────────────────────────────────────────────
    "tray.show": {"sv": "🖥  Visa fönster", "en": "🖥  Show window"},
    "tray.theme": {"sv": "🎨  Tema", "en": "🎨  Theme"},
    "tray.backup": {"sv": "💾  Backup nu", "en": "💾  Backup now"},
    "tray.exports": {"sv": "📁  Öppna exporter", "en": "📁  Open exports"},
    "tray.minimize": {"sv": "🙈  Minimera", "en": "🙈  Minimize"},
    "tray.quit": {"sv": "❌  Avsluta helt", "en": "❌  Quit completely"},
    "tray.tooltip": {"sv": "{app}\nEnkelklicka för att öppna", "en": "{app}\nSingle-click to open"},
}


# ═════════════════════════════════════════════════════════════════════
#  API
# ═════════════════════════════════════════════════════════════════════

def normalize_language(lang: str | None) -> str:
    """'en-US' / 'EN' / 's' → ett språk i LANGUAGES (standard 'sv')."""
    if not lang:
        return "sv"
    code = str(lang).strip().lower().replace("_", "-").split("-")[0]
    if code in ("en", "eng", "english"):
        return "en"
    return "sv"


def language() -> str:
    """Aktuellt språk ('sv' eller 'en')."""
    return _current


def set_language(lang: str | None, *, notify: bool = True) -> str:
    """Sätter aktuellt språk och meddelar lyssnare. Returnerar det satta."""
    global _current
    code = normalize_language(lang)
    changed = code != _current
    _current = code
    if notify and changed:
        for cb in list(_listeners):
            try:
                cb(code)
            except Exception:  # en trasig lyssnare får inte stoppa bytet
                logger.exception("i18n-lyssnare kraschade")
    return _current


def on_language_changed(callback: Callable[[str], None]) -> None:
    """Registrerar en callback som körs vid språkbyte."""
    if callback not in _listeners:
        _listeners.append(callback)


def tr(key: str, **fmt: object) -> str:
    """
    Översatt text för ``key`` på aktuellt språk.

    Extra kwargs formateras in ({name} osv). Saknad nyckel →
    svenska om den finns, annars själva nyckeln (och en loggrad,
    så det syns i loggen i stället för tyst i GUI:t).
    """
    entry = _STRINGS.get(key)
    if entry is None:
        logger.debug("i18n: okänd nyckel %r", key)
        text = key
    else:
        text = entry.get(_current) or entry.get("sv") or key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def tr_list(key: str) -> list[str]:
    """Som tr() men för '|'-separerade listor (tabellrubriker)."""
    return [part.strip() for part in tr(key).split("|")]
