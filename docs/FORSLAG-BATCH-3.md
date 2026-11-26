# Förslag batch 3 — ID 36–45 (levererat vid besked 20)

Nya funktioner i batch-1-andan: **lokal-först, automatisering,
svenska nischregler**. Inga återbruk — ID 1–35 är låsta
(`docs/25-NYA-FORSLAG.md` + `docs/FORSLAG-BATCH-2.md`).

## 36. PEPPOL/Svefaktura-utskick (BIS 3.0)

- **Vad:** Utgående fakturor kan som alternativ exporteras som
  PEPPOL BIS 3.0 / Svefaktura-XML utöver PDF — helt lokalt genererad,
  validerad mot schemat, redo att skickas i användarens eget flöde.
- **Varför användare vill det:** B2B e-faktura blir standardkrav i
  Sverige (offentlig sektor redan, näringslivet på väg); småföretag
  som inte vill lägga sig i en e-fakturatjänst behöver en filväg.
- **Varför konkurrenterna saknar det:** Molntjänster säljer
  e-fakturering som prenumeration via egen växel; en lokal,
  standardkompliant XML-generator utan månadskostnad är sällsynt.

## 37. Valuta vid registrering + lokal kurstabell

- **Vad:** Fakturor i EUR/USD/NOK/DKK registreras i egen valuta med
  belopp i SEK sparat enligt en **lokal** kurstabell (dagligen uppdaterad
  fil eller manuellt); momsredovisningen räknas alltid i SEK.
- **Varför användare vill det:** Importföretag och gränshandlare får
  utländska fakturor idag och räknar om för hand.
- **Varför konkurrenterna saknar det:** Molnsystem kör live-kurser
  via API (kräver uppkoppling + prenumeration); en lokal kurstabell
  utan nät krav passar lokal-först-principen.

## 38. Momsprocent-dubbelkontroll per rad

- **Vad:** Vid registrering kontrolleras att varje momsrad (25/12/6 %)
  stämmer med radsbeloppet, att summan moms = belopp × procentsats och
  att totalen går ihop — avvikelser markeras före utskick.
- **Varför användare vill det:** Fel momsprocent är den vanligaste
  bokföringsbyxan och den dyraste (upprepade deklarationsjusteringar).
- **Varför konkurrenterna saknar det:** De räknar moms på raden men
  kontrollerar sällan **baklänges** mot angiven procentsats och
  summerar inte raderna mot sluttotalen i samma vända.

## 39. Bilagsmapp per faktura

- **Vad:** Varje faktura kan ha extra bilagor (kvitton, mejl, kontrakt,
  leveranssedlar) i en egen undermapp per faktura; exporten kan sammanställa
  original + bilagor i en PDF med bokmärken per bilaga.
- **Varför användare vill det:** Revisor begär "allt som hör till
  fakturan" — idag sparar användaren bilagor utspridda i Utforskaren.
- **Varför konkurrenterna saknar det:** Affärssystem binder bilagor
  i databasen med storleksbegränsningar; en **filbaserad** bilagsmapp
  som följer fakturan är lokal-först och aldrig låst.

## 40. Kalenderexport (.ics) av betalningsplan

- **Vad:** "Lägg i kalender"-knapp genererar en .ics-fil med kommande
  förfallodatum (som användaren kan prenumerera på i Outlook/Google/
  Apple Kalender) — uppdateras vid varje export.
- **Varför användare vill det:** Kalendern är där användaren redan
  lever; att betalningar dyker där automatiskt slår av "kolla appen".
- **Varför konkurrenterna saknar det:** De vill behålla användaren i
  sin app/push-notiser; en öppen filstandard som ger datat till
  ANVÄNDARENS kalender är ovanlig i den segmentet.

## 41. Kundbetalningsbetyg (A–E)

- **Vad:** Per kund räknar appen betalningsbetyg (A = betalar i tid,
  E = återkommande försenad) från historiken; betyget visas i
  registrering och varnar innan ny kreditering av dåliga betalare.
- **Varför användare vill det:** Vilka kunder betalar sent är
  affärskritisk kunskap som idag kräver manuell historikgranskning.
- **Varför konkurrenterna saknar det:** Kreditupplysningstjänster
  kostar per uppslag och täcker inte ens små kunder; inbyggd betyg
  från EGEN historik är gratis och mer sann (den mäter faktiskt).

## 42. Utkast-återställning — halvfärdiga registreringar överlever

- **Vad:** En halvfärdig registreringsdialog (fält ifyllda men ej
  sparade) sparas automatiskt som utkast; efter krasch/omstart/ström-
  avbrott frågar appen "fortsätt där du var?".
- **Varför användare vill det:** Att tappa 20 ifyllda fält för att
  Windows startade om är den enskilt mest förargliga databortgången.
- **Varför konkurrenterna saknar det:** Webbappar räddar sessionen i
  molnet; desktop-appar tappar form-state vid oväntat avslut i princip
  alltid.

## 43. Betalningsvillkors-bibliotek per kund

- **Vad:** Per kund sparas villkor (10/30/60 dagar, "den 25 i
  månaden", "förskott") och förfallodatum beräknas automatiskt vid
  registrering — med svensk helg-/storhelgsjustering (förfaller
  aldrig på röda dagar).
- **Varför användare vill det:** Att räkna 30 dagar + helg i huvudet
  är felkällan nr 1 vid utskick; villkoren varierar per kund.
- **Varför konkurrenterna saknar det:** De har fasta globala
  villkor; per kund + svenska helgdagsregler (midsommar!) är nischat
  som molnsystem inte lägger kraft på.

## 44. Lösenordsskyddad export-PDF

- **Vad:** Betal-/export-PDF:en kan (valfritt) krypteras med ett
  lösenord — praktiskt när underlaget delas via mejl till revisor
  eller kollega; lösenordet visas en gång i appen.
- **Varför användare vill det:** Fakturaunderlag med kunddata ska
  inte skickas öppet i mejl; lösenord i annat kanal är standardråd.
- **Varför konkurrenterna saknar det:** Molntjänster delar via
  länkar (i stället för filer) och skjuter över säkerheten till
  plattformen; en lokal PDF med standardskydd är ovanlig.

## 45. Veckovis datahälsorapport

- **Vad:** En gång i veckan (eller vid varje start) räknar appen
  checksummor över sina datafiler, kontrollerar att arkiv, loggar och
  exporthistorik är läsbara och visar en kort hälsorapport — avvikelser
  loggas och varnas om, allt lokalt.
- **Varför användare vill det:** Tyst filkorruption upptäcks ofta först
  när det är försent; en veckovis check ger tid att vila på backupen.
- **Varför konkurrenterna saknar det:** Molnsystem gör integritet på
  servern osynligt; en lokal app som själv redovisar sin datahälsa
  är unik och kräver bara hash + läsbarhetskontroller.

## Prioritering (förslag)

| Prio | ID | Motivering |
|---|---|---|
| P1 | 36, 38, 37 | PEPPOL-tidsrygg i Sverige, momsfelet är dyrast, valuta räknas om för hand idag |
| P2 | 39, 40, 41, 42 | Bygger på färdiga delar (bilagor→export, betalplan→ics, historik→betyg, utkast→auto-spara) |
| P3 | 43, 44, 45 | Nyskapande men smalare; enkla att bygga mot slutet av kön |
