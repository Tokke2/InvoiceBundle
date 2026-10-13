# Fakturabunten / InvoiceBundle

Lokalt program som räknar ihop fakturor och krediter till en summa att betala.
A local app that totals invoices and credit notes into one amount to pay.

Ingen prenumeration. Ingen molntjänst. All data ligger i programmappen på din dator.
No subscription. No cloud. All data stays in the app folder on your computer.

**© 2026 Rickard Längkvist**

## Språk / Language

Appen finns på **svenska** (standard) och **engelska**.
Byt i menyn **🌐 Språk → Svenska / English** eller på fliken Inställningar — bytet gäller direkt, utan omstart.

The app is available in **Swedish** (default) and **English**.
Switch via the **🌐 Language** menu or the Settings tab — it applies instantly, no restart needed.

## Gratis, med frivillig donation / Free, with voluntary donation

Programmet är gratis att använda. En donation krävs inte och låser inte upp något.

Donera via **💖 Stöd Fakturabunten…** (Hjälp-menyn, guldknappen i verktygsfältet, knappen i statusfältet, högerklick på flikraden eller Inställnings-fliken):

- 💙 PayPal: https://paypal.me/Rickard3dPrint
- ☕ Ko-fi: https://ko-fi.com/tokke2
- 📱 Swish: knappen i donationsrutan kopierar numret

Free to use — a donation is never required and unlocks nothing. Donate via PayPal, Ko-fi or Swish from the **💖 Support** button/dialog inside the app.

## Vad det gör / What it does

- Registrerar leverantörsfakturor och kreditfakturor. / Registers supplier invoices and credit notes.
- Leverantörsregister med sök, favoriter ★, export till CSV/JSON. / Supplier register with search, favourites ★, CSV/JSON export.
- Räknar ihop **Fakturor (+)**, **Krediter (−)** och **ATT BETALA**. / Totals **Invoices (+)**, **Credits (−)** and **TO PAY**.
- Exporterar en PDF med betalningsdatum och bankgiro. / Exports a PDF with payment date and bankgiro.

Datum väljs vid export, inte vid start. / The date is chosen at export time, not at startup.

## Starta på Windows

1. Lägg hela mappen där du vill, till exempel `D:\Program\Fakturabunten`. Sökvägen spelar ingen roll.
2. Saknas Python: kör `Installera senaste Python.bat` en gång. Den installerar senaste stabila Python på datorn.
3. Starta `main.pyw`, eller genvägen `Fakturabunten.lnk` som skapas vid första starten.

Saknade Python-paket hämtas vid start, bara om de behövs.

## Tester / Tests

```bash
python tests/test_core.py        # eller: pytest tests/
```

## Licens / Licence

Ingen öppen licens är vald.

Fritt att använda. Inte fritt att kopiera, ändra eller sälja vidare.
Donation är frivillig. / Free to use. Not free to copy, modify or resell. Donations are voluntary.

© 2026 Rickard Längkvist
