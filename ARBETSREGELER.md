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
