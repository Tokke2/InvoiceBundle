# Fakturabunten — varumärke och logotyp

Här ligger appens ikon och logotyp som **vektorgrafik (SVG)**. Filerna är
skapade för både skärm och tryck: inga inbäddade typsnitt, inga rasterbilder —
bara banor och färgplattor, så de kan skalas hur stort som helst utan att bli
suddiga och öppnas direkt i Illustrator, Inkscape, Affinity Designer, Figma
eller Scribus.

## Filer

| Fil | Användning |
| --- | --- |
| `fakturabunten-ikon.svg` | Själva ikonen (512 × 512, rundade hörn). Samma motiv som `app_icon.png` / `app_icon.ico`. |
| `fakturabunten-ikon-tryck-bleed.svg` | Ikonen med **5 mm bleed** runt om (604 × 604 enheter) för tryck. Beskär till 512 × 512. |
| `fakturabunten-ikon-monokrom.svg` | Enfärgad silhuett för systemfält/menylinje (macOS maskar den själv). |
| `fakturabunten-logotyp.svg` | Liggande logotyp: ikon + ordbild + underrad. **Ljus bakgrund.** |
| `fakturabunten-logotyp-mork-bakgrund.svg` | Samma logotyp för mörk bakgrund (vit ordbild, gul underrad). |
| `fakturabunten-logotyp-svartvit.svg` | Helt svart/vit — för gravering, stämpel, fax, en färg i tryck. |

Appens egna filer i roten (`app_icon.svg`, `app_icon.png`, `app_icon.ico`,
`app_icon_tray.png`) är byggda från samma motiv: `app_icon.svg` är en kopia av
`fakturabunten-ikon.svg`, PNG/ICO är renderade i 1024/256 px och
`app_icon_tray.png` är den monokroma varianten.

## Färger

| Roll | Hex | Används till |
| --- | --- | --- |
| Marinblå (primär) | `#16305a` | Ikonens platta, ordbildens färg i appen |
| Marinblå djup | `#12284b` | Ordtext på ljus bakgrund |
| Guld (accent) | `#e0a526` | Bandet runt fakturabunten |
| Guld ljus | `#f0c24a` | Underrad på mörk bakgrund |
| Papper | `#ffffff` | Fakturaarket |
| Pappersskugga | `#c6d8ee` / `#e4eefb` / `#cbdcef` | Bakre ark, mittenark, vikt hörn |

## Typografi

Ordbilden är ritad ur **Poppins SemiBold** (600) med +0,4 % spärrning, och
underraden ur **Poppins Regular** (400) med +26 % spärrning. Bokstäverna är
omvandlade till banor, så filerna kräver **inget installerat typsnitt**.
Poppins är licensierat under SIL Open Font License 1.1 — fri att använda i
logotyp, tryck och app.

## Regler

- Använd alltid SVG-filerna när du kan; PNG/ICO finns bara för operativsystem
  och program som kräver rasterbilder.
- Behåll luften runt märket: minst höjden på ett "F" på alla sidor.
- Skala proportionellt — sträck aldrig ut logotypen.
- Byt inte färger mot andra än de i tabellen. På fotografier används den
  svartvita varianten eller en vit platta bakom.
- Ikonen får beskäras till rundade hörn men aldrig så att guldbandet eller
  bocken skärs bort.
- Minsta storlek: ikonen 16 px (skärm) / 8 mm (tryck), liggande logotyp
  120 px bred (skärm) / 30 mm (tryck).

## Tryck

Tryckfilen `fakturabunten-ikon-tryck-bleed.svg` har 5 mm bleed runt den
56 mm stora ytan. Bakgrunden är en sluten yta ända ut i bleed-kanten, så
ingen vit kant uppstår vid beskärning. Guldet (`#e0a526`) ligger inom
CMYK-färgrymden; för exakt tryckmatchning rekommenderas en provtryckning
eller konvertering till den tryckeriets ICC-profil.
