import json
import struct
import uuid
import wave
from pathlib import Path

import pytest

from evaluation.synthesis_v2 import generate as synthesis


def write_pcm(path: Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(synthesis.CHANNELS)
        audio.setsampwidth(synthesis.SAMPLE_WIDTH)
        audio.setframerate(synthesis.SAMPLE_RATE)
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_specs_are_unicode_complete_and_leak_free() -> None:
    dev = synthesis.load_spec("dev")
    holdout = synthesis.load_spec("holdout")
    synthesis.validate_split_isolation(dev, holdout)

    assert holdout["seal_after_generation"] is True
    assert {item["voice"] for item in dev["utterances"]}.isdisjoint(
        item["voice"] for item in holdout["utterances"]
    )
    combined = " ".join(
        item["text"] for spec in (dev, holdout) for item in spec["utterances"]
    )
    assert "Bühne" in combined
    assert "Weiß" in combined
    assert not any(token in combined for token in ("Buehne", "fuer", "pruefe"))


def test_v3_is_explicit_additive_and_only_changes_pause_policy() -> None:
    for split in ("dev", "holdout"):
        v2 = synthesis.load_spec(split, "v2")
        v3 = synthesis.load_spec(split, "v3")
        assert v3["dataset_version"] == "synthetic_de_v3"
        assert v3["pause_seconds"] == 0.65
        assert int(v3["pause_seconds"] * synthesis.SAMPLE_RATE) == 10_400
        assert v3["trailing_guard_ms"] == 0
        assert v3["utterances"] == v2["utterances"]
    synthesis.validate_split_isolation(
        synthesis.load_spec("dev", "v3"),
        synthesis.load_spec("holdout", "v3"),
    )
    assert synthesis.spec_path("dev", "v2").name == "dev.json"
    assert synthesis.spec_path("dev", "v3").name == "dev_v3.json"


def test_v4_is_disjoint_from_v3_and_covers_production_messages() -> None:
    dev = synthesis.load_spec("dev", "v4")
    holdout = synthesis.load_spec("holdout", "v4")
    synthesis.validate_split_isolation(dev, holdout)

    assert synthesis.spec_path("holdout", "v4").name == "holdout_v4.json"
    assert len(dev["utterances"]) == len(holdout["utterances"]) == 8
    assert holdout["seal_after_generation"] is True
    for spec in (dev, holdout):
        assert spec["dataset_version"] == "synthetic_de_v4"
        assert spec["pause_seconds"] == 0.65
        assert spec["trailing_guard_ms"] == 0
        assert len({item["voice"] for item in spec["utterances"]}) == 4
        assert len({item["rate"] for item in spec["utterances"]}) >= 4
        categories = {
            category
            for item in spec["utterances"]
            for category in item["categories"]
        }
        assert {"short", "safety", "alphanumeric", "number", "technical"} <= categories

    v3_texts = {
        item["text"].casefold()
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, "v3")["utterances"]
    }
    v4_texts = {
        item["text"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
    }
    assert len(v4_texts) == 16
    assert v3_texts.isdisjoint(v4_texts)
    v3_holdout_names = {
        item["speaker"].casefold()
        for item in synthesis.load_spec("holdout", "v3")["utterances"]
    }
    assert v3_holdout_names.isdisjoint(
        item["speaker"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
    )


def test_v5_is_disjoint_from_prior_versions_and_covers_message_lengths() -> None:
    dev = synthesis.load_spec("dev", "v5")
    holdout = synthesis.load_spec("holdout", "v5")
    synthesis.validate_split_isolation(dev, holdout)

    assert synthesis.spec_path("dev", "v5").name == "dev_v5.json"
    assert len(dev["utterances"]) == len(holdout["utterances"]) == 12
    assert holdout["seal_after_generation"] is True
    for spec in (dev, holdout):
        assert spec["dataset_version"] == "synthetic_de_v5"
        assert spec["pause_seconds"] == 0.65
        assert spec["trailing_guard_ms"] == 0
        assert len({item["voice"] for item in spec["utterances"]}) == 4
        assert len({item["rate"] for item in spec["utterances"]}) >= 6
        categories = {
            category
            for item in spec["utterances"]
            for category in item["categories"]
        }
        assert {
            "short",
            "medium",
            "long",
            "safety",
            "alphanumeric",
            "number",
            "technical",
        } <= categories

    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    v5_texts = {
        item["text"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
    }
    assert len(v5_texts) == 24
    assert prior_texts.isdisjoint(v5_texts)


def test_v6_has_required_short_mix_and_is_disjoint_from_prior_versions() -> None:
    dev = synthesis.load_spec("dev", "v6")
    holdout = synthesis.load_spec("holdout", "v6")
    synthesis.validate_split_isolation(dev, holdout)

    assert synthesis.spec_path("holdout", "v6").name == "holdout_v6.json"
    assert len(dev["utterances"]) == len(holdout["utterances"]) == 16
    assert holdout["seal_after_generation"] is True
    for spec in (dev, holdout):
        assert spec["dataset_version"] == "synthetic_de_v6"
        assert spec["pause_seconds"] == 0.65
        assert spec["trailing_guard_ms"] == 0
        assert len({item["voice"] for item in spec["utterances"]}) == 4
        assert len({item["rate"] for item in spec["utterances"]}) >= 8
        short = [item for item in spec["utterances"] if "short" in item["categories"]]
        assert len(short) == 10
        assert sum("safety" in item["categories"] for item in short) >= 6
        assert sum("alphanumeric" in item["categories"] for item in short) >= 4
        assert sum("medium" in item["categories"] for item in spec["utterances"]) >= 3
        assert sum("long" in item["categories"] for item in spec["utterances"]) >= 3

    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4", "v5")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    v6_texts = {
        item["text"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
    }
    assert len(v6_texts) == 32
    assert prior_texts.isdisjoint(v6_texts)


def test_v7_binds_catalog_and_isolates_phrase_voice_and_rate() -> None:
    dev = synthesis.load_spec("dev", "v7")
    holdout = synthesis.load_spec("holdout", "v7")
    synthesis.validate_split_isolation(dev, holdout)

    assert synthesis.spec_path("dev", "v7").name == "dev_v7.json"
    assert len(dev["utterances"]) == len(holdout["utterances"]) == 16
    assert holdout["seal_after_generation"] is True
    assert dev["safety_catalog"] == holdout["safety_catalog"]
    assert dev["safety_catalog"]["sha256"] == (
        "9217165522fabb2b8559d7164b96a480085f6c5db3dc5c020dd0c10af3c5cfb8"
    )
    assert {item["rate"] for item in dev["utterances"]}.isdisjoint(
        item["rate"] for item in holdout["utterances"]
    )
    for spec in (dev, holdout):
        assert len({item["voice"] for item in spec["utterances"]}) == 4
        assert len({item["rate"] for item in spec["utterances"]}) == 8
        short = [item for item in spec["utterances"] if "short" in item["categories"]]
        assert len(short) == 10
        assert sum("safety" in item["categories"] for item in short) >= 6
        assert sum("alphanumeric" in item["categories"] for item in short) >= 4

    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4", "v5", "v6")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    v7_texts = {
        item["text"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
    }
    assert len(v7_texts) == 32
    assert prior_texts.isdisjoint(v7_texts)


def test_v8_closed_safety_catalog_is_shared_while_open_text_and_audio_inputs_are_isolated() -> None:
    dev = synthesis.load_spec("dev", "v8")
    holdout = synthesis.load_spec("holdout", "v8")
    synthesis.validate_split_isolation(dev, holdout)

    assert synthesis.spec_path("holdout", "v8").name == "holdout_v8.json"
    assert len(dev["utterances"]) == len(holdout["utterances"]) == 18
    assert holdout["seal_after_generation"] is True
    assert dev["safety_catalog"] == holdout["safety_catalog"]
    assert dev["safety_catalog"]["sha256"] == (
        "70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190"
    )
    assert {item["voice"] for item in dev["utterances"]}.isdisjoint(
        item["voice"] for item in holdout["utterances"]
    )
    assert {item["rate"] for item in dev["utterances"]}.isdisjoint(
        item["rate"] for item in holdout["utterances"]
    )

    safety_pairs = []
    for spec in (dev, holdout):
        safety = [
            item
            for item in spec["utterances"]
            if "closed_command" in item["categories"]
        ]
        alpha = [
            item
            for item in spec["utterances"]
            if "alphanumeric" in item["categories"]
            and "short" in item["categories"]
        ]
        assert len(safety) == 8
        assert len(alpha) == 4
        assert all("safety" in item["categories"] for item in safety)
        assert all("open_dictation" not in item["categories"] for item in safety)
        assert all("open_dictation" in item["categories"] for item in alpha)
        assert sum("medium" in item["categories"] for item in spec["utterances"]) == 3
        assert sum("long" in item["categories"] for item in spec["utterances"]) == 3
        safety_pairs.append(
            {(item["command_id"], item["text"]) for item in safety}
        )
    assert safety_pairs[0] == safety_pairs[1]

    dev_open = {
        item["text"].casefold()
        for item in dev["utterances"]
        if "open_dictation" in item["categories"]
    }
    holdout_open = {
        item["text"].casefold()
        for item in holdout["utterances"]
        if "open_dictation" in item["categories"]
    }
    assert dev_open.isdisjoint(holdout_open)

    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4", "v5", "v6", "v7")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    assert prior_texts.isdisjoint(dev_open | holdout_open)


def test_v9_adds_split_disjoint_safety_negative_ood_cases_to_frozen_catalog() -> None:
    dev = synthesis.load_spec("dev", "v9")
    holdout = synthesis.load_spec("holdout", "v9")
    synthesis.validate_split_isolation(dev, holdout)

    assert len(dev["utterances"]) == len(holdout["utterances"]) == 24
    assert holdout["seal_after_generation"] is True
    assert dev["safety_catalog"] == holdout["safety_catalog"]
    assert dev["safety_catalog"]["sha256"] == (
        "70afb86af75eac3bd1a639c0367f6c0121f544c5671ef1422171b10686220190"
    )
    assert {item["voice"] for item in dev["utterances"]}.isdisjoint(
        item["voice"] for item in holdout["utterances"]
    )
    assert {item["rate"] for item in dev["utterances"]}.isdisjoint(
        item["rate"] for item in holdout["utterances"]
    )

    positives = []
    negatives = []
    for spec in (dev, holdout):
        positive = [
            item for item in spec["utterances"] if "closed_command" in item["categories"]
        ]
        negative = [
            item
            for item in spec["utterances"]
            if "safety_negative_ood" in item["categories"]
        ]
        assert len(positive) == 8
        assert len(negative) == 6
        assert all(item["expected_command_id"] is None for item in negative)
        assert {item["negative_type"] for item in negative} == {
            "negation",
            "counter_command",
            "acoustic_near_miss",
        }
        assert sum("alphanumeric" in item["categories"] and "short" in item["categories"] for item in spec["utterances"]) == 4
        assert sum("medium" in item["categories"] for item in spec["utterances"]) == 3
        assert sum("long" in item["categories"] for item in spec["utterances"]) == 3
        positives.append({(item["command_id"], item["text"]) for item in positive})
        negatives.append(
            {
                item["negative_case_id"]: (item["negative_type"], item["text"])
                for item in negative
            }
        )
    assert positives[0] == positives[1]
    assert set(negatives[0]) == set(negatives[1])
    for case_id in negatives[0]:
        assert negatives[0][case_id][0] == negatives[1][case_id][0]
        assert negatives[0][case_id][1] != negatives[1][case_id][1]

    nonpositive_texts = {
        item["text"].casefold()
        for spec in (dev, holdout)
        for item in spec["utterances"]
        if "closed_command" not in item["categories"]
    }
    prior_texts = {
        item["text"].casefold()
        for version in ("v3", "v4", "v5", "v6", "v7", "v8")
        for split in ("dev", "holdout")
        for item in synthesis.load_spec(split, version)["utterances"]
    }
    assert prior_texts.isdisjoint(nonpositive_texts)


def test_reference_files_round_trip_exact_unicode(tmp_path: Path) -> None:
    spec = synthesis.load_spec("holdout")
    jsonl_path, text_path = synthesis.write_references(tmp_path, spec)

    records = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["text"] for record in records] == [
        item["text"] for item in spec["utterances"]
    ]
    assert text_path.read_text(encoding="utf-8").splitlines() == [
        item["text"] for item in spec["utterances"]
    ]


def test_destination_is_new_and_outside_raw_and_fixtures() -> None:
    build_id = f"unit-{uuid.uuid4().hex}"
    destination = synthesis.safe_build_destination("dev", build_id)

    assert synthesis.is_relative_to(destination, synthesis.GENERATED_ROOT.resolve())
    assert not any(
        synthesis.is_relative_to(destination, protected.resolve())
        for protected in synthesis.PROTECTED_ROOTS
    )
    assert "data/raw" not in destination.as_posix()
    assert "fixtures/audio" not in destination.as_posix()


@pytest.mark.parametrize("build_id", ["../raw", "/tmp/escape", "bad id", ""])
def test_unsafe_build_ids_are_rejected(build_id: str) -> None:
    with pytest.raises(synthesis.SynthesisError):
        synthesis.safe_build_destination("dev", build_id)


def test_concat_inserts_exactly_one_sample_exact_pause(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "combined.wav"
    write_pcm(first, [1000] * 100)
    write_pcm(second, [-1000] * 80)

    timeline = synthesis.concatenate_with_one_pause(
        [first, second], output, pause_frames=37
    )

    with wave.open(str(output), "rb") as audio:
        payload = audio.readframes(audio.getnframes())
        samples = struct.unpack(f"<{len(payload) // 2}h", payload)
    assert timeline == [(0, 100), (137, 217)]
    assert len(samples) == 217
    assert samples[100:137] == (0,) * 37
    assert 0 not in samples[:100]
    assert 0 not in samples[137:]


def test_trimming_removes_long_voice_tail_but_keeps_guard(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    trimmed = tmp_path / "trimmed.wav"
    active = [4000] * 1600
    trailing_zeroes = [0] * 6400
    write_pcm(source, active + trailing_zeroes)

    result = synthesis.trim_trailing_silence(source, trimmed)

    assert result["input_frames"] == 8000
    assert result["output_frames"] == 1600 + synthesis.SAMPLE_RATE * 20 // 1000
    assert result["trimmed_frames"] == 6080


def test_v3_trimming_has_no_added_end_guard(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    trimmed = tmp_path / "trimmed.wav"
    write_pcm(source, [4000] * 1600 + [0] * 6400)

    result = synthesis.trim_trailing_silence(
        source, trimmed, trailing_guard_ms=0
    )

    assert result["output_frames"] == 1600
    assert result["trailing_guard_ms"] == 0
    assert synthesis.final_frame_is_active(trimmed)


def test_sample_exact_pause_verifier_rejects_extra_or_nonzero_gap(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "combined.wav"
    write_pcm(first, [1000] * 100)
    write_pcm(second, [-1000] * 80)
    timeline = synthesis.concatenate_with_one_pause(
        [first, second], output, pause_frames=10_400
    )

    assert synthesis.verify_sample_exact_pauses(output, timeline, 10_400) == []
    assert synthesis.verify_sample_exact_pauses(output, timeline, 10_399)


def test_manifest_hash_and_holdout_seal_detect_mutation(tmp_path: Path) -> None:
    artifact = tmp_path / "reference.txt"
    artifact.write_text("Bühne frei?\n", encoding="utf-8")
    record = synthesis.artifact_record(artifact, tmp_path)
    manifest = {
        "schema_version": "2.0",
        "split": "holdout",
        "artifacts": [record],
    }
    (tmp_path / "manifest.json").write_bytes(
        synthesis.canonical_json_bytes(manifest)
    )

    assert synthesis.verify_manifest(tmp_path) == []
    synthesis.write_holdout_seal(tmp_path)
    assert synthesis.verify_holdout_seal(tmp_path) == []

    artifact.write_text("Bühne ist frei.\n", encoding="utf-8")
    assert "hash mismatch: reference.txt" in synthesis.verify_manifest(tmp_path)
    assert any(
        error.startswith("sealed ")
        for error in synthesis.verify_holdout_seal(tmp_path)
    )


def test_existing_build_is_never_overwritten(tmp_path: Path, monkeypatch) -> None:
    generated_root = tmp_path / "generated"
    monkeypatch.setattr(synthesis, "GENERATED_ROOT", generated_root)
    existing = generated_root / "dev" / "fixed-build"
    existing.mkdir(parents=True)

    with pytest.raises(synthesis.SynthesisError, match="Refusing to overwrite"):
        synthesis.safe_build_destination("dev", "fixed-build")
