# Runde 4 – Candidate 4 auf v6-Holdout abgelehnt (2026-07-13)

## Freeze-Disziplin

- Candidate: `evaluation/CANDIDATE_V4.json`
- Candidate-SHA256: `9e34eba47caaa8694e6f02af0a749a314c34998cbbc138dbe45968c89ac2692b`
- Der Candidate wurde vor jeder v6-Holdout-ASR-Ausführung eingefroren.
- Alle im Freeze hinterlegten Implementierungs-Hashes wurden vor dem Holdout geprüft.
- Der v6-Holdout gilt nach dieser Runde als verbranntes Diagnoseset und darf nicht mehr als
  unabhängige Abnahmebasis verwendet werden.

## Ausgangs- und Candidate-Metriken

| v6-Holdout | Base WER | Candidate WER | relative Änderung | Base CER | Candidate CER | relative Änderung |
|---|---:|---:|---:|---:|---:|---:|
| Clean | 0,85567 | 0,24742 | −71,08 % | 0,26546 | 0,07391 | −72,16 % |
| Intercom | 0,85567 | 0,21649 | −74,70 % | 0,24284 | 0,07994 | −67,08 % |

Die relative Verbesserung und beide CER-Grenzen bestehen. Die vorab festgelegte absolute synthetische
WER-Grenze `<= 0,20` wird auf Clean und Intercom verfehlt.

## Kritischer Safety-Befund

Mehrere kurze Safety-Kommandos werden bedeutungsverändert erkannt. Alle kurzen Ergebnisse tragen
korrekt `requires_confirmation=true`; dies ist eine wichtige betriebliche Sicherung, erfüllt aber nicht
das strengere Null-Fehler-Erkennungsziel.

Besonders auffällig ist der Clip mit Referenz `Energiezufuhr trennen`. Turbo, Full Large-v3 und Small
liefern selbst mit dem exakt vorgegebenen Zielprompt drei verschiedene unsinnige Lautfolgen. Das ist
starke Evidenz für eine fehlerhafte beziehungsweise unnatürliche TTS-Realisierung, aber ohne menschliche
Hörprüfung kein endgültiger Beweis. Der Fehler wird nicht durch eine testspezifische Textkorrektur
kaschiert.

## Entscheidung

**Candidate 4 abgelehnt.** Produktcode und Confirmation-Workflow bleiben wertvolle Verbesserungen, aber
Candidate 4 ist keine finale Abnahmeversion.

## Nächste Runde

1. Neue v7 Dev/Holdout-Suite mit neuem Seal; v6 nicht wiederverwenden.
2. Vorab versionierter, produktionsseitig konfigurierbarer Safety-Kommandokatalog.
3. Dev und Holdout verwenden getrennte Stimmen/Raten/Audios; bekannte zulässige Safety-Intents dürfen
   als Katalogeingabe vorliegen, die Holdout-Aufnahmen bleiben unbekannt.
4. Synthetische Kurzclips benötigen eine Ausspracheprüfung. Cross-Model-Diagnostik darf Defekte
   markieren, ersetzt aber keine menschliche Hörfreigabe.
5. Offene Diktate und geschlossener Safety-Command-Mode werden getrennt ausgewertet.
6. Erst nach Dev-Erfolg neuer Candidate-Freeze und einmaliger v7-Holdout.

## Ergebnisdateien

- `evaluation/results/holdout_baseline_base_synthetic_v6_clean_20260713.json`
- `evaluation/results/holdout_baseline_base_synthetic_v6_intercom_20260713.json`
- `evaluation/results/holdout_candidate_v4_synthetic_v6_clean_20260713.json`
- `evaluation/results/holdout_candidate_v4_synthetic_v6_intercom_20260713.json`
- `evaluation/results/burned_diagnostic_v6_intercom_safety_catalog_prompt_20260713.json`
