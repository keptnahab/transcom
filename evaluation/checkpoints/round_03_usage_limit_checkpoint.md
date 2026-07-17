# Runde 3 – Usage-Limit-Checkpoint (2026-07-13)

## Status

Die Arbeit ist **nicht abgeschlossen**. `CANDIDATE_V4.json` wurde bewusst noch nicht erzeugt und der
versiegelte v6-Holdout wurde weder geöffnet noch transkribiert. Der nächste Apple-Metal-Benchmark wurde
von der Plattform wegen des Usage-Limits abgelehnt. Laut Fehlermeldung ist die Ausführung ab
**2026-07-19 15:00** wieder möglich.

## Reproduzierbar erledigt

- v6 Dev/Holdout: je 16 Äußerungen, keine Textüberlappung, objektive Audio-QA bestanden.
- Holdout-Seal: `f3a6cb4f893c45efa3dc1f258fb78a0202aa5763138f9e3dc50407512aa7543d`.
- VAD-Pre-Roll kopiert keine Sprache aus einem vorigen finalisierten Segment mehr.
- Echte unmittelbare Wortwiederholungen bleiben im Timed-Word-Stabilizer erhalten.
- `requires_confirmation` wird bei Deduplizierung per OR erhalten.
- Explizite Bestätigung (`confirmation_acknowledged`) ist persistent, per WebSocket bedienbar und in
  Haupt-UI, LAN-Viewer sowie TXT/CSV-Export sichtbar.
- Segmentübergreifend getrennte Zeiten, Dezimalzahlen, Datumsangaben und technische Codes werden von
  der deutschen Zahlennormalisierung nicht mehr beschädigt.
- Kurze, an den Dateigrenzen eng geschnittene Audios erhalten interne Randpolsterung. Der zuletzt
  implementierte Stand füllt pro Seite nur die bis 0,35 s fehlende stille Reserve auf.
- Eng begrenztes, konfigurierbares Fachglossar: nur zwei benachbarte, lange und phonetisch sehr ähnliche
  Wörter dürfen zu einem explizit hinterlegten Begriff zusammengeführt werden. Release-Glossar:
  `Lastaufnahme,unterbrechen`.
- Pathology-Fallback verwendet unabhängig von benutzerdefinierten Primärmodellen das gepinnte
  `Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120`; Fallback-Fehler werden
  abgefangen und leere MLX-Ausgabe bei hörbarem Signal wird abgelehnt.
- Aktueller gesamter Testlauf: **137 passed**, eine bekannte LibreSSL-Warnung.
- Renderer-Build erfolgreich. Vollständiger Electron-Build war vor der letzten Änderung erfolgreich;
  keine Code-Signatur vorhanden.

## Letzte ASR-Messwerte

Diese Resultate wurden **vor** der allerletzten Umstellung von pauschaler auf bedarfsgerechte
Randpolsterung erzeugt. Sie sind Entwicklungsbelege, aber nicht der Freeze-Nachweis des aktuellen Codes.

| Test | WER | CER | RTF | Zusatz |
|---|---:|---:|---:|---|
| v6 Dev Intercom, direkte Clips | 0,12222 | 0,03443 | 0,12663 | alle 6 kurzen Safety-Kommandos exakt; Short-WER 0,33333 |
| v6 Dev Live-Pipeline | 0,13333 | 0,03912 | 0,11138 | First usable simuliert 2,867 s; 17 Jobs; 0 Dedupe-Replacements |

Direktes Ergebnis:
`evaluation/results/candidate_v4_final2_pre_freeze_synthetic_v6_dev_intercom_20260713.json`

Live-Ergebnis:
`evaluation/results/candidate_v4_final_pre_freeze_synthetic_v6_dev_live_pipeline_20260713.json`

Im Live-Ergebnis blieb ein bedeutungsverändernder Safety-Fehler:
`Schutzraum sofort räumen` → `Schutzraum sofort kommen`. Deshalb wurde Candidate 4 nicht eingefroren.
Die danach implementierte bedarfsgerechte Polsterung ist durch Unit-Tests, aber noch nicht durch einen
Metal-Live-Benchmark validiert.

## Verworfene beziehungsweise noch nicht angenommene Experimente

- faster-whisper Small als Primärmodell: v6 Dev Intercom WER 0,36667, klar schlechter.
- MLX Whisper Large-v3 4-bit: auf v5 Dev schlechter und langsamer als Turbo.
- Beam 5: vom verwendeten MLX-Decoder nicht implementiert.
- 0,65 s pauschale Randpolsterung: keine bessere Gesamt-WER und neue Safety-Regressionen.
- Testspezifischer erweiterter Prompt: keine WER-Verbesserung; nicht als Release-Prompt übernommen.

## Offene Risiken

1. Bedarfsgerechte Randpolsterung muss Direct, Live und Short-Latency auf v6 Dev bestehen.
2. Der Live-Safety-Fehler muss verschwinden; eine Bestätigungsmarkierung allein erfüllt das eingefrorene
   Null-Fehler-Ziel nicht.
3. Human- und Degraded-Dev müssen nach Randpolsterung/Glossar erneut auf Regression geprüft werden.
4. Aktueller Code muss vollständig gehasht und als Candidate 4 eingefroren werden.
5. Erst danach darf der v6-Holdout genau einmal ausgeführt werden.
6. Drei warme Wiederholungen, finaler Human-/Degraded-Holdout, E2E-UI inklusive Bestätigung und
   vollständiger Abschlussbericht fehlen.
7. Synthetische Referenzen und FLEURS-Metadaten sind nicht menschlich auditiv gegengeprüft. Eine
   menschliche Hör- und Datenschutzfreigabe kann durch diesen automatisierten Lauf nicht ersetzt werden.

## Exakte Fortsetzung

Arbeitsverzeichnis:

```bash
cd "/Users/macbookpro/Library/CloudStorage/Dropbox-Privat/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom"
```

1. Aktuellen statischen Stand erneut prüfen:

```bash
PYTHONPYCACHEPREFIX=/tmp/transcom-pycache backend/.venv/bin/python -m pytest -q
npm run build:renderer
```

2. Aktuelle bedarfsgerechte Randpolsterung auf v6 Dev prüfen:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_clip_suite.py \
evaluation/data/manifests/synthetic_v6_dev_intercom_v1.json --language de \
--output evaluation/results/candidate_v4_adaptive_padding_pre_freeze_synthetic_v6_dev_intercom_20260719.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python scripts/benchmark_live_pipeline.py \
evaluation/generated/synthetic_v2/dev/synthetic_de_v6-dev-001/audio/intercom.wav --warmup \
--reference-manifest evaluation/data/manifests/synthetic_v6_dev_intercom_stream_v1.json \
--db /tmp/transcom-candidate-v4-v6-dev-adaptive.db \
--output evaluation/results/candidate_v4_adaptive_padding_pre_freeze_synthetic_v6_dev_live_pipeline_20260719.json

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPYCACHEPREFIX=/tmp/transcom-pycache \
backend/.venv/bin/python evaluation/benchmark_streaming_latency.py \
evaluation/data/manifests/synthetic_v6_short_latency_dev_v1.json --language de \
--output evaluation/results/candidate_v4_adaptive_padding_pre_freeze_synthetic_v6_short_latency_dev_20260719.json
```

3. Wenn und nur wenn Dev-Safety, Latenz, Human/Degraded-Regressionen und alle Tests bestehen:

- aktuelle Produkt-, Test- und Manifestdateien hashen;
- `evaluation/CANDIDATE_V4.json` mit Konfiguration, Code-Hashes, Dev-Belegen und v6-Holdout-Seal anlegen;
- Freeze-Datei selbst hashen;
- danach den v6-Holdout genau einmal über einen getrennten Evaluationspfad ausführen.

## Plattformblocker

Letzte abgelehnte Operation: erneuter lokaler Apple-Metal-Live-Pipeline-Benchmark.
Fehlergrund der Plattform: Usage-Limit; keine Umgehung versucht.
