# MacBook Handoff

## Zeitraum

Ab 2026-07-04 arbeitet der User fuer etwa sechs Wochen nur am MacBook weiter.

## Neuer Arbeitsort

Das komplette Projekt soll in Dropbox liegen:

```text
/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom
```

Nach dem Umzug liegt das Haupt-Repo hier:

```text
/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom
```

Nicht mehr als aktiven Arbeitsort verwenden:

```text
/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT
```

## Aktueller Projektstand

TransCom ist ein lokaler macOS-Beta-Build fuer Live-/File-Transkription eines gemischten Intercom-Feeds.

Wichtigste aktuelle Verbesserungen:

- Demo-WAV/File-Modus ist wieder sichtbar und nutzbar.
- File-Modus bleibt stabil bei UI-State-Refreshes.
- File-/Demo-Modus hat Browser-Audio-Monitoring und sichtbare Audio-Controls.
- Auth kann fuer lokale Tests deaktiviert werden: `TRANSCOM_AUTH_DISABLED=1`.
- Default-ASR ist aktuell `faster-whisper`, nicht `mlx`.
- Beta-Launcher nutzt `TRANSCOM_LANG=auto`.
- Faster-whisper Word-Timestamps laufen in den Timed-Stabilizer.
- UI ersetzt bestehende Transcript-Zeilen mit gleicher `segment_id`, statt Duplikate anzufuegen.
- Es gibt ein weitergebbares Beta-Testpaket unter `release/`.

## Beta-Testpaket

Finales Paket:

```text
release/TransCom_Beta_Testpaket_2026-07-03_FINAL.zip
```

Inhalt:

- macOS arm64 App-Zip
- Start-hier-Readme
- Installationsanleitung
- Benutzerhandbuch
- Troubleshooting
- Datenschutz-/Beta-Hinweise
- Release Notes
- Technische Dokumentation
- Testprotokoll
- Feedbackformular

Wichtig: Der gepackte Beta-Build startet mit Auth-Bypass, damit Tester die App per Doppelklick verwenden koennen.

## Schnellstart im neuen Pfad

```bash
cd "/Users/mkue/Dropbox (Privat)/00_AI/01_Codex/260704 TransCom/01 1st try on Claude/TransCom"
```

Backend ohne Login:

```bash
TRANSCOM_WEB_PORT=8081 TRANSCOM_AUTH_DISABLED=1 backend/.venv/bin/python backend/main.py
```

Renderer:

```bash
TRANSCOM_WEB_PORT=8081 npm run dev:renderer -- --host 127.0.0.1
```

Browser:

```text
http://127.0.0.1:5747/
```

Tests:

```bash
backend/.venv/bin/python -m pytest
```

Renderer-Build:

```bash
npm run build:renderer
```

Electron-Build:

```bash
npm run build
```

## Letzte bekannte Verifikation

- `backend/.venv/bin/python -m pytest` -> `52 passed, 1 warning`
- `npm run build:renderer` -> success
- `npm run build` -> success, macOS arm64 ZIP erstellt
- Browser `/api/audio-file` Range-Request -> `206 Partial Content`, WAV-Daten
- Fixture Benchmark auf `faster-whisper`:
  - WER `0.2667`
  - first emit ca. `3.59s`
  - Sprachen `de/en`

## Offene P0-Themen

- Reale ASR-Qualitaet ist noch unter Erwartung.
- Erste nutzbare Ausgabe ist noch zu langsam.
- Real-UI-Test gegen aktualisierten Backendstand muss bestaetigen, dass die erste Transcript-Zeile nicht mehr doppelt erscheint.
- Session-/Start-/Feed-UX ist fuer Operatoren noch missverstaendlich.

## Offene P1-Themen

- Utterance Commit Logic ueberarbeiten, damit finale Zeilen kohaerenter und weniger fragmentiert sind.
- Speaker Matching nur auf finalen VAD-Segmenten erneut pruefen.
- `mlx`-Runtime erst wieder validieren, wenn `faster-whisper` zufriedenstellend ist.
- Browser-Level-End-to-End-Test nach naechsten ASR/Stabilizer-Aenderungen.

## Wichtige Hinweise fuer naechsten Codex-Start

- Der Git-Worktree ist absichtlich dirty. Nicht zuruecksetzen.
- Ungetrackte Tests gehoeren zum aktuellen Stand:
  - `tests/test_segmentation.py`
  - `tests/test_transcription_engine.py`
- Release-Ordner koennen durch `.gitignore` ausgeblendet sein, liegen aber physisch im Projekt.
- Vor dem Verschieben keine laufenden Preview-Prozesse auf `5747`, `8765`, `8081`.
- Nach dem Verschieben alte absolute Pfade in Doku/Tools auf Dropbox-Pfad aktualisieren, falls sie noch stoeren.
