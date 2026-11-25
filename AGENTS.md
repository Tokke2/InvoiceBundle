# AGENTS.md — läs mig först (anpassas efter varje app)

Denna fil samlar **alla hårda regler på ett ställe**. Varje agent (och
människa) som arbetar i detta repo läser den först och följer den.
Reglerna är inte förhandlingsbara. Detaljer och bakgrund:
`ARBETSREGELER.md` + `docs/FORSLAG-SYSTEM.md`.

**Anpassa efter varje app:** §1–8 är **universella regler** som gäller
i alla appar; **App-profilen** (sist i filen) anpassar dem till just
detta repo. Vid ny app: byt bara profilen.

## 1. Branch & merges — hård regel

* Repot har exakt **EN** arbetsbranch: `arena/be184218-invoicebundle`.
  Allt commitas och pushas **endast** dit.
* Jobba **aldrig** emot `main` — `main` är en frusen referens.
  Speciellt vid appuppdateringar.
* **Aldrig merga** — inga merge-commits, ingen sammanslagning av
  brancher eller PR:er, varken mot `main`, från `main` eller mellan
  brancher. Ändringar landar endast som vanliga commits på
  arbetsbranchen.
* Updaterarens källor (`plugins/updater.py`,
  `.github/workflows/release-integrity.yml`) pekar alltid på GitHub
  Releases (taggar) — aldrig på ett utcheck av `main`.

## 2. Release & updater — hård regel

* **Releasen ska alltid vara aktuell:** varje kodförändring (push)
  gör att CI-jobbet `publish-latest-release` bygger + verifierar
  paketet mot exakt commit-sha, pekar om taggen `latest` till nya
  commiten, laddar upp `InvoiceBundle-latest.zip` (`--clobber`) och
  **markerar releasen som latest**.
* **Appen jämför fil via updater:** `check_for_update()` jämför
  taggens commit-sha mot lokal `build_info.json` — **aldrig
  versionsnummer**. Samma version med ändrade filer = uppdatering.
* Updateraren: https-only, storlekstak, atomär nedladdning,
  `verify_release_zip`, zip-skydd, aldrig main.
* **Lyckad uppdatering → backup tas bort automatiskt.**
* **Arkiverade loggar rensas efter 7 dagar.**

## 3. 10-meddelanderegeln — förslag

* Varje **10:e användarbesked** (10, 20, 30 …) levereras **10 helt
  nya förslag i chatten** + sparas i `docs/FORSLAG-BATCH-<n>.md`.
* **Hård regel: förslaglistor ska alltid skrivas i chatten.** Filen
  är bara arkiv — en leverans utan full chattvisning bryter regeln.
  Gäller även listan "25 nya förslag som konkurrenterna saknar och
  användare efterfrågar": den visas alltid direkt i chatten.
* **Aldrig återbruk eller omformulering** av levererade ID:n.
  Räknare + ID-register: `docs/forslag_status.json` — ökas vid varje
  användarbesked och kontrolleras mot `next_milestone`.
* Batch 1 (ID 1–25, `docs/25-NYA-FORSLAG.md`) är låst.

## 4. Testkrav innan klar

* `pytest` grönt (eller oförändrat fel läge vid kända
  systembegränsningar, t.ex. saknad `libGL`).
* `py_compile` + `pyflakes` på ändrade Python-filer.
* `CHANGELOG.md` (svenska + engelska) uppdateras vid varje användbar
  ändring.
* **Inga tysta beroende- eller gränssnittsbrott:** nya beroenden,
  nya filformat och API-/kontraktsändringar ska vara explicita,
  dokumenterade och täckta av tester. Brott mot befintliga kontrakt
  (t.ex. updater-rapportens nycklar, brand-filernas namn,
  `_SVG_PATHS`-nycklar) förbjuds utan uttryckligt beslut + migrering
  + tester.

## 5. UI-mål — alltid

* Skärmanpassning: fönstret startar i **max höjd läge** beroende på
  skärm, bredden anpassas; bättre layout, allt synligt, minimera
  scroll.
* **REQ-K4 (layout — anpassad till denna app):** varje huvudyta ska
  rymmas utan överflödig scroll — fönstret startar i max höjd
  (beroende på skärm), bredden anpassas efter innehåll, alla
  funktioner synliga/nåbara, scroll minimeras via responsiva
  brytpunkter. Verifieras av testerna i
  `tests/test_ui_sharpness_and_responsiveness.py` (KPI 2×2 ≤ 920 px,
  HistoryView-stack < 820 px, responsiv verktygsrad ≤ 1024 px).
* Bättre ikoner (vektorbiblioteket `ui/icons.py`) och design.
* Skärpa: skarp HiDPI-rendering (DPR-medveten), tydlig text/font/
  bild/kolumn — aldrig grumlig.
* Bättre minneshantering, snabbare, energisnålare.

## 6. Kodkällor

* `brand/build_brand_assets.py` är **enda källan** för logotyp/märke/
  varianter — kör skriptet, redigera aldrig genererade filer direkt.
* `plugins/updater.py` och release-workflownet ändras bara tillsammans
  med uppdaterade tester.

## 7. Arbetsgång vid varje ändring

1. Läs `AGENTS.md` + `ARBETSREGELER.md`.
2. Arbeta på arbetsbranchen (aldrig main, aldrig merga).
3. Kör kvalitetsgrinden (§4).
4. Commita + pusha — CI:n uppdaterar releasen och markerar latest (§2).
5. Öka `user_messages_so_far` i `docs/forslag_status.json` vid varje
   användarbesked; leverera förslag vid milstolpar (§3).

## 8. Nya regler till GitHub direkt — hård regel

* När användaren skriver `- hård regel` eller `regel` kodifieras den
  nya regeln **omedelbart** hit (och vid behov till
  `ARBETSREGELER.md`) och **pushas till GitHub i samma vända** —
  den får aldrig bara förbli chatttext.
* Låsregler kontrolleras av `tests/test_agents_rules.py`.

## App-profil — Fakturabunten (anpassas efter varje app)

| Fält | Värde |
|---|---|
| App | Fakturabunten — lokal-först faktura-/bokföringsapp (PySide6) |
| Arbetsbranch | `arena/be184218-invoicebundle` |
| UI-mål | REQ-K4-layout (§5), HiDPI-skärpa, minne/energi |
| Kodkällor | `brand/build_brand_assets.py`, `ui/icons.py` (§6) |
| Förslagssystem | `docs/forslag_status.json` (10-meddelanderegeln, §3) |
| Release & updater | `publish-latest-release` → taggen `latest` (§2) |
| Start | pythonw + `--minimized`, aldrig terminalfönster |
