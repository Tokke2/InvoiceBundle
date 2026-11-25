# Förslagssystemet — 10 nya förslag varje 10:e chattbesked

## Regeln (hård)

Varje **10:e användarbesked** i en chattsession utlöser en
**förslagslista med 10 nya förslag** som **aldrig återbrukar**
tidigare levererade förslag. Därefter upprepas det: besked 10, 20,
30, 40 … ger en ny lista varje gång.

## Drift (så opererar agenten systemet)

1. **Räkna besked.** Filen `docs/forslag_status.json` är den
   maskinläsbara räknaren. Vid varje nytt användarbesked ökas
   `user_messages_so_far` med 1 (beskedet som just kom in).
2. **Milstolpe?** Om `user_messages_so_far == next_milestone`
   (dvs. 10, 20, 30 …):
   - ta fram **10 nya förslag** med ID:n `next_proposal_id` och
     framåt (t.ex. batch 2 = ID 26–35),
   - leverera listan **i chatten** och spara den i en ny fil
     `docs/FORSLAG-BATCH-<n>.md` (samma format som batch 1:
     Vad / Varför användare vill det / Varför konkurrenterna
     saknar det + prioritering),
   - utöka `used_proposal_ids`, öka `next_batch_id` och
     `next_proposal_id`, och sätt `next_milestone` till nästa
     milstolpe,
   - commita och pusha till arbetsbranchen enligt
     `ARBETSREGELER.md`.
3. **Ingen återbruk.** Ett förslag-ID levereras exakt en gång.
   Batch 1 (ID 1–25) ligger låst i `docs/25-NYA-FORSLAG.md`.
   Nya förslag ska dessutom inte bara omformulera gamla — de ska
   vara **nya funktioner** i samma anda: lokal-först, automatisering,
   svenska nischregler.

## Levererade batcher

| Batch | ID:n | Levererat vid besked | Fil |
|---|---|---|---|
| 1 | 1–25 | 2 | `docs/25-NYA-FORSLAG.md` |
| 2 | 26–35 | 10 | `docs/FORSLAG-BATCH-2.md` |

## Status just nu

`user_messages_so_far = 10` → nästa lista vid **besked 20**
(10 besked kvar), därefter besked 30, 40 …
