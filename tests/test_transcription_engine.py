from __future__ import annotations

import numpy as np
import pytest

import backend.config as cfg
import backend.transcription.engine as engine_module


class _FakeLanguageModel:
    def __init__(self, probabilities):
        self._probabilities = probabilities

    def detect_language(self, *_args, **_kwargs):
        return ("fr", 0.8, self._probabilities)


class _FakeWord:
    def __init__(self, word, start, end, probability):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _FakeSegment:
    def __init__(self, text, start, end, words=None):
        self.text = text
        self.start = start
        self.end = end
        self.words = words or []
        self.avg_logprob = -0.1


class _FakeTranscribeModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, *_args, **_kwargs):
        self.kwargs = _kwargs
        return (
            [
                _FakeSegment(
                    " Hallo Regie",
                    0.0,
                    0.6,
                    [
                        _FakeWord(" Hallo", 0.0, 0.2, 0.9),
                        _FakeWord(" Regie", 0.2, 0.6, 0.8),
                    ],
                )
            ],
            {},
        )


def test_auto_language_stays_within_allowed_languages(monkeypatch):
    monkeypatch.setattr(cfg, "WHISPER_ALLOWED_LANGUAGES", {"de", "en"})
    monkeypatch.setattr(cfg, "WHISPER_DEFAULT_LANGUAGE", "de")
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE", "auto")
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY", 0.55)
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_STICKINESS_RATIO", 0.75)
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_SWITCH_MARGIN", 0.0)

    engine = engine_module.WhisperEngine()
    engine._model = _FakeLanguageModel([("fr", 0.9), ("en", 0.45), ("de", 0.3)])
    engine._last_language = "de"

    detected = engine._select_language(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32))

    assert detected == "en"
    assert engine.last_language == "en"


def test_auto_language_requires_configured_switch_margin(monkeypatch):
    monkeypatch.setattr(cfg, "WHISPER_ALLOWED_LANGUAGES", {"de", "en"})
    monkeypatch.setattr(cfg, "WHISPER_DEFAULT_LANGUAGE", "de")
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE", "auto")
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_SWITCH_MIN_PROBABILITY", 0.55)
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_STICKINESS_RATIO", 0.75)
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE_SWITCH_MARGIN", 0.20)

    engine = engine_module.WhisperEngine()
    engine._model = _FakeLanguageModel([("en", 0.60), ("de", 0.45)])
    engine._last_language = "de"

    detected = engine._select_language(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32))

    assert detected == "de"
    assert engine.last_language == "de"


def test_explicit_unsupported_language_falls_back(monkeypatch):
    monkeypatch.setattr(cfg, "WHISPER_ALLOWED_LANGUAGES", {"de", "en"})
    monkeypatch.setattr(cfg, "WHISPER_DEFAULT_LANGUAGE", "de")

    engine = engine_module.WhisperEngine()
    engine._last_language = "de"

    detected = engine._select_language(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), requested="fr")

    assert detected == "de"
    assert engine.last_language == "de"


def test_faster_whisper_transcribe_prefers_word_segments(monkeypatch):
    monkeypatch.setattr(cfg, "WHISPER_BACKEND", "faster-whisper")
    monkeypatch.setattr(cfg, "WHISPER_LANGUAGE", "de")
    monkeypatch.setattr(cfg, "WHISPER_NO_SPEECH_THRESHOLD", 0.3)
    monkeypatch.setattr(cfg, "WHISPER_HOTWORDS", "Bühne Hubpodium")

    engine = engine_module.WhisperEngine()
    engine._model = _FakeTranscribeModel()
    engine._active_backend = "faster-whisper"
    monkeypatch.setattr(engine, "load", lambda: None)

    segments = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32))

    assert [seg.text for seg in segments] == [" Hallo", " Regie"]
    assert all(seg.is_word for seg in segments)
    assert segments[1].confidence == 0.8
    assert all(seg.requires_confirmation for seg in segments)
    assert engine._model.kwargs["no_speech_threshold"] == 0.3
    assert engine._model.kwargs["hotwords"] == "Bühne Hubpodium"
    assert engine._model.kwargs["beam_size"] == cfg.WHISPER_BEAM_SIZE


def test_release_model_source_is_pinned_to_local_snapshot(monkeypatch):
    calls = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        return "/cache/pinned-model"

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    source, revision = engine_module.WhisperEngine._resolve_model_source(
        cfg.MLX_MODEL_REPOSITORY,
        default_repository=cfg.MLX_MODEL_REPOSITORY,
        pinned_revision=cfg.MLX_MODEL_REVISION,
    )

    assert source == "/cache/pinned-model"
    assert revision == cfg.MLX_MODEL_REVISION
    assert calls == [{
        "repo_id": cfg.MLX_MODEL_REPOSITORY,
        "revision": cfg.MLX_MODEL_REVISION,
        "local_files_only": True,
    }]


def test_hybrid_mlx_defaults_and_confirmation_are_pinned():
    assert cfg.MLX_MODEL_REPOSITORY == "mlx-community/whisper-large-v3-mlx-4bit"
    assert cfg.MLX_MODEL_REVISION == "d12b5d0043a6fe0c59af321617fba041d4e8e0c8"
    assert cfg.MLX_SHORT_MODEL_REPOSITORY == "mlx-community/whisper-large-v3-turbo-q4"
    assert cfg.MLX_SHORT_MODEL_REVISION == "660c343bbf4e52ac257f0b7d952e5388e6f93bef"
    assert cfg.MLX_SHORT_MAX_SECONDS == 3.0
    assert cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY == "Systran/faster-whisper-small"
    assert cfg.SAFETY_CONFIRMATION_MODEL_REVISION == cfg.WHISPER_MODEL_REVISION
    assert cfg.SAFETY_CONFIRMATION_BEAM_SIZE == 3
    assert cfg.WHISPER_CPU_THREADS == 12
    assert cfg.CHUNK_SECONDS == 0.15


def test_both_default_mlx_repositories_resolve_offline_pinned(monkeypatch):
    calls = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        return f"/cache/{kwargs['revision']}"

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    long_source, long_revision = engine_module.WhisperEngine._resolve_model_source(
        cfg.MLX_WHISPER_MODEL,
        default_repository=cfg.MLX_MODEL_REPOSITORY,
        pinned_revision=cfg.MLX_MODEL_REVISION,
    )
    short_source, short_revision = engine_module.WhisperEngine._resolve_model_source(
        cfg.MLX_SHORT_WHISPER_MODEL,
        default_repository=cfg.MLX_SHORT_MODEL_REPOSITORY,
        pinned_revision=cfg.MLX_SHORT_MODEL_REVISION,
    )

    assert long_source.endswith(cfg.MLX_MODEL_REVISION)
    assert short_source.endswith(cfg.MLX_SHORT_MODEL_REVISION)
    assert long_revision == cfg.MLX_MODEL_REVISION
    assert short_revision == cfg.MLX_SHORT_MODEL_REVISION
    assert calls == [
        {
            "repo_id": cfg.MLX_MODEL_REPOSITORY,
            "revision": cfg.MLX_MODEL_REVISION,
            "local_files_only": True,
        },
        {
            "repo_id": cfg.MLX_SHORT_MODEL_REPOSITORY,
            "revision": cfg.MLX_SHORT_MODEL_REVISION,
            "local_files_only": True,
        },
    ]


def test_original_duration_routes_three_seconds_to_short_and_longer_to_full(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", False)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._resolved_model_path = "/models/full"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    calls = []

    def transcribe(*_args, **kwargs):
        calls.append((kwargs["model_source"], kwargs["model_role"]))
        return [engine_module.Segment("Test", 0.0, 1.0, 0.9)]

    monkeypatch.setattr(engine, "_transcribe_mlx", transcribe)

    engine.transcribe(np.zeros(3 * cfg.SAMPLE_RATE, dtype=np.float32), language="de")
    engine.transcribe(np.zeros(3 * cfg.SAMPLE_RATE + 1, dtype=np.float32), language="de")

    assert calls == [("/models/turbo", "short"), ("/models/full", "long")]


def test_edge_padding_does_not_change_short_model_selection(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", False)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._resolved_model_path = "/models/full"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(
        engine,
        "_normalize_edge_context",
        lambda _audio: (np.zeros(10 * cfg.SAMPLE_RATE, dtype=np.float32), 0),
    )
    selected = {}

    def transcribe(audio, **kwargs):
        selected.update({"samples": len(audio), **kwargs})
        return [engine_module.Segment("Test", 0.0, 1.0, 0.9)]

    monkeypatch.setattr(engine, "_transcribe_mlx", transcribe)

    engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert selected["samples"] == 10 * cfg.SAMPLE_RATE
    assert selected["model_source"] == "/models/turbo"
    assert selected["model_role"] == "short"


def test_alternating_mlx_models_use_preloaded_objects_without_reload(monkeypatch):
    loader_calls = []

    def load_model(path, *, dtype):
        loader_calls.append((path, dtype))
        return object()

    class _Holder:
        model = None
        model_path = None

        @classmethod
        def get_model(cls, path, dtype):
            if cls.model is None or cls.model_path != path:
                cls.model = load_model(path, dtype=dtype)
                cls.model_path = path
            return cls.model

    class _DualMlx:
        def __init__(self):
            self.paths = []
            self.word_timestamp_modes = []

        def transcribe(self, *_args, path_or_hf_repo, **kwargs):
            _Holder.get_model(path_or_hf_repo, "float16")
            self.paths.append(path_or_hf_repo)
            self.word_timestamp_modes.append(kwargs["word_timestamps"])
            return {
                "language": "de",
                "segments": [{
                    "text": "Hallo Regie",
                    "start": 0.0,
                    "end": 1.0,
                    "words": [],
                }],
            }

    engine = engine_module.WhisperEngine()
    engine._mlx = _DualMlx()
    engine._mlx_model_holder = _Holder
    engine._mlx_model_loader = load_model
    engine._mlx_float16 = "float16"

    def resolve(configured, **_kwargs):
        return ("/models/turbo", "short-rev") if configured == cfg.MLX_SHORT_WHISPER_MODEL else (
            "/models/full", "long-rev"
        )

    monkeypatch.setattr(engine, "_resolve_model_source", resolve)
    engine._load_mlx()
    assert loader_calls == [
        ("/models/full", "float16"),
        ("/models/turbo", "float16"),
    ]
    assert engine._mlx.word_timestamp_modes[:2] == [True, False]

    engine._transcribe_mlx(
        np.zeros(cfg.SAMPLE_RATE, dtype=np.float32),
        language="de",
        model_source="/models/turbo",
        model_role="short",
    )
    engine._transcribe_mlx(
        np.zeros(4 * cfg.SAMPLE_RATE, dtype=np.float32),
        language="de",
        model_source="/models/full",
        model_role="long",
    )
    engine._transcribe_mlx(
        np.zeros(cfg.SAMPLE_RATE, dtype=np.float32),
        language="de",
        model_source="/models/turbo",
        model_role="short",
    )

    assert loader_calls == [
        ("/models/full", "float16"),
        ("/models/turbo", "float16"),
    ]
    assert engine._mlx.paths[-3:] == ["/models/turbo", "/models/full", "/models/turbo"]
    assert engine._mlx.word_timestamp_modes[-3:] == [False, True, False]


def test_short_segment_mode_preserves_timing_raw_and_safety_confirmation(monkeypatch):
    class _SegmentMlx:
        def __init__(self):
            self.calls = []

        def transcribe(self, *_args, path_or_hf_repo, **kwargs):
            self.calls.append((path_or_hf_repo, kwargs["word_timestamps"]))
            text = "Lass sicher halten" if not kwargs["word_timestamps"] else "Langer Satz"
            return {
                "language": "de",
                "segments": [{
                    "text": text,
                    "start": 0.2,
                    "end": 1.1,
                    "words": [],
                }],
            }

    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._mlx = _SegmentMlx()
    engine._active_backend = "mlx"
    engine._resolved_model_path = "/models/full"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(engine, "_normalize_edge_context", lambda audio: (audio, 0))
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: object())
    monkeypatch.setattr(
        engine,
        "_transcribe_faster_whisper_model",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Last sicher halten!", 0.2, 1.1, 0.9)
        ],
    )

    short = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")
    long = engine.transcribe(np.zeros(4 * cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert engine._mlx.calls == [("/models/turbo", False), ("/models/full", True)]
    assert short[0].text == "Last sicher halten!"
    assert short[0].raw_text == "Lass sicher halten"
    assert short[0].start == 0.2
    assert short[0].end == 1.1
    assert short[0].is_word is False
    assert short[0].safety_confirmation_raw_text == "Last sicher halten!"
    assert short[0].safety_confirmation_used is True
    assert long[0].text == "Langer Satz"
    assert long[0].raw_text == "Langer Satz"
    assert long[0].start == 0.2
    assert long[0].end == 1.1


def test_faster_whisper_transcribe_accepts_beam_override():
    model = _FakeTranscribeModel()
    engine = engine_module.WhisperEngine()

    engine._transcribe_faster_whisper_model(
        np.zeros(cfg.SAMPLE_RATE, dtype=np.float32),
        model,
        "de",
        beam_size_override=3,
    )

    assert model.kwargs["beam_size"] == 3


def test_turbo_safety_near_match_uses_exact_small_model_confirmation(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_SCORE", 0.82)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_MARGIN", 0.04)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    primary_call = {}

    def primary(*_args, **kwargs):
        primary_call.update(kwargs)
        return [engine_module.Segment("Lass sicher halten", 0.0, 1.0, 0.8)]

    monkeypatch.setattr(
        engine,
        "_transcribe_mlx",
        primary,
    )
    confirmation_model = object()
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: confirmation_model)
    confirmation_call = {}

    def confirm(
        audio,
        model,
        language,
        initial_prompt=None,
        *,
        beam_size_override=None,
    ):
        confirmation_call.update({
            "model": model,
            "language": language,
            "initial_prompt": initial_prompt,
            "beam_size_override": beam_size_override,
        })
        return [engine_module.Segment("Last sicher halten!", 0.0, 1.0, 0.9)]

    monkeypatch.setattr(engine, "_transcribe_faster_whisper_model", confirm)

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == "Last sicher halten!"
    assert output[0].raw_text == "Lass sicher halten"
    assert output[0].safety_command_id == "safety_load_hold"
    assert output[0].safety_rejection_reason == "not-allowlisted-exact"
    assert output[0].safety_confirmation_raw_text == "Last sicher halten!"
    assert output[0].safety_confirmation_model == (
        f"{cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY}"
        f"@{cfg.SAFETY_CONFIRMATION_MODEL_REVISION}"
    )
    assert output[0].safety_confirmation_used is True
    assert confirmation_call["model"] is confirmation_model
    assert confirmation_call["language"] == "de"
    assert confirmation_call["beam_size_override"] == 3
    assert confirmation_call["initial_prompt"] == cfg.WHISPER_INITIAL_PROMPT
    assert "Zulässige kurze Sicherheitskommandos" not in confirmation_call["initial_prompt"]
    assert primary_call["model_source"] == "/models/turbo"
    assert primary_call["model_role"] == "short"


def test_secondary_single_non_action_typo_confirms_same_primary_candidate(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(
        engine,
        "_transcribe_mlx",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Lass sicher halten", 0.0, 1.0, 0.8)
        ],
    )
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: object())
    monkeypatch.setattr(
        engine,
        "_transcribe_faster_whisper_model",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Lasst sicher halten", 0.0, 1.0, 0.9)
        ],
    )

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == "Last sicher halten!"
    assert output[0].raw_text == "Lass sicher halten"
    assert output[0].safety_command_id == "safety_load_hold"
    assert output[0].safety_confirmation_used is True
    assert output[0].safety_confirmation_raw_text == "Lasst sicher halten"


@pytest.mark.parametrize(
    ("primary_text", "secondary_text"),
    [
        ("Last sicher fallen", "Last sicher halten!"),
        ("Not-Aus sofort auslassen", "Not-Aus sofort auslösen!"),
        ("Bühne sofort sterben", "Bühne sofort sperren!"),
        ("Schutztor sicher erschließen", "Schutztor sicher schließen!"),
        ("Haltebremse verrigeln", "Haltebremse verriegeln!"),
        ("Gefahrenbereich träumen", "Gefahrenbereich räumen!"),
        ("Energiezufuhr rennen", "Energiezufuhr trennen!"),
    ],
)
def test_changed_action_token_never_reaches_or_accepts_confirmation(
    monkeypatch,
    primary_text,
    secondary_text,
):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(
        engine,
        "_transcribe_mlx",
        lambda *_args, **_kwargs: [
            engine_module.Segment(primary_text, 0.0, 1.0, 0.8)
        ],
    )
    confirmation_calls = []

    def confirm(*_args, **_kwargs):
        confirmation_calls.append(True)
        return [engine_module.Segment(secondary_text, 0.0, 1.0, 0.9)]

    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: object())
    monkeypatch.setattr(engine, "_transcribe_faster_whisper_model", confirm)

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == primary_text
    assert output[0].raw_text == primary_text
    assert output[0].safety_command_id is None
    assert output[0].safety_confirmation_used is False
    assert output[0].safety_confirmation_raw_text is None
    assert confirmation_calls == []


def test_secondary_exact_command_must_match_primary_best_candidate(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(
        engine,
        "_transcribe_mlx",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Lass sicher halten", 0.0, 1.0, 0.8)
        ],
    )
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: object())
    monkeypatch.setattr(
        engine,
        "_transcribe_faster_whisper_model",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Bühne sofort sperren!", 0.0, 1.0, 0.9)
        ],
    )

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == "Lass sicher halten"
    assert output[0].raw_text == "Lass sicher halten"
    assert output[0].safety_command_id is None
    assert output[0].safety_confirmation_used is True
    assert output[0].safety_confirmation_raw_text == "Bühne sofort sperren!"


def test_turbo_exact_stage_command_skips_small_confirmation(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    engine._short_mlx_resolved_model_path = "/models/turbo"
    monkeypatch.setattr(engine, "load", lambda: None)
    primary_call = {}

    def primary(*_args, **kwargs):
        primary_call.update(kwargs)
        return [engine_module.Segment("Bühne sofort sperren!", 0.0, 1.0, 0.9)]

    monkeypatch.setattr(engine, "_transcribe_mlx", primary)
    monkeypatch.setattr(
        engine,
        "_load_guard_fallback_model",
        lambda: (_ for _ in ()).throw(AssertionError("exact Turbo match needs no confirmation")),
    )

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == "Bühne sofort sperren!"
    assert output[0].raw_text == "Bühne sofort sperren!"
    assert output[0].safety_command_id == "safety_stage_lock"
    assert output[0].safety_confirmation_used is False
    assert primary_call["model_source"] == "/models/turbo"
    assert primary_call["model_role"] == "short"


def test_failed_safety_confirmation_preserves_primary_and_secondary_raw_audit(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "mlx"
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(
        engine,
        "_transcribe_mlx",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Lass sicher halten", 0.0, 1.0, 0.8)
        ],
    )
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: object())
    monkeypatch.setattr(
        engine,
        "_transcribe_faster_whisper_model",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Lass sicher fallen", 0.0, 1.0, 0.7)
        ],
    )

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].text == "Lass sicher halten"
    assert output[0].raw_text == "Lass sicher halten"
    assert output[0].safety_command_id is None
    assert output[0].safety_confirmation_raw_text == "Lass sicher fallen"
    assert output[0].safety_confirmation_model == (
        f"{cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY}"
        f"@{cfg.SAFETY_CONFIRMATION_MODEL_REVISION}"
    )
    assert output[0].safety_confirmation_used is True


def test_faster_whisper_primary_never_uses_safety_confirmation(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    engine._active_backend = "faster-whisper"
    engine._model = object()
    monkeypatch.setattr(engine, "load", lambda: None)
    monkeypatch.setattr(engine, "_select_language", lambda *_args, **_kwargs: "de")
    monkeypatch.setattr(
        engine,
        "_transcribe_faster_whisper_model",
        lambda *_args, **_kwargs: [
            engine_module.Segment("Haltebremse verrigeln", 0.0, 1.0, 0.8)
        ],
    )
    monkeypatch.setattr(
        engine,
        "_load_guard_fallback_model",
        lambda: (_ for _ in ()).throw(AssertionError("confirmation must be MLX-only")),
    )

    output = engine.transcribe(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert output[0].safety_command_id is None
    assert output[0].safety_rejection_reason == "not-allowlisted-exact"
    assert output[0].safety_confirmation_used is False


def test_safety_confirmation_never_runs_for_disallowed_primary_matches(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_SCORE", 0.82)
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MIN_MARGIN", 0.04)
    engine = engine_module.WhisperEngine()
    assert engine._safety_catalog is not None

    def unexpected_confirmation():
        raise AssertionError("safety confirmation must not run")

    monkeypatch.setattr(engine, "_load_guard_fallback_model", unexpected_confirmation)

    attempts = {
        "Haltebremse nicht verriegeln": "negation:nicht",
        "Haltebremse bitte verriegeln": "token-count-mismatch",
        "Haltebremse öffnen": "token-mismatch:öffnen",
        "Bremse verriegeln": "not-allowlisted-exact",
        "Haltebremse verriegeln!": None,
    }

    for text, expected_reason in attempts.items():
        output = engine._apply_safety_catalog(
            [engine_module.Segment(text, 0.0, 1.0, 0.8)],
            confirmation_audio=np.zeros(cfg.SAMPLE_RATE, dtype=np.float32),
            confirmation_language="de",
        )
        assert output[0].safety_rejection_reason == expected_reason
        assert output[0].safety_confirmation_used is False
        assert output[0].safety_confirmation_raw_text is None
        assert output[0].safety_confirmation_model is None


def test_status_reports_safety_confirmation_model_and_beam():
    engine = engine_module.WhisperEngine()
    engine._resolved_model_path = "/models/full"
    engine._model_revision = cfg.MLX_MODEL_REVISION
    engine._short_mlx_resolved_model_path = "/models/turbo"
    engine._short_mlx_model_revision = cfg.MLX_SHORT_MODEL_REVISION
    engine._last_mlx_model_role = "short"
    engine._last_mlx_model_source = "/models/turbo"
    engine._last_mlx_model_revision = cfg.MLX_SHORT_MODEL_REVISION
    status = engine.status()

    assert status["safety_confirmation_model"] == cfg.SAFETY_CONFIRMATION_MODEL_REPOSITORY
    assert status["safety_confirmation_model_revision"] == cfg.SAFETY_CONFIRMATION_MODEL_REVISION
    assert status["safety_confirmation_beam_size"] == 3
    assert status["safety_confirmation_error"] is None
    assert status["mlx_model_strategy"] == "original-duration-router"
    assert status["mlx_long_model"]["revision"] == cfg.MLX_MODEL_REVISION
    assert status["mlx_long_model"]["resolved_model_path"] == "/models/full"
    assert status["mlx_short_model"]["revision"] == cfg.MLX_SHORT_MODEL_REVISION
    assert status["mlx_short_model"]["resolved_model_path"] == "/models/turbo"
    assert status["mlx_short_model"]["max_original_audio_seconds"] == 3.0
    assert status["mlx_short_model"]["short_word_timestamps"] is False
    assert status["short_word_timestamps"] is False
    assert status["last_mlx_model_role"] == "short"
    assert status["last_mlx_model_source"] == "/models/turbo"


def test_mlx_load_preloads_safety_confirmation_without_changing_primary_on_failure(monkeypatch):
    monkeypatch.setattr(cfg, "SAFETY_COMMAND_MODE", True)
    engine = engine_module.WhisperEngine()
    monkeypatch.setattr(engine, "_load_mlx", lambda: None)
    monkeypatch.setattr(
        engine,
        "_load_guard_fallback_model",
        lambda: (_ for _ in ()).throw(RuntimeError("confirmation unavailable")),
    )

    engine.load()

    assert engine.active_backend == "mlx"
    assert engine.status()["safety_confirmation_error"] == "confirmation unavailable"


def test_custom_model_source_is_not_rewritten():
    source, revision = engine_module.WhisperEngine._resolve_model_source(
        "/models/custom",
        default_repository=cfg.MLX_MODEL_REPOSITORY,
        pinned_revision=cfg.MLX_MODEL_REVISION,
    )

    assert source == "/models/custom"
    assert revision is None


def test_pathology_guard_rejects_token_loop_and_script_drift():
    assert engine_module.WhisperEngine._pathology_reason(
        "Bau " * 80,
        duration_seconds=2.0,
        language="de",
    ) is not None
    assert engine_module.WhisperEngine._pathology_reason(
        "Du F 대 대 대",
        duration_seconds=2.0,
        language="de",
    ) == "unexpected-script"
    assert engine_module.WhisperEngine._pathology_reason(
        "KUHU" * 60,
        duration_seconds=3.0,
        language="de",
    ).startswith("character-loop:")


def test_pathology_guard_accepts_normal_german_transcript():
    assert engine_module.WhisperEngine._pathology_reason(
        "Achtung, bitte die Bühne sofort räumen.",
        duration_seconds=2.0,
        language="de",
    ) is None


def test_confirmation_policy_only_marks_short_audio(monkeypatch):
    monkeypatch.setattr(cfg, "SAMPLE_RATE", 10)
    monkeypatch.setattr(cfg, "ASR_CONFIRM_SHORT_SECONDS", 3.0)
    short = [engine_module.Segment("Stopp", 0.0, 1.0, 0.9)]
    long = [engine_module.Segment("Langer Satz", 0.0, 4.0, 0.9)]

    engine_module.WhisperEngine._apply_confirmation_policy(short, 30)
    engine_module.WhisperEngine._apply_confirmation_policy(long, 31)

    assert short[0].requires_confirmation is True
    assert long[0].requires_confirmation is False


def test_edge_padding_only_fills_missing_quiet_context(monkeypatch):
    monkeypatch.setattr(cfg, "ASR_EDGE_PADDING_SECONDS", 0.35)
    monkeypatch.setattr(cfg, "ASR_MIN_RMS", 0.01)
    audio = np.concatenate([
        np.zeros(int(0.2 * cfg.SAMPLE_RATE), dtype=np.float32),
        np.full(cfg.SAMPLE_RATE, 0.1, dtype=np.float32),
        np.zeros(int(0.35 * cfg.SAMPLE_RATE), dtype=np.float32),
    ])

    normalized, shift = engine_module.WhisperEngine._normalize_edge_context(audio)

    assert shift == -int(0.15 * cfg.SAMPLE_RATE)
    assert len(normalized) == len(audio) + int(0.15 * cfg.SAMPLE_RATE)
    assert np.all(normalized[: int(0.35 * cfg.SAMPLE_RATE)] == 0)
    assert np.all(normalized[-int(0.35 * cfg.SAMPLE_RATE) :] == 0)


def test_edge_context_trims_only_surplus_quiet_samples(monkeypatch):
    monkeypatch.setattr(cfg, "ASR_EDGE_PADDING_SECONDS", 0.35)
    monkeypatch.setattr(cfg, "ASR_MIN_RMS", 0.01)
    audio = np.concatenate([
        np.zeros(int(0.5 * cfg.SAMPLE_RATE), dtype=np.float32),
        np.full(cfg.SAMPLE_RATE, 0.1, dtype=np.float32),
        np.zeros(int(0.45 * cfg.SAMPLE_RATE), dtype=np.float32),
    ])

    normalized, shift = engine_module.WhisperEngine._normalize_edge_context(audio)

    assert shift == int(0.15 * cfg.SAMPLE_RATE)
    assert len(normalized) == len(audio) - int(0.25 * cfg.SAMPLE_RATE)
    assert np.all(normalized[: int(0.35 * cfg.SAMPLE_RATE)] == 0)
    assert np.all(normalized[-int(0.35 * cfg.SAMPLE_RATE) :] == 0)


def test_mlx_pathology_uses_fallback_without_changing_active_backend(monkeypatch):
    class _FakeMlx:
        kwargs = None

        def transcribe(self, *_args, **kwargs):
            self.kwargs = kwargs
            return {
                "language": "de",
                "segments": [{
                    "text": " 대 대 대 대 대 대",
                    "start": 0.0,
                    "end": 1.0,
                    "words": [],
                }],
            }

    fallback = _FakeTranscribeModel()
    engine = engine_module.WhisperEngine()
    engine._mlx = _FakeMlx()
    engine._mlx_warmed = True
    engine._active_backend = "mlx"
    engine._resolved_model_path = "/models/mlx"
    monkeypatch.setattr(engine, "_load_guard_fallback_model", lambda: fallback)

    segments = engine._transcribe_mlx(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32), language="de")

    assert [segment.text for segment in segments] == [" Hallo", " Regie"]
    assert engine.active_backend == "mlx"
    assert engine.status()["guard_fallback_count"] == 1
    assert engine._mlx.kwargs["temperature"] == 0.0
    assert "beam_size" not in engine._mlx.kwargs
    assert fallback.kwargs["beam_size"] == cfg.WHISPER_BEAM_SIZE
