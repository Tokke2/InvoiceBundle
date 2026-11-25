# Fakturabunten — hårda arbetsregler

Dessa regler gäller alltid för alla som utvecklar Fakturabunten
(människor, AI-agenter, skript). De är inte förhandlingsbara.

## 1. Endast EN arbetsbranch — arbeta endast emot den

* Repot har exakt **en** aktiv arbetsbranch: `arena/be184218-invoicebundle`.
* Alla ändringar — kod, design, ikoner, testfixar, dokumentation —
  commitas och pushas **endast** till den branchen.
* Inga nya arbetsbrancher skapas. Gamla arbetsbrancher raderas när
  deras innehåll finns i den aktiva branchen.

## 2. Jobba aldrig emot `main` — hård regel

* `main` är **endast** en frusen referens/bas. Inga commits, merges,
  force-pushes eller rebases mot `main` någonsin, inte heller
  "småfix" eller hotfixar.
* Om något måste baseras om baseras det **från** `main` **till**
  arbetsbranchen — aldrig åt andra hållet.

## 3. Särskilt vid appuppdateringar

* Uppdateringar (nya funktioner, buggfixar, versionshöjningar,
  releasebyggen) paketeras och pushas **endast via arbetsbranchen**.
* Uppdaterarens källor i appen (`plugins/updater.py`,
  `.github/workflows/release-integrity.yml`) ska peka på GitHub
  Releases — aldrig på ett direkt utcheck av `main`.
* En release byggs alltid från en tagg som pekar på en commit i
  arbetsbranchen (verifieras av release-workflownet), aldrig från
  `main`-spetsen.

## 4. Kvalitetsgrind före push

* `pytest` ska vara grönt ( eller oförändrat fel läge i miljöer med
  kända systembegränsningar, t.ex. saknad `libGL`).
* `py_compile` på alla ändrade Python-filer.
* CHANGELOG.md uppdateras (svenska + engelska) för varje användbar
  ändring.

## 5. Förslagssystemet — varje 10:e chattbesked ger 10 nya förslag

* Räknaren står i `docs/forslag_status.json` och ökas vid varje
  nytt användarbesked.
* Vid besked 10, 20, 30 … levereras **10 nya förslag i chatten**,
  sparade i `docs/FORSLAG-BATCH-<n>.md`, med **nya ID:n som aldrig
  återbrukar** tidigare levererade förslag (register: `used_proposal_ids`).
* Batch 1 (ID 1–25) finns i `docs/25-NYA-FORSLAG.md` och är låst.
  Fullständiga driftinstruktioner: `docs/FORSLAG-SYSTEM.md`.

## 6. Releasen är alltid aktuell — uppdateras vid varje kodförändring

* Varje push med kodförändring till arbetsbranchen (eller `main`)
  **måste** resultera i en uppdaterad release: workflow-jobbet
  `publish-latest-release` bygger paketet, pekar taggen `latest`
  på nya commiten, laddar upp `InvoiceBundle-latest.zip`
  (`--clobber`) och **markerar releasen som latest**.
* Appen jämför **alltid via updatern**: `check_for_update()`
  hämtar `releases/latest`, jämför taggens commit-sha mot lokal
  `build_info.json` och erbjuder uppdateringen. Versionnumret är
  kosmetiskt — **filändringar upptäcks via sha**, aldrig versionsnummer.
* v*-taggade releases rörs aldrig av den rullande releasen;
  taggtriggern godtar bara `v*` (ingen publikationsloop).
* Bygg-paketet verifieras (CRC, build-sha, manifest) **före**
  publicering — en underkänd build får aldrig markeras som latest.
