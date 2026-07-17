from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import random
import tarfile
import wave

import pytest

from evaluation.import_fleurs import (
    FleursRow,
    import_fleurs,
    load_metadata_with_repairs,
    select_rows,
    verify_holdout_seal,
)


def _row(sentence_id: int, bucket: str, gender: str, suffix: int = 0) -> FleursRow:
    word_counts = {"short": 6, "medium": 14, "long": 24}
    words = " ".join(f"wort{index}" for index in range(word_counts[bucket]))
    filename = f"{sentence_id * 10 + suffix}.wav"
    return FleursRow(
        sentence_id=str(sentence_id),
        audio_filename=filename,
        raw_transcription=words.capitalize() + ".",
        normalized_transcription=words,
        phonemes="w o r t",
        sample_count=160,
        gender=gender,
    )


def _wav_bytes(frame_count: int = 160) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * frame_count)
    return output.getvalue()


def _write_source(
    tmp_path: Path,
    rows: list[FleursRow],
    prefix: str = "dev",
) -> tuple[Path, Path, dict[str, bytes]]:
    metadata = tmp_path / "source.tsv"
    metadata.write_text(
        "".join(
            "\t".join(
                [
                    row.sentence_id,
                    row.audio_filename,
                    row.raw_transcription,
                    row.normalized_transcription,
                    row.phonemes,
                    str(row.sample_count),
                    row.gender,
                ]
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    payloads = {row.audio_filename: _wav_bytes(row.sample_count) for row in rows}
    archive_path = tmp_path / "source.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        directory = tarfile.TarInfo(prefix)
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for filename in sorted(payloads):
            data = payloads[filename]
            member = tarfile.TarInfo(f"{prefix}/{filename}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return archive_path, metadata, payloads


def test_selection_is_order_independent_balanced_and_sentence_disjoint():
    rows = []
    sentence_id = 100
    for bucket in ("short", "medium", "long"):
        for gender in ("FEMALE", "MALE"):
            for _ in range(3):
                rows.append(_row(sentence_id, bucket, gender))
                sentence_id += 1
    shuffled = list(rows)
    random.Random(8675309).shuffle(shuffled)

    selected = select_rows(rows)
    selected_shuffled = select_rows(shuffled)

    assert [row.audio_filename for row in selected] == [row.audio_filename for row in selected_shuffled]
    assert len({row.sentence_id for row in selected}) == 12
    assert {bucket: sum(row.length_bucket == bucket for row in selected) for bucket in ("short", "medium", "long")} == {
        "short": 4,
        "medium": 4,
        "long": 4,
    }
    assert {gender: sum(row.gender == gender for row in selected) for gender in ("FEMALE", "MALE")} == {
        "FEMALE": 6,
        "MALE": 6,
    }


def test_metadata_parser_repairs_only_the_known_official_quoted_tab_shape(tmp_path):
    metadata = tmp_path / "quoted-tab.tsv"
    metadata.write_text(
        '1\t10.wav\tRaw text.\t"normalized text\tp h o n e m e s"\t160\tMALE\n',
        encoding="utf-8",
    )

    rows, repairs = load_metadata_with_repairs(metadata)

    assert rows[0].normalized_transcription == "normalized text"
    assert rows[0].phonemes == "p h o n e m e s"
    assert repairs == [
        {
            "line": 1,
            "audio_filename": "10.wav",
            "reason": "official TSV quote anomaly joined normalized text and phonemes",
        }
    ]


def test_import_rejects_archive_path_traversal(tmp_path):
    rows = []
    sentence_id = 100
    for bucket in ("short", "medium", "long"):
        for _ in range(4):
            rows.append(_row(sentence_id, bucket, "MALE"))
            sentence_id += 1
    archive_path, metadata, _ = _write_source(tmp_path, rows)
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("../escape.wav")
        data = _wav_bytes()
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))

    with pytest.raises(ValueError, match="Unsafe archive member path"):
        import_fleurs(archive_path, metadata, tmp_path / "out", tmp_path / "manifest.json")

    assert not (tmp_path / "escape.wav").exists()


def test_import_preserves_wav_bytes_and_writes_bound_development_manifest(tmp_path):
    rows = []
    sentence_id = 200
    for bucket in ("short", "medium", "long"):
        for gender in ("FEMALE", "MALE"):
            for _ in range(2):
                rows.append(_row(sentence_id, bucket, gender))
                sentence_id += 1
    archive_path, metadata, payloads = _write_source(tmp_path, rows)
    output_dir = tmp_path / "audio"
    manifest_path = tmp_path / "manifest.json"

    first = import_fleurs(archive_path, metadata, output_dir, manifest_path)
    first_bytes = manifest_path.read_bytes()
    second = import_fleurs(archive_path, metadata, output_dir, manifest_path)

    assert first == second
    assert first_bytes == manifest_path.read_bytes()
    assert first["official_split"] == "dev"
    assert first["usage"] == "development"
    assert first["is_holdout"] is False
    assert first["license"]["spdx_id"] == "CC-BY-4.0"
    assert first["selection"]["selected_count"] == 12
    assert first["selection"]["unique_sentence_ids"] == 12
    assert first["selection"]["asr_outputs_used_for_selection"] is False
    assert first["selection"]["length_buckets"] == {"long": 4, "medium": 4, "short": 4}
    assert first["selection"]["selected_gender_counts"] == {"FEMALE": 6, "MALE": 6}
    assert first["source"]["archive_sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert first["source"]["metadata_sha256"] == hashlib.sha256(metadata.read_bytes()).hexdigest()

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted == first
    for clip in first["clips"]:
        copied = (output_dir / clip["fleurs_audio_filename"]).read_bytes()
        original = payloads[clip["fleurs_audio_filename"]]
        assert copied == original
        assert clip["sha256"] == hashlib.sha256(original).hexdigest()
        assert clip["sample_rate_hz"] == 16_000
        assert clip["channels"] == 1
        assert clip["frame_count"] == 160


def test_test_split_requires_test_tar_prefix(tmp_path):
    rows = []
    sentence_id = 300
    for bucket in ("short", "medium", "long"):
        for _ in range(4):
            rows.append(_row(sentence_id, bucket, "MALE"))
            sentence_id += 1
    archive_path, metadata, _ = _write_source(tmp_path, rows, prefix="dev")

    with pytest.raises(ValueError, match="Unexpected archive directory"):
        import_fleurs(
            archive_path,
            metadata,
            tmp_path / "audio",
            tmp_path / "manifest.json",
            official_split="test",
            seal_path=tmp_path / "seal.json",
        )


def test_test_split_writes_deterministic_seal_and_detects_tampering(tmp_path):
    rows = []
    sentence_id = 400
    for bucket in ("short", "medium", "long"):
        for gender in ("FEMALE", "MALE"):
            for _ in range(2):
                rows.append(_row(sentence_id, bucket, gender))
                sentence_id += 1
    archive_path, metadata, payloads = _write_source(tmp_path, rows, prefix="test")
    output_dir = tmp_path / "holdout"
    manifest_path = tmp_path / "holdout.json"
    seal_path = tmp_path / "holdout.seal.json"

    first = import_fleurs(
        archive_path,
        metadata,
        output_dir,
        manifest_path,
        official_split="test",
        seal_path=seal_path,
    )
    manifest_bytes = manifest_path.read_bytes()
    seal_bytes = seal_path.read_bytes()
    seal = verify_holdout_seal(manifest_path, output_dir, seal_path)
    second = import_fleurs(
        archive_path,
        metadata,
        output_dir,
        manifest_path,
        official_split="test",
        seal_path=seal_path,
    )

    assert first == second
    assert manifest_path.read_bytes() == manifest_bytes
    assert seal_path.read_bytes() == seal_bytes
    assert first["official_split"] == "test"
    assert first["usage"] == "holdout"
    assert first["is_holdout"] is True
    assert first["holdout_seal"]["required"] is True
    assert seal["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert seal["clip_count"] == 12
    assert {clip["filename"] for clip in seal["clips"]} == set(payloads)

    target_name = seal["clips"][0]["filename"]
    target = output_dir / target_name
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="byte size mismatch"):
        verify_holdout_seal(manifest_path, output_dir, seal_path)

    target.write_bytes(payloads[target_name])
    verify_holdout_seal(manifest_path, output_dir, seal_path)
    (output_dir / "unexpected.wav").write_bytes(_wav_bytes())
    with pytest.raises(ValueError, match="file set mismatch"):
        verify_holdout_seal(manifest_path, output_dir, seal_path)
