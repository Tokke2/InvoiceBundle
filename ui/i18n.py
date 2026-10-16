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
    "tab.log_tab": {"sv": "🪵  Logg", "en": "🪵  Log"},
    "tab.dashboard.sub": {"sv": "Översikt och nyckeltal", "en": "Overview and key figures"},
    "tab.invoices.sub": {"sv": "Hantera inkommande fakturor", "en": "Manage incoming invoices"},
    "tab.suppliers.sub": {"sv": "Leverantörsregister", "en": "Supplier register"},
    "tab.payments.sub": {"sv": "Betalbatcher och betalhistorik", "en": "Payment batches and history"},
    "tab.import_tab.sub": {"sv": "Importera fakturor via PDF / e-post", "en": "Import invoices via PDF / e-mail"},
    "tab.reports.sub": {"sv": "Månads- och leverantörsrapporter", "en": "Monthly and supplier reports"},
    "tab.settings_tab.sub": {"sv": "Program- och företagsinställningar", "en": "App and company settings"},
    "tab.log_tab.sub": {"sv": "Systemlogg — hitta fel på sekunder", "en": "System log — find errors in seconds"},

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
    "invoices.pay_today": {"sv": "⚡  Betala idag", "en": "⚡  Pay today"},
    "invoices.chip_overdue": {"sv": "🔴  Förfallna", "en": "🔴  Overdue"},
    "invoices.chip_today": {"sv": "📅  Idag & i morgon", "en": "📅  Today & tomorrow"},
    "invoices.chip_week": {"sv": "🗓  Inom 7 dagar", "en": "🗓  Within 7 days"},
    "invoices.pay_today_tip": {"sv": "Markera allt som förfaller idag eller i morgon", "en": "Select everything due today or tomorrow"},
    "invoices.pay_today_none": {"sv": "Inget förfaller idag eller i morgon 🎉", "en": "Nothing is due today or tomorrow 🎉"},
    "invoices.pay_today_found": {"sv": "⚡  {n} faktura(or) förfaller idag/i morgon – markerade, summa {amount}", "en": "⚡  {n} invoice(s) due today/tomorrow – selected, total {amount}"},
    "invoices.att_betala_total": {"sv": "Att betala totalt: {amount} (obetalda)", "en": "Total to pay: {amount} (unpaid)"},
    "invoices.selected_sum": {"sv": "Markerat: {n} st · {amount} · tidigaste förfall {due}", "en": "Selected: {n} · {amount} · earliest due {due}"},
    "invoices.selected_sum_no_due": {"sv": "Markerat: {n} st · {amount}", "en": "Selected: {n} · {amount}"},
    "invoices.copy_payinfo": {"sv": "💳  Kopiera betalinfo", "en": "💳  Copy payment info"},
    "invoices.payinfo_copied": {"sv": "💳  Betalinfo för {nr} kopierad till urklipp", "en": "💳  Payment info for {nr} copied to the clipboard"},
    "invoices.undo_tip": {"sv": "Ångra senaste statusändringen (Ctrl+Z)", "en": "Undo the last status change (Ctrl+Z)"},
    "invoices.undo_done": {"sv": "↩  Ångrade statusändring för {n} faktura(or)", "en": "↩  Undid status change for {n} invoice(s)"},
    "invoices.undo_empty": {"sv": "Inget att ångra", "en": "Nothing to undo"},
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

    # ── Datumväljare / exportdatum ───────────────────────────────────
    "date.today_btn": {"sv": "Idag", "en": "Today"},
    "date.tomorrow_btn": {"sv": "Imorgon", "en": "Tomorrow"},
    "date.month_end_btn": {"sv": "Månadsslut", "en": "End of month"},
    "date.rel_today": {"sv": "idag", "en": "today"},
    "date.rel_tomorrow": {"sv": "imorgon", "en": "tomorrow"},
    "date.rel_yesterday": {"sv": "igår", "en": "yesterday"},
    "date.rel_in_days": {"sv": "om {n} dagar", "en": "in {n} days"},
    "date.rel_days_ago": {"sv": "för {n} dagar sedan", "en": "{n} days ago"},
    "export.date_window_title": {"sv": "Betalningsdatum för export", "en": "Payment date for export"},
    "export.date_title": {"sv": "📄  Ange betalningsdatum för export", "en": "📄  Choose the payment date for this export"},
    "export.date_count": {"sv": "Antal fakturor:  {n}", "en": "Invoices:  {n}"},
    "export.date_suppliers": {"sv": "Leverantörer:     {names}", "en": "Suppliers:     {names}"},
    "export.date_and_more": {"sv": "  och {n} till …", "en": "  and {n} more …"},
    "export.date_info": {"sv": "Betalningsdatumet gäller ALLA fakturor i denna export.\nDet nollställs automatiskt efter exporten.\nNästa export → du tillfrågas igen.", "en": "The payment date applies to ALL invoices in this export.\nIt is reset automatically after the export.\nNext export → you will be asked again."},
    "export.payment_date": {"sv": "Betalningsdatum:", "en": "Payment date:"},
    "export.export_with_date": {"sv": "✔  Exportera med detta datum", "en": "✔  Export with this date"},
    "export.cancel_export": {"sv": "✖  Avbryt export", "en": "✖  Cancel export"},
    "export.choose_for": {"sv": "Ange betalningsdatum för {n} fakturor:", "en": "Choose the payment date for {n} invoices:"},
    "export.export_btn": {"sv": "✔  Exportera", "en": "✔  Export"},

    # ── Donation ─────────────────────────────────────────────────────
    "donate.title": {"sv": "💖 Stöd Fakturabunten", "en": "💖 Support InvoiceBundle"},
    "donate.window_title": {"sv": "Fakturabunten — Stöd projektet", "en": "InvoiceBundle — Support the project"},
    "donate.body_html": {
        "sv": "<p><b>Fakturabunten är gratis och utan reklam.</b> Om programmet hjälper dig i vardagen är en donation ett frivilligt tack som hjälper mig att fortsätta utveckla och underhålla det.</p><ul><li>Ingen reklam, ingen inloggning, inga prenumerationer.</li><li>Donationer går direkt till utveckling och underhåll.</li><li>Appen fungerar exakt lika bra utan donation.</li></ul><p style='color:#8a8a9e;font-size:11px'>Betalningen sker hos PayPal, Ko-fi eller Swish. Fakturabunten ser inga betalningsuppgifter.</p>",
        "en": "<p><b>InvoiceBundle is free and ad-free.</b> If the app helps you in everyday life, a donation is a voluntary thank-you that helps me keep developing and maintaining it.</p><ul><li>No ads, no sign-up, no subscriptions.</li><li>Donations go directly to development and maintenance.</li><li>The app works exactly the same without a donation.</li></ul><p style='color:#8a8a9e;font-size:11px'>Payment takes place at PayPal, Ko-fi or Swish. InvoiceBundle never sees any payment details.</p>",
    },
    "donate.paypal": {"sv": "💙 Donera via PayPal", "en": "💙 Donate with PayPal"},
    "donate.kofi": {"sv": "☕ Bjud på en kaffe (Ko-fi)", "en": "☕ Buy me a coffee (Ko-fi)"},
    "donate.swish_scan": {"sv": "📱  Skanna med Swish-appen", "en": "📱  Scan with the Swish app"},
    "donate.swish_number": {"sv": "Swish: {number}", "en": "Swish: {number}"},
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

    # ── Fakturadialogen ──────────────────────────────────────────────
    "invdialog.title_new": {"sv": "➕  Registrera faktura", "en": "➕  Register invoice"},
    "invdialog.title_edit": {"sv": "✏️  Redigera faktura", "en": "✏️  Edit invoice"},
    "invdialog.supplier": {"sv": "🏢  Leverantör", "en": "🏢  Supplier"},
    "invdialog.none_chosen": {"sv": "(ingen vald)", "en": "(none selected)"},
    "invdialog.session_banner": {"sv": "📅  Session-förfallodatum: {date}  (används som default för nya fakturor)", "en": "📅  Session due date: {date}  (default for new invoices)"},
    "invdialog.primary": {"sv": "🧾  Fakturainformation  ✱", "en": "🧾  Invoice information  ✱"},
    "invdialog.invoice_number": {"sv": "Fakturanummer  ✱ :", "en": "Invoice number  ✱ :"},
    "invdialog.amount": {"sv": "Belopp  ✱ :", "en": "Amount  ✱ :"},
    "invdialog.sign_tip": {"sv": "＋  Faktura – beloppet läggs till ATT BETALA\n−  Kredit – beloppet dras av från ATT BETALA", "en": "＋  Invoice – added to TO PAY\n−  Credit – deducted from TO PAY"},
    "invdialog.type_invoice": {"sv": "🧾  FAKTURA – läggs till ATT BETALA", "en": "🧾  INVOICE – added to TO PAY"},
    "invdialog.type_credit": {"sv": "📋  KREDITFAKTURA – dras av från ATT BETALA", "en": "📋  CREDIT NOTE – deducted from TO PAY"},
    "invdialog.other": {"sv": "📋  Övriga uppgifter  (valfritt)", "en": "📋  Other details  (optional)"},
    "invdialog.ocr": {"sv": "OCR :", "en": "OCR :"},
    "invdialog.reference": {"sv": "Referens :", "en": "Reference :"},
    "invdialog.category": {"sv": "Kategori :", "en": "Category :"},
    "invdialog.category_ph": {"sv": "ex. IT, Kontorsmaterial, Hyra", "en": "e.g. IT, Office supplies, Rent"},
    "invdialog.ref_ph": {"sv": "Er referens / PO-nummer", "en": "Your reference / PO number"},
    "invdialog.invoice_date": {"sv": "Fakturadatum :", "en": "Invoice date :"},
    "invdialog.due_date": {"sv": "Förfallodatum :", "en": "Due date :"},
    "invdialog.payment_date": {"sv": "Betalningsdatum :", "en": "Payment date :"},
    "invdialog.currency": {"sv": "Valuta :", "en": "Currency :"},
    "invdialog.status": {"sv": "Status :", "en": "Status :"},
    "invdialog.note": {"sv": "Anteckning :", "en": "Note :"},
    "invdialog.note_ph": {"sv": "Fritext anteckning …", "en": "Free-text note …"},
    "invdialog.no_date": {"sv": "(ej angivet)", "en": "(not set)"},
    "invdialog.ocr_warning": {"sv": "⚠️  OCR saknas – kontrollera om det behövs.", "en": "⚠️  OCR missing – check if it is needed."},
    "invdialog.ocr_check_warning": {"sv": "⚠️  OCR-numrets kontrollsiffra stämmer inte – dubbelkolla siffrorna.", "en": "⚠️  The OCR check digit does not match – double-check the digits."},
    "invdialog.ocr_check_title": {"sv": "Kontrollsiffran stämmer inte", "en": "Check digit mismatch"},
    "invdialog.ocr_check_body": {"sv": "OCR-numret {ocr} klarar inte kontrollsiffertestet.\nTroligen är en siffra felskriven – då hittar banken inte fakturan.\n\nSpara ändå?", "en": "The OCR number {ocr} fails the check digit test.\nA digit is probably wrong – the bank would not find the invoice.\n\nSave anyway?"},
    "invdialog.dup_warning": {"sv": "⚠️  Fakturanummer {nr} finns redan för {supplier}.", "en": "⚠️  Invoice number {nr} already exists for {supplier}."},
    "payinfo.title": {"sv": "Fakturabetalning", "en": "Invoice payment"},
    "payinfo.supplier": {"sv": "Leverantör", "en": "Supplier"},
    "payinfo.bankgiro": {"sv": "Bankgiro", "en": "Bankgiro"},
    "payinfo.plusgiro": {"sv": "Plusgiro", "en": "Plusgiro"},
    "payinfo.iban": {"sv": "IBAN", "en": "IBAN"},
    "payinfo.invoice_number": {"sv": "Fakturanr", "en": "Invoice no."},
    "payinfo.ocr": {"sv": "OCR", "en": "OCR"},
    "payinfo.reference": {"sv": "Referens", "en": "Reference"},
    "payinfo.due": {"sv": "Förfallodatum", "en": "Due date"},
    "payinfo.amount": {"sv": "Belopp", "en": "Amount"},
    "invdialog.save_changes": {"sv": "💾  Spara ändringar", "en": "💾  Save changes"},
    "invdialog.register": {"sv": "➕  Registrera", "en": "➕  Register"},
    "invdialog.terms": {"sv": "Betalvillkor: {n} dagar", "en": "Payment terms: {n} days"},
    "invdialog.orgnr": {"sv": "Org.nr", "en": "Org. no."},
    "invdialog.bankgiro": {"sv": "Bankgiro", "en": "BG"},
    "invdialog.plusgiro": {"sv": "Plusgiro", "en": "PG"},

    "invdialog.validation": {"sv": "Validering", "en": "Validation"},
    "invdialog.amount_required": {"sv": "Ange ett belopp större än 0.\n\nVälj ＋ för faktura eller − för kreditfaktura.", "en": "Enter an amount greater than 0.\n\nChoose ＋ for invoice or − for credit note."},
    "invdialog.overdue_title": {"sv": "Förfallodatum passerat", "en": "Due date passed"},
    "invdialog.overdue_body": {"sv": "Förfallodatum har passerat.\n\nVill du ändra status till 'Förfallen'?", "en": "The due date has passed.\n\nChange the status to 'Overdue'?"},

    # ── Fakturavyn (summor, info, meddelanden) ────────────────────────
    "invoices.rows": {"sv": "Poster: {n}  ({f}f/{k}k)", "en": "Entries: {n}  ({f} inv/{k} cr)"},
    "invoices.unpaid": {"sv": "Obetalt: {amount}", "en": "Unpaid: {amount}"},
    "invoices.overdue": {"sv": "Förfallet: {amount}", "en": "Overdue: {amount}"},
    "invoices.history_count": {"sv": "({n} exporter)", "en": "({n} exports)"},
    "invoices.none_chosen": {"sv": "(ingen vald)", "en": "(none selected)"},
    "invoices.no_supplier_title": {"sv": "🏢  Ingen leverantör vald", "en": "🏢  No supplier selected"},
    "invoices.no_supplier_body": {"sv": "Välj en leverantör i listan först — eller skapa en ny.", "en": "Choose a supplier in the list first — or create a new one."},
    "invoices.delete_title": {"sv": "Ta bort faktura", "en": "Delete invoice"},
    "invoices.delete_body": {"sv": "Ta bort fakturan?\nKan inte ångras.", "en": "Delete this invoice?\nThis cannot be undone."},
    "invoices.export_title": {"sv": "Komplett fakturalista", "en": "Complete invoice list"},

    "invoices.rows_of": {"sv": "Poster: {shown} av {total}  ({f}f/{k}k)", "en": "Entries: {shown} of {total}  ({f} inv/{k} cr)"},
    "invoices.export_all_n": {"sv": "📄  Exportera ALLA till PDF  ({n})", "en": "📄  Export ALL to PDF  ({n})"},
    "invoices.export_none": {"sv": "📄  Inga fakturor att exportera", "en": "📄  No invoices to export"},
    "invoices.favorite": {"sv": "★ Favorit", "en": "★ Favourite"},

    # ── Leverantörsdialogen (återstående fält) ────────────────────────
    "supplierdlg.bg": {"sv": "Bankgiro (BG):", "en": "Bankgiro (BG):"},
    "supplierdlg.pg": {"sv": "Plusgiro (PG):", "en": "Plusgiro (PG):"},
    "supplierdlg.iban": {"sv": "IBAN:", "en": "IBAN:"},
    "supplierdlg.bic": {"sv": "BIC / SWIFT:", "en": "BIC / SWIFT:"},
    "supplierdlg.terms": {"sv": "Betalvillkor:", "en": "Payment terms:"},
    "supplierdlg.contact": {"sv": "Kontaktperson:", "en": "Contact person:"},
    "supplierdlg.email": {"sv": "E-post:", "en": "E-mail:"},
    "supplierdlg.phone": {"sv": "Telefon:", "en": "Phone:"},
    "supplierdlg.address": {"sv": "Adress:", "en": "Address:"},
    "supplierdlg.note": {"sv": "Anteckning:", "en": "Note:"},
    "supplierdlg.note_ph": {"sv": "Fritext anteckning …", "en": "Free-text note …"},
    "supplier.unknown_title": {"sv": "Okänd leverantör", "en": "Unknown supplier"},
    "supplier.unknown_body": {"sv": "Leverantören '{name}' finns inte.\nLägga till nu?", "en": "The supplier '{name}' does not exist.\nAdd it now?"},

    # ── Kortkommandon (Inställnings-fliken) ───────────────────────────
    "shortcut.ny_leverantor": {"sv": "Ny leverantör", "en": "New supplier"},
    "shortcut.ny_faktura": {"sv": "Ny faktura", "en": "New invoice"},
    "shortcut.skapa_backup": {"sv": "Skapa backup", "en": "Create backup"},
    "shortcut.exportera_pdf": {"sv": "Exportera alla aktiva till PDF", "en": "Export all active to PDF"},
    "shortcut.uppdatera": {"sv": "Uppdatera alla vyer", "en": "Refresh all views"},
    "shortcut.avsluta": {"sv": "Avsluta programmet helt", "en": "Quit completely"},
    "shortcut.tab_dashboard": {"sv": "Hoppa till Dashboard", "en": "Go to Dashboard"},
    "shortcut.tab_fakturor": {"sv": "Hoppa till Fakturor", "en": "Go to Invoices"},
    "shortcut.tab_leverantorer": {"sv": "Hoppa till Leverantörer", "en": "Go to Suppliers"},
    "shortcut.tab_betalningar": {"sv": "Hoppa till Betalningar", "en": "Go to Payments"},
    "shortcut.tab_import": {"sv": "Hoppa till Import", "en": "Go to Import"},
    "shortcut.tab_rapporter": {"sv": "Hoppa till Rapporter", "en": "Go to Reports"},
    "shortcut.tab_installningar": {"sv": "Hoppa till Inställningar", "en": "Go to Settings"},
    "shortcut.tab_logg": {"sv": "Hoppa till Logg", "en": "Go to Log"},

    # ── Huvudfönstrets dialoger ───────────────────────────────────────
    "main.quit_title": {"sv": "Avsluta programmet", "en": "Quit the app"},
    "main.quit_body": {"sv": "Stäng {app} helt?\n\nAlla data har sparats automatiskt.", "en": "Close {app} completely?\n\nAll data has been saved automatically."},
    "main.backup_created": {"sv": "✅  Backup skapad:\n{path}", "en": "✅  Backup created:\n{path}"},
    "main.backup_failed": {"sv": "❌  Backup misslyckades.", "en": "❌  Backup failed."},
    "main.no_supplier_title": {"sv": "🏢  Ingen leverantör", "en": "🏢  No supplier"},
    "main.no_supplier_body": {"sv": "Du måste skapa en leverantör\ninnan du kan registrera en faktura.\n\nVill du lägga till en leverantör nu?", "en": "You must create a supplier\nbefore you can register an invoice.\n\nAdd a supplier now?"},
    "main.view_missing": {"sv": "Leverantörsvyn saknas.", "en": "The suppliers view is missing."},
    "main.invoice_view_missing": {"sv": "Fakturavyn saknas.", "en": "The invoices view is missing."},

    "main.reading": {"sv": "🔄  Läser data/ …", "en": "🔄  Reading data/ …"},
    "main.opening": {"sv": "📁  Öppnar: {path}", "en": "📁  Opening: {path}"},
    "main.shortcuts_restored": {"sv": "↩️  Standardkortkommandon återställda", "en": "↩️  Default shortcuts restored"},
    "main.plugin_status_na": {"sv": "Status ej tillgänglig: {error}", "en": "Status unavailable: {error}"},
    "main.autostart": {"sv": "Autostart", "en": "Autostart"},
    "main.autostart_failed": {"sv": "Kunde inte registrera autostart hos operativsystemet.\nInställningen är sparad och försöket görs om vid nästa start.", "en": "Could not register autostart with the operating system.\nThe setting is saved and will be retried at next start."},
    "main.autostart_error": {"sv": "Kunde inte ändra:\n{error}", "en": "Could not change:\n{error}"},
    "main.autostart_on": {"sv": "Autostart är på.\n\nVid inloggning väntar programmet om disken inte är redo,\nstartar gömd, och sätter arbetsmappen till appmappen.", "en": "Autostart is on.\n\nAt login the app waits if the disk is not ready,\nstarts hidden, and sets the working folder to the app folder."},
    "main.autostart_off": {"sv": "Autostart är av.\nProgrammet startar inte längre vid inloggning.", "en": "Autostart is off.\nThe app no longer starts at login."},
    "main.autostart_status": {"sv": "🚀  Autostart {state}", "en": "🚀  Autostart {state}"},
    "main.autostart_on_direct": {"sv": "Autostart är på (direktstart, utan VBS).\n\nVid inloggning:\n• OS startar Python direkt — ingen startfil behövs\n• startar gömd i systemfältet, utan konsolfönster\n• arbetsmapp = appmappen, aldrig System32\n\nArbetsmapp: {workdir}\nKommando: {command}", "en": "Autostart is on (direct start, no VBS).\n\nAt login:\n• the OS starts Python directly — no launcher file needed\n• starts hidden in the system tray, without a console window\n• working folder = the app folder, never System32\n\nWorking folder: {workdir}\nCommand: {command}"},
    "autostart.method": {"sv": "Autostart-metod", "en": "Autostart method"},
    "autostart.method_tip": {"sv": "Hur appen startas vid inloggning.\nDirekt = utan VBS/startfil (rekommenderas).\nStartfil = väntar på att disken blir redo (portabel USB).", "en": "How the app starts at login.\nDirect = no VBS/launcher file (recommended).\nLauncher file = waits for the disk to become ready (portable USB)."},
    "autostart.method_auto": {"sv": "Automatiskt (direkt, utan VBS)", "en": "Automatic (direct, no VBS)"},
    "autostart.method_direct": {"sv": "Direkt — utan VBS/startfil", "en": "Direct — no VBS/launcher file"},
    "autostart.method_launcher": {"sv": "Startfil i appmappen (väntar på disk)", "en": "Launcher file in app folder (waits for disk)"},
    "autostart.method_set": {"sv": "🚀  Autostart-metod: {method}", "en": "🚀  Autostart method: {method}"},
    "autostart.method_failed": {"sv": "Kunde inte byta autostart-metod hos operativsystemet.", "en": "Could not change the autostart method with the operating system."},
    "main.autostart_on_full": {"sv": "Autostart är på.\n\nVid inloggning:\n• väntar upp till 90 sekunder om disken inte är redo (t.ex. om E: inte hunnit monteras)\n• startar gömd i systemfältet, utan konsolfönster\n• arbetsmapp = appmappen, aldrig System32\n\nArbetsmapp: {workdir}\nStartfil: {launcher}", "en": "Autostart is on.\n\nAt login:\n• waits up to 90 seconds if the disk is not ready (e.g. if E: has not mounted yet)\n• starts hidden in the system tray, without a console window\n• working folder = the app folder, never System32\n\nWorking folder: {workdir}\nLauncher: {launcher}"},
    "main.on_check": {"sv": "på ✔", "en": "on ✔"},
    "main.off": {"sv": "av", "en": "off"},
    "main.close_tray_status": {"sv": "🙈  Stäng till tray: {state}", "en": "🙈  Close to tray: {state}"},
    "main.on": {"sv": "PÅ", "en": "ON"},
    "main.off_state": {"sv": "AV", "en": "OFF"},
    "donate.paypal_tip": {"sv": "Öppnar PayPal i webbläsaren", "en": "Opens PayPal in the browser"},
    "donate.kofi_tip": {"sv": "Öppnar Ko-fi i webbläsaren", "en": "Opens Ko-fi in the browser"},
    "donate.about_tip": {"sv": "Öppnar about.md med komplett info", "en": "Opens about.md with complete info"},

    # ── Skanningsimport (återstående) ─────────────────────────────────
    "scan.columns": {"sv": "Fil|Leverantör|Fakturanr|Datum|Förfaller|OCR|Belopp|Metod|Status", "en": "File|Supplier|Invoice no.|Date|Due|OCR|Amount|Method|Status"},
    "scan.sum": {"sv": "{n} rad(er)  ·  summa {amount} kr", "en": "{n} row(s)  ·  total {amount} SEK"},
    "scan.ready": {"sv": "redo", "en": "ready"},
    "scan.missing": {"sv": "saknas: {fields}", "en": "missing: {fields}"},

    "scan.no_text": {"sv": "ingen text hittad", "en": "no text found"},

    # ── Bevakade mappar (auto-import) ─────────────────────────────────
    "watch.title": {"sv": "📁  Bevakade mappar — automatisk import", "en": "📁  Watched folders — automatic import"},
    "watch.info": {"sv": "En mapp per leverantör (t.ex. Pilkington, Direktglas). Nya fakturafiler tolkas och registreras automatiskt; ofullständiga parkeras här för granskning. Samma fil importeras aldrig två gånger.", "en": "One folder per supplier (e.g. Pilkington, Direktglas). New invoice files are parsed and registered automatically; incomplete ones are parked here for review. The same file is never imported twice."},
    "watch.add_folder": {"sv": "➕  Lägg till mapp …", "en": "➕  Add folder …"},
    "watch.remove_folder": {"sv": "🗑  Ta bort markerad", "en": "🗑  Remove selected"},
    "watch.auto_create": {"sv": "Registrera kompletta fakturor automatiskt", "en": "Register complete invoices automatically"},
    "watch.no_folders": {"sv": "(inga bevakade mappar ännu)", "en": "(no watched folders yet)"},
    "watch.folder_entry": {"sv": "{supplier}  →  {path}", "en": "{supplier}  →  {path}"},
    "watch.folder_no_supplier": {"sv": "(leverantör känns igen automatiskt)", "en": "(supplier recognised automatically)"},
    "watch.parked": {"sv": "⏸  {n} fil(er) väntar på granskning", "en": "⏸  {n} file(s) awaiting review"},
    "watch.review": {"sv": "Granska i tabellen", "en": "Review in table"},
    "watch.learn": {"sv": "🎓 Lär appen från mappen…", "en": "🎓 Teach the app from the folder…"},
    "watch.learn_title": {"sv": "Lär appen läsa fakturorna", "en": "Teach the app to read the invoices"},
    "watch.learn_offer": {"sv": "Vill du lära appen läsa fakturor från {supplier}?\n\nAlla leverantörer har egen layout, så mappen blir inte automatisk förrän du visat appen hur {supplier} ser ut. Du får se en av filerna i mappen och markerar vad som är fakturanummer, belopp, förfallodatum m.m. Det sparas som en mall i invoice_templates.json — sedan läser appen resten själv.", "en": "Would you like to teach the app to read invoices from {supplier}?\n\nEvery supplier has its own layout, so the folder does not become automatic until you have shown the app what {supplier} looks like. You see one of the files in the folder and mark which is the invoice number, amount, due date, etc. It is saved as a template in invoice_templates.json — then the app reads the rest itself."},
    "watch.learn_need_folder": {"sv": "Markera en bevakad mapp i listan först", "en": "Select a watched folder in the list first"},
    "watch.learn_no_files": {"sv": "Inga PDF:er eller bilder i mappen ännu — lägg en exempelfaktura där först", "en": "No PDFs or images in the folder yet — put a sample invoice there first"},
    "watch.learn_no_text": {"sv": "Kunde inte läsa någon text ur {file}", "en": "Could not read any text from {file}"},
    "watch.learn_pick": {"sv": "Välj en faktura att visa appen:", "en": "Choose an invoice to show the app:"},
    "watch.imported": {"sv": "📥  Auto-import: {file} registrerad", "en": "📥  Auto-import: {file} registered"},
    "watch.dialog_title": {"sv": "Bevaka mapp för leverantör", "en": "Watch folder for supplier"},
    "watch.supplier": {"sv": "Leverantör:", "en": "Supplier:"},
    "watch.folder": {"sv": "Mapp:", "en": "Folder:"},
    "watch.browse": {"sv": "Bläddra …", "en": "Browse …"},
    "watch.add": {"sv": "➕  Bevaka mappen", "en": "➕  Watch folder"},
    "watch.need_folder": {"sv": "Välj en befintlig mapp först.", "en": "Choose an existing folder first."},
    "menu.include_originals": {"sv": "📎  Inkludera originalfakturor i PDF-export", "en": "📎  Include original invoices in PDF export"},
    "invoices.attachments_note": {"sv": "  📎 {n} original bifogade", "en": "  📎 {n} originals attached"},
    "invoices.attachments_missing": {"sv": "⚠ {n} original kunde inte bifogas (saknas på disk — flyttade eller raderade)", "en": "⚠ {n} originals could not be attached (missing on disk — moved or deleted)"},
    "invoices.originals_archived": {"sv": "  📁 {n} original flyttade till Arkiv/{year}", "en": "  📁 {n} originals moved to Arkiv/{year}"},

    # ── Uppdatering i appen ───────────────────────────────────────────
    "menu.update": {"sv": "🔄  Sök ny version …", "en": "🔄  Check for updates …"},
    "update.title": {"sv": "Sök ny version", "en": "Check for updates"},
    "update.checking": {"sv": "Söker efter ny version …", "en": "Checking for a new version …"},
    "update.current": {"sv": "Du har redan den senaste versionen (v{version}).", "en": "You already have the latest version (v{version})."},
    "update.available": {"sv": "🎉  Ny version finns: {tag}  (installerad: {current})", "en": "🎉  A new version is available: {tag}  (installed: {current})"},
    "update.published": {"sv": "Släppt: {date}", "en": "Released: {date}"},
    "update.install": {"sv": "⬇️  Hämta och installera", "en": "⬇️  Download and install"},
    "update.downloading": {"sv": "Hämtar uppdateringen … {percent}%", "en": "Downloading the update … {percent}%"},
    "update.installing_files": {"sv": "Installerar … fil {done} av {total}", "en": "Installing … file {done} of {total}"},
    "update.applying": {"sv": "Installerar …", "en": "Installing …"},
    "update.safe_note": {"sv": "✓ Bara programfilerna byts. Dina fakturor och data (data/, ui/data/), settings.json, loggar och exporter rörs aldrig. En backup sparas i bak/.", "en": "✓ Only program files are replaced. Your invoices and data (data/, ui/data/), settings.json, logs and exports are never touched. A backup is saved in bak/."},
    "update.done": {"sv": "✅  Uppdateringen är installerad ({n} filer utbytta). Starta om appen för att köra den nya versionen.", "en": "✅  The update is installed ({n} files replaced). Restart the app to run the new version."},
    "update.restart": {"sv": "🔁  Starta om nu", "en": "🔁  Restart now"},
    "update.close": {"sv": "Stäng", "en": "Close"},
    "update.failed": {"sv": "Kunde inte slutföra uppdateringen.\n{error}", "en": "The update could not be completed.\n{error}"},
    "update.notes": {"sv": "Versionsnoteringar:", "en": "Release notes:"},
    "update.installed_build": {"sv": "Installerad build: {build}", "en": "Installed build: {build}"},
    "update.auto_menu": {"sv": "🔄  Sök uppdateringar automatiskt vid start", "en": "🔄  Check for updates automatically at startup"},
    "update.found_title": {"sv": "Ny version finns", "en": "Update available"},
    "update.found_text": {"sv": "En ny version av Fakturabunten finns att hämta ({tag}).\nInstallera den nu? Dina data rörs aldrig — bara programfilerna byts.", "en": "A new version of InvoiceBundle is available ({tag}).\nInstall it now? Your data is never touched — only program files are replaced."},
    "update.install_now": {"sv": "⬇️  Installera nu", "en": "⬇️  Install now"},
    "update.later": {"sv": "Senare", "en": "Later"},
    "update.restore": {"sv": "↩  Återställ senaste backup …", "en": "↩  Restore latest backup …"},
    "update.restore_confirm": {"sv": "Återställ programfilerna från backupen {name}?\nFakturor och data påverkas inte.", "en": "Restore the program files from backup {name}?\nInvoices and data are not affected."},
    "update.restored": {"sv": "↩  Backup återställd ({n} filer). Starta om appen.", "en": "↩  Backup restored ({n} files). Restart the app."},
    "update.unknown_build": {"sv": "okänd (äldre kopia utan build-info)", "en": "unknown (older copy without build info)"},

    # ── Slå ihop markerade fakturor ───────────────────────────────────
    "combine.button": {"sv": "🧮  Slå ihop markerade", "en": "🧮  Combine selected"},
    "combine.tip": {"sv": "Lägg ihop markerade fakturor: totalsumma + förfallodatum från den som förfaller först", "en": "Add up the selected invoices: total + the due date of the earliest one"},
    "combine.title": {"sv": "Sammanslagning — {n} fakturor", "en": "Combined — {n} invoices"},
    "combine.status": {"sv": "🧮  Markerade: {n} st · {amount} · tidigast förfall {due}", "en": "🧮  Selected: {n} · {amount} · earliest due {due}"},
    "combine.status_no_due": {"sv": "🧮  Markerade: {n} st · {amount}", "en": "🧮  Selected: {n} · {amount}"},
    "combine.invoices_line": {"sv": "Fakturor ({n}):", "en": "Invoices ({n}):"},
    "combine.credits_line": {"sv": "Krediter ({n}):", "en": "Credits ({n}):"},
    "combine.total": {"sv": "ATT BETALA:", "en": "TOTAL TO PAY:"},
    "combine.earliest": {"sv": "📅  Förfaller först: {date}  ({supplier} · {nr})", "en": "📅  Earliest due: {date}  ({supplier} · {nr})"},
    "combine.earliest_none": {"sv": "📅  Ingen av de markerade har ett förfallodatum", "en": "📅  None of the selected invoices has a due date"},
    "combine.missing_due": {"sv": "⚠  {n} av fakturorna saknar förfallodatum", "en": "⚠  {n} of the invoices have no due date"},
    "combine.due_today": {"sv": "förfaller idag!", "en": "due today!"},
    "combine.due_in": {"sv": "om {d} dagar", "en": "in {d} days"},
    "combine.due_overdue": {"sv": "förfallen sedan {d} dagar!", "en": "overdue by {d} days!"},
    "combine.copy": {"sv": "📋  Kopiera sammanfattning", "en": "📋  Copy summary"},
    "combine.copied": {"sv": "Sammanfattningen kopierad till urklipp", "en": "Summary copied to clipboard"},
    "combine.export_sel": {"sv": "📄  Exportera dessa till betal-PDF …", "en": "📄  Export these to payment PDF …"},
    "combine.close": {"sv": "Stäng", "en": "Close"},
    "combine.export_title": {"sv": "Exportera markerade fakturor", "en": "Export selected invoices"},
    "combine.need_two": {"sv": "Markera minst två fakturor i listan först.", "en": "Select at least two invoices in the list first."},

    # ── Automatisk batch-export ───────────────────────────────────────
    "auto_batch.menu": {"sv": "🤖  Autoexport: 10 fakturor/leverantör eller förfall inom 5 dagar", "en": "🤖  Auto-export: 10 invoices/supplier or due within 5 days"},
    "auto_batch.pdf_title": {"sv": "Autoexport – {supplier}", "en": "Auto-export – {supplier}"},
    "auto_batch.done": {"sv": "🤖  Autoexport: {n} fakturor från {supplier} exporterades och sattes som Betald", "en": "🤖  Auto-export: {n} invoices from {supplier} exported and marked Paid"},
    "auto_batch.printed": {"sv": "  ·  🖨 utskriven med original", "en": "  ·  🖨 printed with originals"},
    "auto_batch.failed": {"sv": "🤖  Autoexport för {supplier} misslyckades: {error}", "en": "🤖  Auto-export for {supplier} failed: {error}"},

    # ── Dashboard ─────────────────────────────────────────────────────
    "dashboard.title": {"sv": "🏠  Dashboard", "en": "🏠  Dashboard"},
    "dashboard.open_invoices": {"sv": "🧾  Öppna Fakturor", "en": "🧾  Open Invoices"},
    "dashboard.to_pay": {"sv": "ATT BETALA", "en": "TO PAY"},
    "dashboard.to_pay_sub": {"sv": "{n} obetalda fakturor", "en": "{n} unpaid invoices"},
    "dashboard.overdue": {"sv": "FÖRFALLET", "en": "OVERDUE"},
    "dashboard.overdue_sub": {"sv": "{n} fakturor passerade", "en": "{n} invoices past due"},
    "dashboard.due_week": {"sv": "FÖRFALLER 7 DAGAR", "en": "DUE IN 7 DAYS"},
    "dashboard.due_week_sub": {"sv": "{n} fakturor på väg", "en": "{n} invoices coming up"},
    "dashboard.suppliers": {"sv": "LEVERANTÖRER", "en": "SUPPLIERS"},
    "dashboard.suppliers_sub": {"sv": "{n} fakturor totalt", "en": "{n} invoices in total"},
    "dashboard.upcoming": {"sv": "Förfaller snart", "en": "Due soon"},
    "dashboard.col_due": {"sv": "Förfaller", "en": "Due"},
    "dashboard.col_supplier": {"sv": "Leverantör", "en": "Supplier"},
    "dashboard.col_invoice": {"sv": "Fakturanr", "en": "Invoice no."},
    "dashboard.col_amount": {"sv": "Belopp", "en": "Amount"},
    "dashboard.currency": {"sv": "kr", "en": "SEK"},
    "dashboard.hint": {"sv": "Dubbelklicka eller använd knappen för att öppna Fakturor.", "en": "Double-click or use the button to open Invoices."},
    "main.to_pay_bar": {"sv": "Att betala: {amount}  ({n} obetalda)", "en": "To pay: {amount}  ({n} unpaid)"},
    "tray.tooltip_due": {"sv": "{app} · Att betala {amount} ({n} obetalda)", "en": "{app} · To pay {amount} ({n} unpaid)"},
    "scan.ocr_warn": {"sv": "⚠ OCR-kontrollsiffra", "en": "⚠ OCR check digit"},
    "dashboard.credits_stale": {"sv": "⚠️  {n} kreditfaktura(or) på {amount} har legat okvittade i över 30 dagar – kontrollera så ATT BETALA stämmer.", "en": "⚠️  {n} credit invoice(s) totalling {amount} have been unnetted for over 30 days – check that TO PAY adds up."},
    "dashboard.all_clear": {"sv": "🎉  Inget förfaller den närmaste veckan — allt är under kontroll.", "en": "🎉  Nothing due in the next week — everything is under control."},

    # ── Loggfliken (felsökning) ───────────────────────────────────────
    "log.title": {"sv": "🪵  Systemlogg — hitta fel på sekunder", "en": "🪵  System log — find errors in seconds"},
    "log.level": {"sv": "Nivå:", "en": "Level:"},
    "log.search_ph": {"sv": "Sök i loggen (meddelande, logger, action) …", "en": "Search the log (message, logger, action) …"},
    "log.only_errors": {"sv": "Endast fel", "en": "Errors only"},
    "log.only_session": {"sv": "Denna session", "en": "This session"},
    "log.auto_scroll": {"sv": "Auto-scroll", "en": "Auto-scroll"},
    "log.col_time": {"sv": "Tid", "en": "Time"},
    "log.col_level": {"sv": "Nivå", "en": "Level"},
    "log.col_logger": {"sv": "Logger", "en": "Logger"},
    "log.col_action": {"sv": "Action", "en": "Action"},
    "log.col_message": {"sv": "Meddelande", "en": "Message"},
    "log.banner_errors": {"sv": "⚠  {n} fel i loggen — senaste: {last}", "en": "⚠  {n} errors in the log — latest: {last}"},
    "log.goto_error": {"sv": "Visa senaste felet", "en": "Show latest error"},
    "log.refresh": {"sv": "🔄  Uppdatera", "en": "🔄  Refresh"},
    "log.pause": {"sv": "⏸  Pausa live", "en": "⏸  Pause live"},
    "log.resume": {"sv": "▶  Återuppta", "en": "▶  Resume"},
    "log.mark": {"sv": "🔖  Markera här", "en": "🔖  Mark here"},
    "log.marker_set": {"sv": "✔  Markering satt!", "en": "✔  Marker set!"},
    "log.marker_text": {"sv": "Användarmarkering — återskapa felet nu, kopiera sedan loggen efter markeringen", "en": "User marker — reproduce the error now, then copy the log after the marker"},
    "log.copy_marked": {"sv": "📋  Kopiera efter markering", "en": "📋  Copy after marker"},
    "log.copy_diag": {"sv": "📋  Kopiera felsökningspaket", "en": "📋  Copy diagnostics"},
    "log.open_dir": {"sv": "📁  Öppna loggmapp", "en": "📁  Open log folder"},
    "log.export_shown": {"sv": "💾  Exportera visade", "en": "💾  Export shown"},
    "log.export_title": {"sv": "Exportera logg", "en": "Export log"},
    "log.reset_filters": {"sv": "🧹  Nollställ filter", "en": "🧹  Reset filters"},
    "log.copy_row": {"sv": "📋  Kopiera rad", "en": "📋  Copy row"},
    "log.copied": {"sv": "✔  Kopierat!", "en": "✔  Copied!"},
    "log.info_line": {"sv": "Visar {shown} av {total} rader  ·  {errors} fel  ·  {warnings} varningar  ·  loggfil {size} KB", "en": "Showing {shown} of {total} rows  ·  {errors} errors  ·  {warnings} warnings  ·  log file {size} KB"},

    # ── Leverantörsmallar för tolkning ────────────────────────────────
    "scan.select_row": {"sv": "Markera en rad i tabellen först.", "en": "Select a row in the table first."},
    "scan.template_btn": {"sv": "🧩  Mall för rad …", "en": "🧩  Template for row …"},
    "scan.templates_btn": {"sv": "🧩  Mallar ({n})", "en": "🧩  Templates ({n})"},
    "scan.template_used": {"sv": "redo 🧩", "en": "ready 🧩"},
    "tmpl.title": {"sv": "🧩  Fakturamall — {supplier}", "en": "🧩  Invoice template — {supplier}"},
    "tmpl.supplier": {"sv": "Leverantör:", "en": "Supplier:"},
    "tmpl.intro": {"sv": "Markera ett värde i fakturatexten (t.ex. beloppet) och klicka sedan på 🎯 vid rätt fält — etiketten före värdet hämtas automatiskt. Justera etiketten vid behov, testa mallen och spara. Nästa faktura från samma leverantör tolkas då med mallen.", "en": "Select a value in the invoice text (e.g. the amount) and click 🎯 next to the right field — the label before the value is filled in automatically. Adjust the label if needed, test the template and save. The next invoice from the same supplier will then be read with the template."},
    "tmpl.use_selection": {"sv": "🎯 Använd markerad text", "en": "🎯 Use selected text"},
    "tmpl.label_ph": {"sv": "Etikett på fakturan, t.ex. Att betala", "en": "Label on the invoice, e.g. Total due"},
    "tmpl.found": {"sv": "→ {value}", "en": "→ {value}"},
    "tmpl.not_found": {"sv": "→ (hittades inte)", "en": "→ (not found)"},
    "tmpl.test": {"sv": "🧪  Testa mallen", "en": "🧪  Test template"},
    "tmpl.save": {"sv": "💾  Spara mall", "en": "💾  Save template"},
    "tmpl.need_supplier": {"sv": "Ange leverantörens namn först.", "en": "Enter the supplier name first."},
    "tmpl.need_label": {"sv": "Fyll i minst en etikett.", "en": "Fill in at least one label."},
    "tmpl.saved": {"sv": "🧩  Mall sparad för {supplier} — raden tolkas om", "en": "🧩  Template saved for {supplier} — re-reading the row"},
    "tmpl.no_selection": {"sv": "Markera först ett värde i texten.", "en": "Select a value in the text first."},
    "tmpl.manager_title": {"sv": "🧩  Sparade fakturamallar", "en": "🧩  Saved invoice templates"},
    "tmpl.manager_empty": {"sv": "Inga mallar ännu. Öppna en tolkad rad och välj 'Mall för rad …'.", "en": "No templates yet. Open a parsed row and choose 'Template for row …'."},
    "tmpl.manager_entry": {"sv": "{supplier} — {n} fält: {fields}", "en": "{supplier} — {n} fields: {fields}"},
    "tmpl.delete": {"sv": "🗑  Ta bort vald mall", "en": "🗑  Delete selected template"},
    "tmpl.field_invoice_number": {"sv": "Fakturanummer", "en": "Invoice number"},
    "tmpl.field_total_amount": {"sv": "Belopp (att betala)", "en": "Amount (total due)"},
    "tmpl.field_date": {"sv": "Fakturadatum", "en": "Invoice date"},
    "tmpl.field_due_date": {"sv": "Förfallodatum", "en": "Due date"},
    "tmpl.field_ocr": {"sv": "OCR-nummer", "en": "OCR number"},

    # ── PDF-export ────────────────────────────────────────────────────
    "pdf.complete_list": {"sv": "Komplett fakturalista", "en": "Complete invoice list"},
    "pdf.page": {"sv": "Sida {n} av {total}", "en": "Page {n} of {total}"},
    "pdf.invoices_plus": {"sv": "Fakturor  (+):", "en": "Invoices  (+):"},
    "pdf.credits_minus": {"sv": "Krediter  (-):", "en": "Credits  (-):"},
    "pdf.to_pay": {"sv": "ATT BETALA:", "en": "TO PAY:"},
    "pdf.invoices_count": {"sv": "Fakturor: {n}", "en": "Invoices: {n}"},
    "pdf.credits_count": {"sv": "Krediter: {n}", "en": "Credits: {n}"},
    "pdf.payment_date": {"sv": "Betalningsdatum", "en": "Payment date"},
    "pdf.no_invoices": {"sv": "Inga fakturor att exportera.", "en": "No invoices to export."},

    # ── Tray ─────────────────────────────────────────────────────────
    "tray.show": {"sv": "🖥  Visa fönster", "en": "🖥  Show window"},
    "tray.theme": {"sv": "🎨  Tema", "en": "🎨  Theme"},
    "tray.backup": {"sv": "💾  Backup nu", "en": "💾  Backup now"},
    "tray.exports": {"sv": "📁  Öppna exporter", "en": "📁  Open exports"},
    "tray.minimize": {"sv": "🙈  Minimera", "en": "🙈  Minimize"},
    "tray.quit": {"sv": "❌  Avsluta helt", "en": "❌  Quit completely"},
    "tray.tooltip": {"sv": "{app}\nEnkelklicka för att öppna", "en": "{app}\nSingle-click to open"},
}


# Kanoniska värden som LAGRAS i datafilerna (alltid svenska, så att
# filter/statuslogik aldrig bryts av ett språkbyte) → visningstext.
STATUS_LABELS: dict[str, dict[str, str]] = {
    "Obetald":         {"sv": "Obetald",         "en": "Unpaid"},
    "Planerad":        {"sv": "Planerad",        "en": "Planned"},
    "Betalfil skapad": {"sv": "Betalfil skapad", "en": "Payment file created"},
    "Betald":          {"sv": "Betald",          "en": "Paid"},
    "Förfallen":       {"sv": "Förfallen",       "en": "Overdue"},
    "Makulerad":       {"sv": "Makulerad",       "en": "Cancelled"},
    "Arkiverad":       {"sv": "Arkiverad",       "en": "Archived"},
}

TYPE_LABELS: dict[str, dict[str, str]] = {
    "Faktura":       {"sv": "Faktura",       "en": "Invoice"},
    "Kreditfaktura": {"sv": "Kreditfaktura", "en": "Credit note"},
    "Kredit":        {"sv": "Kredit",        "en": "Credit"},
}


#: Fält som skanningsparsern rapporterar som saknade (svenska internt).
SCAN_MISSING_LABELS: dict[str, dict[str, str]] = {
    "belopp":         {"sv": "belopp",         "en": "amount"},
    "fakturanummer":  {"sv": "fakturanummer",  "en": "invoice number"},
    "leverantör":     {"sv": "leverantör",     "en": "supplier"},
    "datum":          {"sv": "datum",          "en": "date"},
    "förfallodatum":  {"sv": "förfallodatum",  "en": "due date"},
}


def tr_missing(fields: list) -> str:
    """Visningstext för parserns saknade-fält-lista."""
    out = []
    for f in fields:
        entry = SCAN_MISSING_LABELS.get(str(f))
        out.append(
            (entry.get(_current) or entry["sv"]) if entry else str(f)
        )
    return ", ".join(out)


def tr_status(status: str) -> str:
    """Visningstext för en lagrad (svensk) status, på aktuellt språk."""
    entry = STATUS_LABELS.get(str(status))
    if entry is None:
        return str(status)
    return entry.get(_current) or entry["sv"]


def tr_type(invoice_type: str) -> str:
    """Visningstext för en lagrad (svensk) fakturatyp."""
    entry = TYPE_LABELS.get(str(invoice_type))
    if entry is None:
        return str(invoice_type)
    return entry.get(_current) or entry["sv"]


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
