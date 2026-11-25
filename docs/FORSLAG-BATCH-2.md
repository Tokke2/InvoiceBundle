# Förslag batch 2 — ID 26–35 (levererat vid besked 10)

Nya funktioner i batch-1-andan: **lokal-först, automatisering,
svenska nischregler**. Inga återbruk — ID 1–25 är låsta i
`docs/25-NYA-FORSLAG.md`.

## 26. ROT/RUT-vakt med automatisk gränsräkning

- **Vad:** Per kund räknar appen automatiskt ROT-/RUT-avdraget
  (30/50 % av arbetskostnaden), varnar i förväg när en kunds
  deklarationsår närmar sig ROT-gränsen och samlar kvartalsvis i ett
  Skatteverket-underlag. Varning med ikonerna `shield_check`/`percent`.
- **Varför användare vill det:** ROT-räknaren är notoriskt krånglig —
  överskjuten gräns innebär personligt betalningsansvar för
  hantverkaren. Ingen vill räkna manuellt i Excel.
- **Varför konkurrenterna saknar det:** Stora affärssystem bor i
  molnet och hanterar ROT som efterhandsrapport; de gränsvarnar inte
  per kund i fakturablicken. Lokal app = ingen data lämnar datorn.

## 27. Kvittoterminal (58/80 mm utskrift på plats)

- **Vad:** Vid betalning på plats genereras ett kvitto lokalt i
  58/80-mm-format (skrivare eller som PDF) med OCR-nummer,
  mottagarsignaturfält och "tack för köpet"-rad.
- **Varför användare vill det:** Smallarmörer, städare och
  hantverkare som tar swish/kort på plats behöver ett kvitto nu —
  inte en faktura om 30 dagar.
- **Varför konkurrenterna saknar det:** Fakturaappar fokuserar på
  A4-fakturor; kvittot kräver oftast separat kassasystem med
  månadsavgift.

## 28. SIE4-export med ett klick

- **Vad:** En knapp genererar en SIE4-fil (svensk standard för
  bokföringsimport) med verifikationer per faktura, inbetalning och
  kostnad, redo för Visma, Björn Lundén m.fl.
- **Varför användare vill det:** Redovisningskonsulterna frågar
  alltid efter SIE — idag får användaren knappa om allt manuellt.
- **Varför konkurrenterna saknar det:** Molntjänster exporterar hellre
  via betalda API-integrationer; den lilla aktören får ingen
  filväg. En lokal SIE-generator är billig och alltid fungerande.

## 29. Hyresavi & periodiserade fakturor

- **Vad:** Skapa en aviseringsserie (t.ex. 12 månader i förväg) med
  auto-numrering, automatisk OCR-variant per avi, paus/återuppta och
  automatisk sändlista vid månadsskiftet.
- **Varför användare vill det:** Småhyresvärdar som uthyder enstaka stugor skriver
  idag 12 identiska fakturor för hand varje år.
- **Varför konkurrenterna saknar det:** Avisering ligger hos
  specialsystem (t.ex. hyresadministration) med hyreshusfokus; en
  lätt avi-serie i fakturaappen finns sällan för micro-utgivare.

## 30. Lokala e-postutkast (.eml) — ingen server

- **Vad:** "Skapa utkast"-knappen genererar en .eml-fil lokalt med
  faktura-PDF bifogad, svensk standardtext och rätt ämnesrad
  (fakturanr + OCR), öppnad i användarens eget e-postprogram.
- **Varför användare vill det:** Man vill skicka från sin egen
  inkorg (avsändarrykte, signaturer) — men slippa kopiera filer och
  skriva samma text 40 gånger.
- **Varför konkurrenterna saknar det:** Tjänster kräver SMTP-/API-
  nycklar eller skickar via egen server (leveransrisk + GDPR).
  .eml-vägen är gratis, offline och spårar ingen.

## 31. Fakturahälsa — obligatoriska fält före utskick

- **Vad:** Före utskick kontrolleras de svenska obligatoriska fälten:
  organisationsnummer, F-skatt-markering, momsregistrering,
  korrekt OCR-format (mod 10), clearingsnummer-format, rot-/rut-
  deklaration. Saknas något visas en lista med direkthopp till fältet.
- **Varför användare vill det:** En faktura som avslås av kundens
  bokföringsavdelning ger 30+ dagars försening. Kontrollen fångar 90 %
  av returen-orsakerna innan den lämnar huset.
- **Varför konkurrenterna saknar det:** De validerar bara "fälten är
  ifyllda", inte svenska formatregler (mod 10-OCR, clearing, F-skatt)
  — och visar sällan var felet sitter.

## 32. Auto-kategorisering av kostnader från egen historik

- **Vad:** När en kostnad importeras föreslår appen kategori utifrån
  användarens tidigare val för samma leverantör/ord ("du placerar
  normalt denna i Material") — helt lokalt, med en-klick-bekräftelse.
- **Varför användare vill det:** Kategorisering är den mest repetitiva
minuten i bokföringen; ett förslag som blir rätt 90 % av tiden sparar
  timmar varje månad.
- **Varför konkurrenterna saknar det:** AI-kategorisering skickas till
  molnet (kostnad, integritet, krångel). En frekvensbaserad lokal modell
  kräver ingen integration och lär sig bara av din egen historik.

## 33. PIN-lås & automatisk tidslåsning

- **Vad:** Snabb 4–6-siffrig PIN låser appen (Ctrl+L), med valfri
  automatisk låsning efter X minuter på delad dator. Allt lagras
  lokalt (hashad PIN) — ingen molnkontroll.
- **Varför användare vill det:** På en delad kontors- eller
  hembrygga vill man inte att fakturalistan är öppen för alla.
- **Varför konkurrenterna saknar det:** Molntjänster litar på
  kontoinloggning; desktop-appar släpper ofta rätt in i databasen vid
  start. Lås mellan "app igång" och "data läsbart" saknas.

## 34. Tryckklar kvartals-/årssammanställning

- **Vad:** En PDF-sammanställning per kvartal/år: topp 10 kunder,
  betalningsstatistik, mini-grafer per månad och ROT-/RUT-sammanfattning
  — genererad lokalt med befintlig PDF-stack, redo att ge revisorn.
- **Varför användare vill det:** Revisorn vill ha en översikt — inte 400
  lösa PDF:er. En sida att skriva ut räcker för 80 % av microföretag.
- **Varför konkurrenterna saknar det:** Dashboard i appen ja, men en
  **tryckklar** en-sidas-sammanställning är sällsynt — och kräver
  precis den layout-typning (REQ-K4) som är appens styrka.

## 35. USB-speglar & flytta-dator-wizard

- **Vad:** Automatisk daglig spegel av data + arkiv till vald USB-mapp
  (hashverifierad, respekterar 7-dagarsretentionen) plus en wizard som
  flyttar hela installationen till ny dator med verifierad integritet.
- **Varför användare vill det:** Laptop byts, disk dör — "var är mina
  fakturor?" ska vara en 2-minutersfråga, inte en katastrof.
- **Varför konkurrenterna saknar det:** Molntjänsternas svar är
  "logga in i molnet igen". En hashverifierad, offline migration
  utan konton är unik för lokal-först-appar.

## Prioritering (förslag)

| Prio | ID | Motivering |
|---|---|---|
| P1 | 26, 31, 28 | Svenska nischregler + sparas timmar direkt; ROT-risk och SIE är återkommande smärtpunkter |
| P2 | 35, 30, 33 | Trygghet och väg-friction; bygger på färdiga delar (arkiv-hash, ikoner, settings) |
| P3 | 27, 29, 32, 34 | Starkt värde för smala nischer; snygga att bygga mot slutet av kön |
