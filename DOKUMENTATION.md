# TransCom v1 Dokumentation

TransCom ist eine lokale macOS-Desktop-App fuer Live-Transkription eines gemischten Intercom- oder Produktions-Audiofeeds. Die App basiert auf Electron fuer die Bedienoberflaeche und einem Python-Backend fuer Audioaufnahme, Transkription, Speaker-Workflow, Session-Speicherung und LAN-Sharing.

Die v1 ist konsequent offline gedacht: Audio bleibt lokal, Transkripte werden lokal gespeichert, und der Viewer laeuft nur im lokalen Netzwerk. Cloud-APIs sind nicht vorgesehen.

## Schnellstart

Im Projektordner:

```bash
npm run dev:renderer
backend/.venv/bin/python backend/main.py
```

Danach die App im Browser oder Electron oeffnen:

```text
http://localhost:5747/
```

Fuer die Electron-App:

```bash
npm run dev
```

## Bedienablauf

### 1. Session anlegen

Links im Bereich `Session` wird eine neue Session erstellt.

- `Session name`: Anzeigename der Session, z. B. eine Show, Probe oder Produktion.
- `Storage folder`: optionaler Zielordner. Wenn leer, nutzt TransCom den lokalen Standardordner `sessions/`.
- `Create`: legt einen eigenen Session-Unterordner an.
- `Start`: markiert die Session als live.
- `Stop`: beendet die Session und stoppt laufende Audiofeeds.

Beim Erstellen einer Session erzeugt TransCom:

```text
sessions/<session-id>/
  session.json
  transcript.db
  exports/
  profiles/
```

### 2. Audioquelle waehlen

Im Bereich `Audio Feed` wird zuerst der Quellmodus gewaehlt:

- `Live Input / Loopback`: fuer ein echtes Audio-Interface, ein Intercom-Mischpult, BlackHole/Loopback oder REAPER.
- `Audio File`: fuer eine vorab aufgezeichnete Intercom-Session, z. B. die mitgelieferte Test-WAV.

TransCom v1 nutzt genau einen gemischten Summenfeed. Mono und Stereo werden als ein Feed behandelt.

#### Variante A: Test-WAV oder aufgezeichnete Session direkt laden

1. In `Audio Feed` den Modus `Audio File` waehlen.
2. `Choose File` klicken und eine WAV/Audio-Datei auswaehlen.
3. Alternativ `Use Demo WAV` klicken, um den mitgelieferten Testfeed zu laden.
4. `Start Feed` klicken.

Die Datei wird von TransCom selbst gelesen. Dafuer muss keine Player-App geoeffnet und kein macOS-Audio-Routing eingerichtet werden.

#### Variante B: Lokale Player-App oder REAPER einspielen

macOS zeigt App-Ausgaenge nicht automatisch als Eingabequelle an. Fuer Player-Apps oder REAPER wird deshalb ein virtuelles Audiogeraet benoetigt, z. B. BlackHole oder Rogue Amoeba Loopback.

1. Virtuelles Audiogeraet installieren/anlegen, z. B. `BlackHole 2ch`.
2. In der Player-App oder in REAPER den Output auf dieses virtuelle Geraet routen.
3. In TransCom `Live Input / Loopback` waehlen.
4. Das virtuelle Geraet als Input auswaehlen.
5. `Start Feed` klicken und die Player-App/REAPER starten.

#### Variante C: Live-Intercom einspielen

1. Intercom-Mix ueber ein USB-Audiointerface oder Mischpult an den Mac anschliessen.
2. In TransCom `Live Input / Loopback` waehlen.
3. Das Hardware-Input-Geraet auswaehlen.
4. Bei Bedarf `Refresh` klicken, wenn das Geraet erst nach App-Start verbunden wurde.
5. `Start Feed` klicken.

Im Backend erfolgt die Live-Aufnahme mit `sounddevice`. Audio-Dateien werden im gleichen Capture-Pfad in Echtzeit abgespielt und an die Transkriptionspipeline uebergeben.

### 3. Speaker Check-in

Rechts im Bereich `Speaker Check-in` koennen bis zu 8 Sprecher fuer die Session angelegt werden.

Workflow:

1. Namen eingeben.
2. `Add` klicken.
3. Fuer die Person 8-12 Sekunden klar sprechen lassen.
4. Dauer und Pegel kontrollieren.
5. `Check-in` ausloesen.

Die UI zeigt:

- Name und Farbe des Sprechers.
- Profilqualitaet als Balken.
- Ob das Profil verwendbar ist.
- Dauer und Pegel des Check-ins.

Aktueller Implementierungsstand:

- Das Datenmodell und die UI fuer Speaker-Profile sind vorhanden.
- Der Service ist so gebaut, dass `sherpa-onnx` Speaker-Embeddings darunter integriert werden koennen.
- Solange `sherpa-onnx`-Modelle fehlen, nutzt TransCom einen lokalen deterministischen Fallback fuer die Workflow-Tests.

### 4. Live-Transcript

Die Mitte der App zeigt das laufende Transcript.

Jede Zeile enthaelt:

- Zeitstempel
- Sprecher oder Channel-Label
- Transkripttext
- Dropdown fuer Sprecherkorrektur

Operatoren koennen in v1 nur die Sprecherzuordnung korrigieren. Der Transkripttext selbst ist absichtlich nicht editierbar.

### 5. Speaker-Korrektur

Neben jedem Segment gibt es ein Sprecher-Dropdown.

Wenn ein Sprecher korrigiert wird, schreibt das Backend:

- `corrected_speaker_id`
- `corrected_speaker_name`

Die urspruengliche Erkennung bleibt im Segment erhalten. Dadurch kann spaeter nachvollzogen werden, was automatisch erkannt und was manuell korrigiert wurde.

### 6. LAN Viewer starten

Im Bereich `LAN Viewer` kann ein Read-only Viewer gestartet werden.

- `Start Share`: startet einen lokalen HTTP-Server.
- TransCom erzeugt einen zufaelligen Token.
- Die UI zeigt einen Link im lokalen Netzwerk.
- `Copy` kopiert den Link.
- `Stop Share` beendet den Viewer.

Der Viewer kann nur live mitlesen. Er hat keine Export-, Bearbeitungs- oder Korrekturfunktionen.

Beispiel:

```text
http://192.168.x.x:8787/?token=<zufallstoken>
```

Der Viewer ruft intern read-only Daten ab:

```text
/api/segments?token=<zufallstoken>
```

Ohne gueltigen Token antwortet der Server mit `403`.

## Architektur

### Electron

Dateien:

- `electron/main.js`
- `electron/preload.js`

Aufgaben:

- Startet das Python-Backend.
- Wartet auf `READY`.
- Oeffnet das Electron-Fenster.
- Stellt native Dialoge bereit, z. B. Speichern unter.
- Leitet Backend-Fehler an den Renderer weiter.

### Renderer

Dateien:

- `renderer/index.html`
- `renderer/src/main.js`
- `renderer/src/store.js`
- `renderer/src/ws.js`
- `renderer/src/components/ChannelPanel.js`
- `renderer/src/components/Toolbar.js`
- `renderer/src/components/TranscriptPane.js`
- `renderer/src/components/SpeakerPanel.js`
- `renderer/src/styles/app.css`

Aufgaben:

- Zeigt den Operator-Workflow.
- Verwaltet UI-State im lokalen Store.
- Kommuniziert per WebSocket mit dem Backend.
- Rendert Live-Transkript, Sessionstatus, Speakerprofile und Sharing-Link.

### Python Backend

Wichtige Module:

- `backend/main.py`: startet Services und WebSocket-Server.
- `backend/server/ws_server.py`: WebSocket-Protokoll und Request-Handler.
- `backend/audio/capture.py`: Audioaufnahme per `sounddevice`.
- `backend/audio/ring_buffer.py`: Chunking und Overlap fuer ASR.
- `backend/transcription/engine.py`: `faster-whisper` Wrapper.
- `backend/transcription/worker_pool.py`: Worker-Thread fuer ASR.
- `backend/transcript/store.py`: SQLite-Speicher.
- `backend/session/manager.py`: Session-Ordner und Metadaten.
- `backend/speaker/service.py`: Speaker-Profile und Matching-Grenze.
- `backend/share/server.py`: tokenisierter LAN-Viewer.

## Datenmodell

### Session

Gespeichert in `session.json`:

- `id`
- `name`
- `root_dir`
- `session_dir`
- `db_path`
- `created_at`
- `started_at`
- `stopped_at`
- `status`

### Transcript-Segment

Gespeichert in SQLite:

- `segment_id`
- `channel_id`
- `text`
- `timestamp`
- `confidence`
- `speaker_id`
- `speaker_name`
- `speaker_color`
- `speaker_confidence`
- `corrected_speaker_id`
- `corrected_speaker_name`

### Speaker-Profil

Aktueller In-Memory-Stand:

- `id`
- `name`
- `color`
- `quality`
- `duration_seconds`
- `level`
- `usable`
- internes Embedding bzw. Fallback-Feature

Optionales Persistieren von Profilsets ist als v1-Ziel vorgesehen, aber noch nicht vollstaendig implementiert.

## WebSocket-Protokoll

### Initialisierung

Frontend sendet:

```json
{ "type": "init", "payload": {} }
```

Backend antwortet mit:

```json
{
  "type": "init_state",
  "payload": {
    "devices": [],
    "channels": [],
    "segments": [],
    "session": null,
    "speakers": [],
    "share": {},
    "status": {}
  }
}
```

### Session

Inbound:

- `session_create`
- `session_start`
- `session_stop`

Outbound:

- `session_state`
- `session_started`
- `session_stopped`

### Audio/Channels

Inbound:

- `list_devices`
- `add_channel`
- `update_channel`
- `remove_channel`
- `start_capture`
- `stop_capture`
- `stop_all`

Outbound:

- `device_list`
- `channel_added`
- `channel_updated`
- `channels_updated`
- `channel_removed`

### Transcript

Inbound:

- `clear_transcript`
- `export_transcript`
- `search_transcript`
- `segment_correct_speaker`

Outbound:

- `transcript_segment`
- `transcript_cleared`
- `segment_updated`
- `export_done`
- `search_results`

### Speaker

Inbound:

- `speaker_create`
- `speaker_update`
- `speaker_delete`
- `enrollment_start`

Outbound:

- `speaker_update`
- `enrollment_result`
- `speaker_match`

### Sharing

Inbound:

- `share_start`
- `share_stop`

Outbound:

- `share_state`

### Status/Fehler

Outbound:

- `backend_status`
- `engine_status`
- `error`

## Audio- und ASR-Pipeline

Aktueller Ablauf:

1. `sounddevice` nimmt vom gewaehlen Input Device auf.
2. `RingBuffer` sammelt Audioframes.
3. Sobald genug Frames vorhanden sind, wird ein Chunk mit Overlap erzeugt.
4. `TranscriptionPool` schickt den Chunk in einen Worker-Thread.
5. `WhisperEngine` transkribiert lokal mit `faster-whisper`.
6. Ergebnisse werden als Transcript-Segmente in SQLite gespeichert.
7. Backend sendet `transcript_segment` an alle verbundenen UIs.

Geplanter v1-Zielablauf mit sherpa-onnx:

1. Summenfeed aufnehmen.
2. Silero VAD via `sherpa-onnx` segmentiert Sprache.
3. Unsichere/kurze Segmente werden verworfen oder markiert.
4. Speaker-Embedding wird extrahiert.
5. Speaker-Match erfolgt gegen Check-in-Profile.
6. Segment wird per `faster-whisper` transkribiert.
7. Segment wird mit Speaker-Metadaten gespeichert und gesendet.

## Offline-Modelle

Defaults:

- ASR: `faster-whisper`, multilingual, CPU/int8.
- VAD: `sherpa-onnx` Silero VAD vorgesehen.
- Speaker-ID: `sherpa-onnx` SpeakerEmbeddingExtractor/Manager vorgesehen.

Aktueller Status:

- `faster-whisper` ist integriert.
- `sherpa-onnx` steht in `backend/requirements.txt`.
- ONNX-Modelle werden noch nicht automatisch geladen.
- UI zeigt fehlende Modelle als `pending`.
- Die App bleibt trotzdem bedienbar, damit Session, UI, Storage und Sharing getestet werden koennen.

## Tests

Tests ausfuehren:

```bash
backend/.venv/bin/python -m pytest
```

Aktueller Stand:

- Device-Scanner
- RingBuffer
- Message-Schema
- TranscriptStore
- SessionManager
- SpeakerService

Beim letzten Lauf:

```text
29 passed
```

Renderer-Build:

```bash
npm run build:renderer
```

## Aktuelle Grenzen

Diese Punkte sind bewusst noch nicht fertig:

- Echte `sherpa-onnx` VAD-Integration ist vorbereitet, aber nicht final verdrahtet.
- Echte Speaker-Embeddings sind vorbereitet, aber aktuell noch Fallback.
- Einmaliger Download-Assistent fuer Modelle fehlt noch.
- Profilsets werden noch nicht dauerhaft als eigene Profilpakete gespeichert.
- QR-Code wird noch nicht gerendert; aktuell wird der LAN-Link angezeigt und kopierbar gemacht.
- Live-Viewer nutzt HTTP-Polling statt WebSocket-Streaming.
- Overlapping Speech wird nicht getrennt.
- Textkorrektur ist absichtlich nicht Teil von v1.

## Empfohlene naechste Schritte

1. Setup-Assistent fuer Modell-Download bauen.
2. `sherpa-onnx` Silero VAD in `backend/audio` integrieren.
3. SpeakerEmbeddingExtractor/Manager in `backend/speaker/service.py` hinter der bestehenden Service-Grenze anbinden.
4. Profilsets im Session-Ordner speichern und wieder laden.
5. QR-Code fuer den LAN-Link im rechten Panel rendern.
6. Datei-basierten Integrationstest fuer zwei Sprecher und Viewer-Token ergaenzen.
