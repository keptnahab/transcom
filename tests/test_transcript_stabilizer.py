from backend.transcript.stabilizer import TranscriptStabilizer
from backend.transcript.stabilizer import TimedWordStabilizer
from backend.transcription.engine import Segment


def test_emits_only_new_suffix_after_overlap():
    stabilizer = TranscriptStabilizer()

    assert stabilizer.accept("ch1", "Hallo Regie, dies ist") == "Hallo Regie, dies ist"
    assert stabilizer.accept("ch1", "dies ist Anna auf Kanal eins.") == "Anna auf Kanal eins."


def test_suppresses_repeated_segment():
    stabilizer = TranscriptStabilizer()

    assert stabilizer.accept("ch1", "Copy that, this is Daniel.") == "Copy that, this is Daniel."
    assert stabilizer.accept("ch1", "Copy that, this is Daniel.") == ""


def test_keeps_channels_independent():
    stabilizer = TranscriptStabilizer()

    assert stabilizer.accept("left", "Bitte pruefen") == "Bitte pruefen"
    assert stabilizer.accept("right", "Bitte pruefen") == "Bitte pruefen"


def test_no_overlap_emits_original_text():
    stabilizer = TranscriptStabilizer()

    assert stabilizer.accept("ch1", "Hallo Regie") == "Hallo Regie"
    assert stabilizer.accept("ch1", "Please stand by.") == "Please stand by."


def test_timed_words_emit_only_stable_suffix():
    stabilizer = TimedWordStabilizer()
    words = [
        Segment(" Hallo", 0.0, 0.2, 0.99, is_word=True),
        Segment(" Regie", 0.2, 0.6, 0.99, is_word=True),
        Segment(" dies", 0.8, 1.1, 0.99, is_word=True),
    ]

    accepted = stabilizer.accept("ch1", words, window_start_ts=10.0, stable_until_ts=10.7)

    assert accepted is not None
    assert accepted.text == "Hallo Regie"
    assert accepted.start == 10.0
    assert accepted.end == 10.6


def test_timed_words_propagate_confirmation_policy_and_zero_confidence():
    stabilizer = TimedWordStabilizer()
    accepted = stabilizer.accept(
        "ch1",
        [Segment(" Stopp", 0.0, 0.4, 0.0, is_word=True, requires_confirmation=True)],
        window_start_ts=10.0,
        stable_until_ts=11.0,
    )

    assert accepted is not None
    assert accepted.confidence == 0.0
    assert accepted.requires_confirmation is True


def test_timed_words_preserve_pre_normalization_raw_text():
    stabilizer = TimedWordStabilizer()
    accepted = stabilizer.accept(
        "ch1",
        [Segment(" siebenundsechzig", 0.0, 0.4, 0.9, is_word=True, raw_text=" 67")],
        window_start_ts=10.0,
        stable_until_ts=11.0,
    )

    assert accepted is not None
    assert accepted.text == "siebenundsechzig"
    assert accepted.raw_text == "67"


def test_timed_words_suppress_repeated_overlap_word():
    stabilizer = TimedWordStabilizer()

    first = stabilizer.accept(
        "ch1",
        [Segment(" Signal.", 0.0, 0.4, 0.99, is_word=True)],
        window_start_ts=10.0,
        stable_until_ts=11.0,
    )
    repeated = stabilizer.accept(
        "ch1",
        [Segment(" Signal.", 0.0, 0.4, 0.99, is_word=True)],
        window_start_ts=10.5,
        stable_until_ts=11.5,
    )

    assert first is not None
    assert first.text == "Signal."
    assert repeated is None


def test_timed_words_preserve_genuine_immediate_repetition():
    stabilizer = TimedWordStabilizer()
    accepted = stabilizer.accept(
        "ch1",
        [
            Segment(" Nein", 0.0, 0.25, 0.99, is_word=True),
            Segment(", nein!", 0.28, 0.55, 0.99, is_word=True),
        ],
        window_start_ts=10.0,
        stable_until_ts=11.0,
    )

    assert accepted is not None
    assert accepted.text == "Nein, nein!"


def test_timed_words_skip_words_that_start_before_committed_end():
    stabilizer = TimedWordStabilizer()

    assert stabilizer.accept(
        "ch1",
        [
            Segment(" dies", 0.0, 0.3, 0.99, is_word=True),
            Segment(" ist", 0.3, 0.6, 0.99, is_word=True),
            Segment(" Anna", 0.6, 0.9, 0.99, is_word=True),
        ],
        window_start_ts=10.0,
        stable_until_ts=12.0,
    )
    accepted = stabilizer.accept(
        "ch1",
        [
            Segment(" ist", 0.2, 0.7, 0.99, is_word=True),
            Segment(" Anna", 0.7, 1.0, 0.99, is_word=True),
            Segment(" Wir", 1.0, 1.3, 0.99, is_word=True),
        ],
        window_start_ts=10.5,
        stable_until_ts=12.0,
    )

    assert accepted is not None
    assert accepted.text == "Wir"


def test_timed_words_allow_same_word_later_in_new_utterance():
    stabilizer = TimedWordStabilizer()

    first = stabilizer.accept(
        "ch1",
        [Segment(" Copy", 0.0, 0.3, 0.99, is_word=True)],
        window_start_ts=10.0,
        stable_until_ts=11.0,
    )
    second = stabilizer.accept(
        "ch1",
        [Segment(" Copy", 0.0, 0.3, 0.99, is_word=True)],
        window_start_ts=13.0,
        stable_until_ts=14.0,
    )

    assert first is not None
    assert second is not None
    assert second.text == "Copy"
