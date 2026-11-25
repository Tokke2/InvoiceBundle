# 25 nya förslag — funktioner konkurrenterna saknar

Fakturabunten är **lokal-först**: all data och all bearbetning finns på
användarens egen disk, ingen molntjänst krävs, ingen prenumeration. Det
är själva konkurrensfördelen mot Fortnox, Visma eEkonomi, Björn Lundén, Fakturoid
och Zervant — som alla är molntjänster med abonnemang, inloggningskrav
och data utanför användarens kontroll. Varje förslag nedan utnyttjar
den fördelen: antingen **automatisering som molntjänsterna inte kan erbjuda per användare** (OCR + själv lärande
mallar som molntjänsterna inte kan erbjuda per användare), **trygghet
genom lokaldata** eller **svenska nischregler** som de stora plattformarna
generaliserar bort.

Gruppering: **A. Automatisering & AI (1–8), B. Betalning & bank (9–14),
C. Trygghet, arkiv & efterlevnad (15–19), D. Hastighet,
tillgänglighet & design (20–25).**

---

## A. Automatisering & AI

### 1. Offline-AI-klassificering av obekanta fakturor
**Vad:** Valfritt nedladdat litet språkmodellpaket som körs helt lokalt
och föreslår leverantör, fakturanummer, OCR och belopp på fakturor där
mallarna misslyckas — med konfidensgrad per fält.
**Varför användare vill det:** Idag kräver första fakturan från en ny
leverantör manuell mallbyggnad. Auto-förslag slår 80 % av det arbetet.
**Varför konkurrenterna saknar det:** Fortnox/Visma klassificerar i moln
(och skickar då användarens fakturor till extern server). En app som
kör AI:n **på användarens egen disk** finns i princip inte.

### 2. Mallhälsoindex per leverantör
**Vad:** Poäng 0–100 per mall baserat på träffprocent senaste 30 dagar,
antal manuella korrigeringar och mallvarianter i bruk — plus ett
konkret "förbättra"-förslag (t.ex. "logotypmarkeringen täcker bara
1 av 3 sidor").
**Varför användare vill det:** Man ser på vilka mallar som är trötta
innan de börjar missmatcha — i stället för att upptäcka det via fel.
**Varför konkurrenterna saknar det:** Molntjänsterna har inga
användarskapade mallar alls; de har inget att mäta hälsan på.

### 3. Duplikatvakten vid import
**Vad:** Hash-register (leverantör + OCR + belopp + fakturanummer) som
larmar i samma sekund en dubblett skannas/importeras — även månader
senare och även när filen bytt namn.
**Varför användare vill det:** Dubbelbetalningar och dubbelbokföring
står högst på fel-listan för småföretagare.
**Varför konkurrenterna saknar det:** Dubblettkontrollen sker oftast först i
bokföringen — inte vid skanna/importhändelsen, där fel bör stoppas.

### 4. Prisdriftslarm per leverantör
**Vad:** Statistik över fakturabelopp per leverantör; varning när
beloppet avviker mer än vald procentsats från glidande medelvärde
("Elektrikern har höjt 23 % sedan förra kvartalet").
**Varför användare vill det:** Prisjakten blir synlig — underlag för
omförhandling eller leverantörsbyte.
**Varför konkurrenterna saknar det:** Leverantörsstatistik finns i
BI-moduler som kostar extra; ingen säljer den som ett passivt larm i
fakturavyn.

### 5. Leverantörsbedrägerivakt
**Vad:** Jämför bankgiro/plusgiro/IBAN på varje inläst faktura mot
historiken; larm + vägra auto-matchning när kontonummer plötsligt
ändrats ("fake invoice"-bedrägeriet som skjutit i Europa).
**Varför användare vill det:** En enda stoppad bedrägerifaktura betalar
apparna för livet.
**Varför konkurrenterna saknar det:** Kräver OCR av kontofält + lokal
historik — de stora tolkar inte ens scannede fakturor i den graden.

### 6. OCR-referensvakt (mod 10/Luhn)
**Vad:** Validera OCR-nummer mot Luhn/mod10 innan fakturan skickas
eller registreras; varna när kontrollsiffran är fel.
**Varför användare vill det:** Fel OCR-nummer = pengar som landar utan
avstämning hos mottagaren — dyrt och tidskrävande att rätta.
**Varför konkurrenterna saknar det:** De flesta e-fakturasystem
genererar OCR själva; få kontrollerar OCR som **användaren** skriver
in eller läser in via skanning.

### 7. Betalnings-QR på varje faktura-PDF
**Vad:** Svensk betalnings-QR (bankgiro/plusgiro + OCR + belopp) som
renderas på den exporterade PDF-fakturan; mottagaren skannar och får
upp allt förifyllt i Swish/bankappen.
**Varför användare vill det:** Snabbare inbetalningar = kortare
betalningstider och färre "jag betalade, men fel OCR"-mail.
**Varför konkurrenterna saknar det:** QR-fakturor syns mest hos banker;
fakturaprogrammen renderar sällan betal-QR på PDF:en ännu.

### 8. Kontrollstreck för mallträff — "varför matchade den inte?"
**Vad:** Klick på en omatchad rad visar exakt vilka OCR-crop-zoner som
testats, vilka som träffade och vilka som missade, med ikoner per zon.
**Varför användare vill det:** Felsökning av mallar blir
självinstruerande i stället för gissningslekt.
**Varför konkurrenterna saknar det:** Ingen annan app låter användaren
bygga egna OCR-zonmallar — och kan då förstås inte visa dem heller.

## B. Betalning & bank

### 9. Bankutdragsavstämningsmotor (filbaserad)
**Vad:** Dra in bankutdrag som CSV/MT940/camt.053 (export från valfri
svensk bank) och matcha mot öppna fakturor: OCR-normalisering,
belopptolerans (ränta/avgift), datumfönster — med kö av förslag och
konfidensnivå.
**Varför användare vill det:** "Är allt betalt?" ska vara en knapp,
inte kvällens grävarbete.
**Varför konkurrenterna saknar det:** De kräver PSD2-bankkoppling med
inloggning till banken. Filbaserad avstämning utan bankinloggning
ger samma resultat, 100 % offline, och fungerar med **alla** banker.

### 10. Kvittningsförslag: kredit ↔ faktura
**Vad:** Auto-matchning av kreditfakturor mot originalfakturor
(belopp/subtraktion/datum) med förslag och en-klick-kvittning,
inklusive delkvittning.
**Varför användare vill det:** Kreditfakturor är kirurgiskt tråkiga att
kvitta manuellt; felet är att lämna resterande saldo fel.
**Varför konkurrenterna saknar det:** Kreditkvittning finns i bokföringspaketen
men styrs sällan av förslag — användaren får räkna själv.

### 11. Samlad betalorder
**Vad:** Markera flera fakturor → exportera en samlad betalorder i
bankens filformat (eller samlad OCR-sträng) sorterad efter
förfallodatum.
**Varför användare vill det:** Betala veckans fakturor på 2 minuter i
stället för 15 enskilda inmatningar.
**Varför konkurrenterna saknar det:** Betalfil-export (LUB/ISO20022)
säljs som tillägg; i en lokal app är det bara ytterligare en exporterare.

### 12. Kassaprognos vecka för vecka
**Vad:** "Kommer kassan räcka?" — prognosvy som kombinerar planerade
utbetalningar (förfallna + kommande) med förväntade inbetalningar,
vecka för vecka, med varning när saldot riskerar att ta slut.
**Varför användare vill det:** Likviditetshot upptäcks 3 veckor för
tidigt i stället för 3 dagar för sent.
**Varför konkurrenterna saknar det:** Likviditetsvyer finns i
ekonomipaketen men kräver att ALLT bokförs där; här räcker
fakturadata som appen redan har.

### 13. Påminnelsemotor enligt svensk rätt
**Vad:** Auto-genererade påminnelser med villkorlig delsumma, laglig
dröjsmålsränta (referensräntan + 8 %-enheter hämtad/auto-uppdaterad)
och spårbar PDF-kedja.
**Varför användare vill det:** Att driva in obetalda fakturor korrekt
kräver exakt ränta och ordning — svårt att hålla reda på manuellt.
**Varför konkurrenterna saknar det:** Kräver inkassotillstånd-integration
och är därför oftast outsourcat; en lokal motor som _förbereder_
(men inte skickar via nät) är ovanlig.

### 14. "Att betala idag"-panel med en-klick-OCR
**Vad:** Dashboard-panel som listar exakt vad som måste betalas idag/
imorgon, sorterat, med kopiera-OCR- och kopiera-bankgiro-knappar direkt
på raden.
**Varför användare vill det:** Kärnfrågan i appen ("vad ska jag betala?")
svarad på en yta, utan tabellnavigering.
**Varför konkurrenterna saknar det:** Statusraden "Att betala" är redan
unik för Fakturabunten; panelen tar den logiken till nästa steg.

## C. Trygghet, arkiv & efterlevnad

### 15. 7-års bokföringsarkiv med lås och hashmanifest
**Vad:** Autoarkivering av varje kvitterad/arkiverad faktura som PDF/A
med SHA-256-manifest och valfri låsning — ändring av arkiverad fil
larmar omedelbart (integritetsverifikation i appen).
**Varför användare vill det:** Bokföringsnämndens 7-årsregel uppfylld
automatiskt, med bevisbar integritet mot revisor.
**Varför konkurrenterna saknar det:** Molntjänsterna arkiverar internt
men kan inte ge användaren en **lokal, verifierbar** arkivstruktur som
överlever deras eget bolag.

### 16. Krypterad säkerhetskopiering vid avslut
**Vad:** AES-256-krypterad zip av hela datakatalogen till valfri mapp
(USB/nätverksdisk) vid appavslut, med rotationspolicy och
återställningswizard.
**Varför användare vill det:** "Datorn dog" är den vanligaste
datorkatastrofen; återställning ska vara guidad, inte teknisk.
**Varför konkurrenterna saknar det:** Molnen har backup inbyggd — men
då är datan också hos molnet. Lokal krypterad backup är fördelen.

### 17. Revisorspaket med ett klick
**Vad:** En-klick-export: zip med alla faktura-PDF:ar för perioden,
verifikationslista, momsrapport, bankavstämningsrapport och
hashmanifest — filnamnskodad och klar att maila.
**Varför användare vill det:** Bokslutstid = massutskick till revisorn;
paketering idag är handarbete.
**Varför konkurrenterna saknar det:** De vill hellre att revisorn loggar
in i deras moln. En revisor som vägrar moln (vanligt!) har inga alternativ.

### 18. Momsrapport direkt till deklarationsunderlaget
**Vad:** Kvartalsvis sammanställning av ingående/utgående moms med
svenska momssatser (25/12/6 %), avstämning mot fakturadatum-perioder
och utskriftsunderlag i deklarationsordning.
**Varför användare vill det:** Momssammanställningen är bokföringens
återkommande skräck; gjort av datan appen redan läser in.
**Varför konkurrenterna saknar det:** Finns i bokföringsmoduler — men
kräver att användaren bokför i systemet. Här genereras den ur själva
fakturaflödet.

### 19. Känslighetsläge (privacy blur)
**Vad:** Ett kortkommando som suddar belopp, kontonummer och personnummer
i hela UI:t (halvtransparenta kakelrutor) vid skärmdelning/support —
av-blur kräver knappen, inte musens position.
**Varför användare vill det:** Remote-support, skärmdelade möten och
demonstrationer idag riskerar att läcka kunddata.
**Varför konkurrenterna saknar det:** Finns knappt ens i molnsystemen;
de utgår från att ingen delar skärm med bokföring öppen.

## D. Hastighet, tillgänglighet & design

### 20. Kommandopalett (Ctrl+K)
**Vad:** En sökruta över alla kommandon, fakturanummer, leverantörer
och statusåtgärder — piltangenter + Enter kör. Recent-sida lär sig
användarens vanor.
**Varför användare vill det:** Erfarna användare vill aldrig
klicka genom menyer; nybörjare hittar funktioner de visste fanns.
**Varför konkurrenterna saknar det:** Kommandopaletter är ännu sällsynt
i svenska ekonomiappar (de finns i IDE:er och Slack — inte i ekonomiapparna).

### 21. Tangentbordsfirst-läge för hela arbetsflödet
**Vad:** Full drift utan mus: piltangenter i tabeller, mellanslag
väljer, Enter öppnar, B betalar, K kvitterar, S skannar — med
"nässta åtgärd"-indikator per rad.
**Varför användare vill det:** Volumanvändare (50+ fakturor/vecka)
skriver in allt dubbelt så snabbt som klickare.
**Varför konkurrenterna saknar det:** Webbsystemen har fläckvis
tabbnavigering; ingen har en sammanhängande tangentbordsdrift genom hela
arbetsflödet.

### 22. Färgblind-säkert statusläge (form + färg)
**Vad:** Betalningsstatusmarkeringar kompletteras med former (bock /
triangel / stjärna) och mönster, så att röd/grön/amber aldrig bär
information ensam; inställningsbara profiler (deuteranopi, protanopi,
tritanopi).
**Varför användare vill det:** Ca 8 % av män har någon färgblindhet;
statusfärger i dagens ekonomiappar är rena gissningslekt för dem.
**Varför konkurrenterna saknar det:** Tillgänglighetslägen i ekonomiappar
begränsas till textstorlek; semantisk färg ersätts nästan aldrig.

### 23. Årsvärmekalender för fakturaflödet
**Vad:** Heatmap-kalender (GitHub-graf-stil) över ankomna och betalda
fakturor per dag; klicka en dag → filtrerad lista. Månads- och
kvartalsrad i sidled.
**Varför användare vill det:** Belastningstrender och "tysta månader"
ser direkt; retrospektiv planering blir visuell.
**Varför konkurrenterna saknar det:** Diagrammen i ekonomisystemen är
stapel/cirkel; en kalenderheatmap över fakturaaktivitet finns knappast
någonstans.

### 24. Plugin-galleri inuti appen
**Vad:** Kuraterad lista av lokala plugins (repoet har redan
plugin-arkitekturen) med beskrivning, versionskompatibilitet och
en-knapp-installation från en mapp/GitHub-release — allt utan att
apparna lämnar maskinen.
**Varför användare vill det:** Appen växer med behovet utan
tungversioner; community-förslag blir installerbara.
**Varför konkurrenterna saknar det:** Plugin-ekosystem finns i IDE:er —
inte i fakturaappar; molnsystemen är stängda till sin natur.

### 25. Flerprofilsdata (företag A / företag B) med profilväljare
**Vad:** Separata, krypterat åtskilda datamängder (leverantörer, mallar,
fakturor, export) i samma installation; profilväljare i tray-menyn
med tydlig färgkant på fönstret per profil.
**Varför användare vill det:** En person driver ofta 2–3 bolag;
idag krävs separata installationer eller handplockade mappar.
**Varför konkurrenterna saknar det:** Multi-företag är premiumfunktion
med extra licenskostnad i molnsystemen; i en lokal app är det
katalogval + lås — gratis.

---

## Prioritering (förslag)

| Fas | Förslag | Motivering |
|---|---|---|
| Nu | 3, 14, 22, 25 | Liten kodbana, stor användbarhet, bygger på existerande data |
| Nästa | 1, 2, 5, 8, 16, 20 | Automationen är appens DNA; trygghet säljer |
| Senare | 7, 9, 10, 11, 12, 13, 15, 17, 18, 19, 21, 23, 24, 4, 6 | Kräver ny export/import eller gränssnitt, men ingen molninfrastruktur |

Alla förslag håller sig inom principen: **all data och bearbetning
förblir på användarens maskin**.
