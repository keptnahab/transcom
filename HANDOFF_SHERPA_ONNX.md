# Handoff: sherpa-onnx VAD und Speaker-Embedding Integration

Dieses Dokument ist fuer einen neuen Entwicklungs-Chat gedacht. Ziel ist, die aktuell vorbereitete TransCom-v1-App um echte `sherpa-onnx` VAD- und Speaker-Embedding-Inferenz zu erweitern.

## Projektstand

Arbeitsordner:

```text
/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/01 1st try on Claude/TransCom
```

Vorhandene App:

- Electron/Vite Renderer
- Python Backend
- `sounddevice` Audioaufnahme
- `faster-whisper` ASR
- SQLite Transcript Storage
- Session-Ordner
- Speaker-Check-in UI
- Tokenisierter LAN-Viewer

Aktuelle Verifikation:

```bash
backend/.venv/bin/python -m pytest
# 29 passed

npm run build:renderer
# successful
```

## Ziel des naechsten Chats

Die Platzhalter-/Fallback-Logik in der Speaker- und Audio-Pipeline soll durch echte lokale `sherpa-onnx` Inferenz ersetzt werden:

1. Silero VAD via `sherpa-onnx`
2. Speaker-Embedding-Extraktion via `sherpa-onnx`
3. Speaker-Matching gegen Check-in-Profile
4. Segment-Metadaten mit Speaker-ID, Name, Farbe und Confidence speichern
5. Unsichere oder kurze VAD-Segmente verwerfen oder markieren

Keine Cloud-APIs.

## Relevante Dateien

### Backend Entry Point

```text
backend/main.py
```

Aktuell:

- erzeugt `TranscriptStore`
- erzeugt `SessionManager`
- erzeugt `SpeakerService`
- erzeugt `ShareServer`
- erzeugt `TranscriptionPool`
- erzeugt `ChannelManager`
- startet `WSServer`

Wichtig:

```python
speaker_service = SpeakerService()
```

Hier kann spaeter ein echter sherpa-basierter Service oder eine Modell-Konfiguration injiziert werden.

### Audio Capture

```text
backend/audio/capture.py
backend/audio/ring_buffer.py
```

Aktuell:

- `ChannelCapture` nimmt Audio per `sounddevice.InputStream` auf.
- Mono-Frames gehen in `RingBuffer`.
- Sobald genug Audio gesammelt ist, wird ein Chunk an `on_chunk(channel_id, audio, wall_clock_ts)` gesendet.
- Chunks sind aktuell fixe Whisper-Fenster mit Overlap.

VAD-Integration kann an zwei Stellen erfolgen:

1. In `ChannelCapture`, bevor Chunks an `on_chunk` gehen.
2. In einer neuen Pipeline-Schicht zwischen `ChannelCapture` und `TranscriptionPool`.

Empfohlen:

- Neue Pipeline-Schicht anlegen, z. B. `backend/audio/segmentation.py`.
- `ChannelCapture` weiter nur als Capture-Komponente behandeln.
- VAD/Speaker/ASR-Entscheidung nicht in die Low-Level-Capture-Klasse mischen.

### ASR Worker

```text
backend/transcription/worker_pool.py
backend/transcription/engine.py
```

Aktuell:

- `TranscriptionPool.submit(channel_id, audio, wall_clock_ts)`
- berechnet Chunk-Dauer
- ruft `WhisperEngine.transcribe(audio)` auf
- dispatcht `TranscriptionResult`

Ziel:

- Der Worker sollte segmentiertes Sprach-Audio bekommen, nicht grosse fixe Chunks.
- `TranscriptionResult` sollte Speaker-Match-Metadaten mitfuehren oder separat in `main.py` zugeordnet bekommen.

Moeglicher Umbau:

```python
@dataclass
class TranscriptionJob:
    channel_id: str
    audio: np.ndarray
    wall_clock_ts: float
    segment_start: float
    segment_duration: float
    speaker_match: SpeakerMatch | None
```

### Speaker Service

```text
backend/speaker/service.py
```

Aktuell:

- `SpeakerService` verwaltet Speaker-Profile.
- `enroll_from_stats(...)` ist ein Workflow-Fallback.
- `match_audio(audio)` nutzt einfache lokale Audiofeatures als Ersatz.

Das ist der wichtigste Integrationspunkt.

Gewuenschte neue API:

```python
service = SpeakerService(
    embedding_model_path=cfg.SPEAKER_EMBEDDING_MODEL,
    provider=cfg.SHERPA_PROVIDER,
)

profile = service.enroll_from_audio(speaker_id, audio, sample_rate=16000)
match = service.match_audio(audio, sample_rate=16000)
```

Bestehende UI-API kann erhalten bleiben:

- `speaker_create`
- `enrollment_start`
- `speaker_update`
- `segment_correct_speaker`

Aber `enrollment_start` sollte perspektivisch echte Audioaufnahme nutzen statt manuelle Dauer/Pegel-Werte.

### WebSocket Server

```text
backend/server/ws_server.py
```

Relevante Messages:

Inbound:

- `enrollment_start`
- `speaker_create`
- `speaker_update`
- `speaker_delete`
- `segment_correct_speaker`

Outbound:

- `enrollment_result`
- `speaker_update`
- `speaker_match`
- `transcript_segment`
- `engine_status`

Aktueller Handler:

```python
async def _handle_enrollment_start(self, ws, payload, req_id):
    result = self._speaker_service.enroll_from_stats(...)
```

Hier muss spaeter echte Enrollment-Audioaufnahme oder ein Enrollment-Buffer angebunden werden.

### Config

```text
backend/config.py
```

Bereits vorhanden:

```python
MODEL_DIR = Path(os.environ.get("TRANSCOM_MODEL_DIR", str(PROJECT_ROOT / "models")))
SILERO_VAD_MODEL = Path(os.environ.get("TRANSCOM_SILERO_VAD_MODEL", str(MODEL_DIR / "silero_vad.onnx")))
SPEAKER_EMBEDDING_MODEL = Path(
    os.environ.get(
        "TRANSCOM_SPEAKER_MODEL",
        str(MODEL_DIR / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
    )
)
SHERPA_PROVIDER = os.environ.get("TRANSCOM_SHERPA_PROVIDER", "cpu")
```

Diese Pfade sind absichtlich fuer die sherpa-onnx Integration vorbereitet.

### Requirements

```text
backend/requirements.txt
```

Enthaelt aktuell:

```text
sherpa-onnx>=1.10.0
pytest>=8.0
```

Pruefen, ob die Version fuer macOS Apple Silicon korrekt installiert und importierbar ist.

## Lokaler sherpa-onnx Ordner

Neben dem App-Prototyp existiert:

```text
/Users/mkue/Documents/CODEX/INTERCOM TRANSCRIPT/02 sherpa onnx
```

Dieser Ordner enthaelt Code, Beispiele und Skripte, aber nach aktuellem Stand keine fertigen ONNX-Modelle.

Nuetzliche Referenzbereiche:

```text
02 sherpa onnx/python-api-examples/
02 sherpa onnx/scripts/3dspeaker/
02 sherpa onnx/scripts/whisper/
02 sherpa onnx/scripts/wespeaker/
02 sherpa onnx/sherpa-onnx/python/
```

Im neuen Chat zuerst gezielt nach Beispielcode fuer folgende Klassen suchen:

- `VoiceActivityDetector`
- `VadModelConfig`
- `SileroVadModelConfig`
- `SpeakerEmbeddingExtractor`
- `SpeakerEmbeddingExtractorConfig`
- `SpeakerEmbeddingManager`

Empfohlene Suche:

```bash
rg "SpeakerEmbeddingExtractor|SpeakerEmbeddingManager|VoiceActivityDetector|SileroVad" "../02 sherpa onnx"
```

## Gewuenschte Zielarchitektur

### Audiofluss

```text
sounddevice InputStream
  -> mono float32 frames @ 16 kHz
  -> VAD frame/window collector
  -> speech segment
  -> speaker embedding
  -> speaker match
  -> faster-whisper ASR
  -> TranscriptStore.add_segment(...)
  -> WebSocket transcript_segment
  -> LAN viewer
```

### Komponenten

Empfohlen neue Dateien:

```text
backend/audio/vad.py
backend/audio/segmenter.py
backend/speaker/sherpa_backend.py
backend/models/setup.py
tests/test_vad_segmenter.py
tests/test_speaker_matching.py
```

Oder kompakter:

```text
backend/speaker/service.py
backend/audio/segmentation.py
```

Wichtig: `ChannelCapture` sollte weiterhin keine ASR- oder Speaker-Logik enthalten.

## VAD Anforderungen

### Input

- `np.ndarray`
- mono
- float32
- 16 kHz

### Output

Segment-Objekt:

```python
@dataclass
class SpeechSegment:
    audio: np.ndarray
    start_ts: float
    end_ts: float
    duration: float
    vad_confidence: float
    is_uncertain: bool
```

### Regeln

Defaults aus `config.py`:

```python
VAD_MIN_SPEECH_SECONDS = 0.5
VAD_MIN_SILENCE_SECONDS = 0.35
VAD_MAX_SEGMENT_SECONDS = 8.0
VAD_ENERGY_THRESHOLD = 0.012
```

Erwartetes Verhalten:

- Segmente unter Minimum verwerfen oder als unsicher markieren.
- Lange Segmente bei Maximaldauer abschliessen.
- Stille nicht an Whisper senden.
- Unsichere Segmente duerfen in UI mit niedriger Confidence erscheinen.

## Speaker Embedding Anforderungen

### Enrollment

Gefuehrter Check-in pro Person:

- Ziel: 8-12 Sekunden Sprache.
- UI zeigt Dauer, Pegel, Qualitaet, verwendbar/nicht verwendbar.
- Backend erzeugt Speaker-Profil mit Embedding.

Aktuelle UI sendet simulierte Werte:

```json
{
  "type": "enrollment_start",
  "payload": {
    "speaker_id": "...",
    "duration_seconds": 10,
    "level": 0.04
  }
}
```

Ziel:

- UI startet echte Enrollment-Aufnahme.
- Backend sammelt Audio fuer den gewaehlten Speaker.
- Nach ausreichend Sprache wird Embedding extrahiert.
- `enrollment_result` meldet Qualitaet und Profilstatus.

### Matching

Pro Sprachsegment:

- Embedding extrahieren.
- Gegen SpeakerEmbeddingManager suchen.
- Ergebnis:

```python
@dataclass
class SpeakerMatch:
    speaker_id: str | None
    speaker_name: str
    confidence: float
    is_unknown: bool
```

Confidence-Regel:

- Unter Threshold: `Unknown`
- Sonst bester Speaker

Konfig:

```python
SPEAKER_THRESHOLD = 0.45
SPEAKER_MAX_V1 = 8
```

## TranscriptStore Integration

Datei:

```text
backend/transcript/store.py
```

`add_segment` akzeptiert bereits:

```python
speaker_id
speaker_name
speaker_color
speaker_confidence
```

Beim echten Speaker-Match sollen diese Felder gesetzt werden.

Beispiel:

```python
stored = store.add_segment(
    channel_id=result.channel_id,
    text=seg.text,
    timestamp=abs_ts,
    confidence=seg.confidence,
    speaker_id=match.speaker_id,
    speaker_name=match.speaker_name,
    speaker_color=match.speaker_color,
    speaker_confidence=match.confidence,
)
```

Aktuell ruft `backend/main.py` noch:

```python
match = speaker_service.match_audio(None)
```

Das ist ein Platzhalter und muss durch echtes Segment-Audio ersetzt werden.

## UI Integration

Die UI ist vorbereitet:

```text
renderer/src/components/SpeakerPanel.js
renderer/src/components/TranscriptPane.js
```

Transcript-Zeilen zeigen:

- Sprechername
- Sprecherfarbe
- Speaker-Confidence im Tooltip
- Korrektur-Dropdown

SpeakerPanel zeigt:

- Profilqualitaet
- Dauer
- Pegel
- verwendbar/nicht verwendbar

Moeglicher naechster UI-Schritt:

- Enrollment-Button startet echte Aufnahme.
- Fortschritt laeuft automatisch.
- Pegelanzeige live statt manuellem Zahlenfeld.
- Fehler anzeigen, wenn Modell fehlt.

## Modell-Setup

Noch zu bauen:

```text
backend/models/setup.py
renderer/src/components/ModelSetupPanel.js
```

Aufgaben:

- Pruefen, ob `models/silero_vad.onnx` existiert.
- Pruefen, ob Speaker-Modell existiert.
- Download/Install-Assistent anbieten.
- Nach erfolgreichem Setup `backend_status` aktualisieren.

Wichtig:

- Einmaliger Download ist erlaubt.
- Danach soll TransCom offline laufen.
- Keine Cloud-APIs fuer Transkription/Speaker-ID.

## Testplan fuer den neuen Chat

### Unit Tests

Neue Tests:

```text
tests/test_vad_segmenter.py
tests/test_speaker_matching.py
```

Faelle:

- synthetische Stille erzeugt keine Segmente.
- synthetischer Ton/Sprache-Proxy erzeugt Segment.
- sehr kurze Segmente werden verworfen oder unsicher.
- Enrollment erzeugt verwendbares Profil.
- Matching findet bekannten Sprecher.
- niedrige Confidence ergibt Unknown.

### Integration Tests

Dateibasierter Audiofluss:

- `TRANSCOM_AUDIO_SOURCE=file:///path/to/test.wav`
- zwei Speaker-Profile
- Live-Transkription
- Segment enthaelt Speaker-Metadaten

Viewer:

- `share_start`
- `/api/segments?token=valid` liefert Segmente.
- `/api/segments?token=invalid` liefert `403`.

### Bestehende Tests

Nach Umbau immer ausfuehren:

```bash
backend/.venv/bin/python -m pytest
npm run build:renderer
env PYTHONPYCACHEPREFIX=/private/tmp/transcom-pycache backend/.venv/bin/python -m compileall -q backend tests -x 'backend/.venv'
```

## Bekannte Risiken

### sherpa-onnx Installation

Die venv wurde urspruenglich aus einem anderen Pfad kopiert. `pip` war kaputt, aber funktioniert ueber:

```bash
backend/.venv/bin/python -m pip install ...
```

Nicht verwenden:

```bash
backend/.venv/bin/pip
```

### Modellpfade

`02 sherpa onnx` enthaelt Code/Beispiele, aber keine fertigen Modelle. Der neue Chat muss Modell-Download oder manuelle Modellpfade klaeren.

### Apple Silicon Provider

Default soll CPU-stabil sein. CoreML/provider-Optimierung nur optional aktivieren, wenn lokal verfuegbar und getestet.

### Latenz

Ziel: 3-5 Sekunden End-to-end.

VAD-Max-Segmentdauer, Whisper-Chunking und Enrollment-Puffer duerfen diese Zielwerte nicht aus Versehen deutlich erhoehen.

### Overlaps

V1 trennt Overlapping Speech nicht sauber. Bei Overlap:

- Hauptsprecher waehlen
- niedrige Confidence anzeigen
- optional `Unknown`

## Konkrete erste Schritte im neuen Chat

1. `rg` im lokalen `02 sherpa onnx` Ordner nach VAD/Speaker-Beispielen.
2. Pruefen, ob `import sherpa_onnx` in `backend/.venv/bin/python` funktioniert.
3. Falls nicht, mit `backend/.venv/bin/python -m pip install sherpa-onnx` installieren.
4. Minimales Python-Scratch-Skript fuer Silero VAD mit lokalem oder heruntergeladenem Modell.
5. Minimales Python-Scratch-Skript fuer SpeakerEmbeddingExtractor/Manager.
6. `SpeakerService` von Fallback auf echten sherpa-Backend-Adapter erweitern.
7. VAD-Segmenter zwischen Capture und TranscriptionPool setzen.
8. Tests ergaenzen.
9. UI-Status fuer Modell bereit/fehlt aktualisieren.

## Definition of Done

Die Integration gilt fuer v1 als fertig, wenn:

- App startet ohne Cloud-Abhaengigkeit.
- Ohne Modelle zeigt UI einen klaren Setup-/Missing-Model-Status.
- Mit Modellen segmentiert VAD echte Sprache.
- Speaker-Check-in erzeugt echte Embeddings.
- Live-Segmente enthalten Speaker-Match-Metadaten.
- Korrektur bleibt moeglich.
- LAN-Viewer zeigt Speakerfarbe und Sprechername.
- `backend/.venv/bin/python -m pytest` ist gruen.
- `npm run build:renderer` ist gruen.
