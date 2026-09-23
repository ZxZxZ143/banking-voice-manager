from app.speech.stt.endpointing import PauseTracker


def advance(tracker, speech, count):
    return [tracker.step(speech) for _ in range(count)]


def test_silence_alone_never_commits():
    tracker = PauseTracker(2500)
    assert not any(advance(tracker, False, 400))


def test_two_second_hesitation_does_not_commit_and_continuation_resets_timer():
    tracker = PauseTracker(2500)
    advance(tracker, True, 10)
    assert not any(advance(tracker, False, 63))
    advance(tracker, True, 10)
    assert not any(advance(tracker, False, 78))
    assert tracker.step(False)


def test_short_impulse_is_not_enough_speech():
    tracker = PauseTracker(500)
    advance(tracker, True, 1)
    assert not any(advance(tracker, False, 50))


def test_short_confirmations_are_not_required_to_last_a_second():
    tracker = PauseTracker(500)
    advance(tracker, True, 4)
    assert advance(tracker, False, 16)[-1]
