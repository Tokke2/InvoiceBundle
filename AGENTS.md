# AGENTS.md — Fakturabunten (läs mig först)

Denna fil samlar **alla hårda regler på ett ställe**. Varje agent (och
människa) som arbetar i detta repo läser den först och följer den.
Reglerna är inte förhandlingsbara. Detaljer och bakgrund:
`ARBETSREGELER.md` + `docs/FORSLAG-SYSTEM.md`.

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
