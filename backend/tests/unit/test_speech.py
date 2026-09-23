"""Offline tests: byte strings and clients in this module are explicit fixtures."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import OpenAIError
from pydantic import ValidationError

from app.speech.errors import SpeechConfigurationError, SpeechProviderError
from app.speech.stt.base import MAX_AUDIO_BYTES, AudioInput
from app.speech.stt.openai_provider import OpenAISTTProvider
from app.speech.tts.base import MAX_SPEECH_CHARACTERS
from app.speech.tts.openai_provider import OpenAITTSProvider


@pytest.fixture
def audio_input() -> AudioInput:
    return AudioInput(audio=b"test audio fixture", filename="test.webm", content_type="audio/webm")


def mocked_client(monkeypatch: pytest.MonkeyPatch, module: str) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(f"{module}.AsyncOpenAI", constructor)
    return client


def test_missing_key_does_not_fail_until_invocation(
    monkeypatch: pytest.MonkeyPatch, audio_input: AudioInput
) -> None:
    stt_constructor = MagicMock(side_effect=AssertionError("Client must not be constructed."))
    tts_constructor = MagicMock(side_effect=AssertionError("Client must not be constructed."))
    monkeypatch.setattr("app.speech.stt.openai_provider.AsyncOpenAI", stt_constructor)
    monkeypatch.setattr("app.speech.tts.openai_provider.AsyncOpenAI", tts_constructor)
    stt = OpenAISTTProvider(api_key=None, model="test-model")
    tts = OpenAITTSProvider(api_key=None, model="test-model", voice="test-voice")
    with pytest.raises(SpeechConfigurationError, match="OPENAI_API_KEY"):
        asyncio.run(stt.transcribe(audio_input))
    with pytest.raises(SpeechConfigurationError, match="OPENAI_API_KEY"):
        asyncio.run(tts.synthesize("Test input", "ru"))
    stt_constructor.assert_not_called()
    tts_constructor.assert_not_called()


@pytest.mark.parametrize("size", [0, MAX_AUDIO_BYTES + 1], ids=["empty", "oversized"])
def test_audio_input_requires_nonempty_bounded_bytes(size: int) -> None:
    with pytest.raises(ValidationError):
        AudioInput(audio=b"x" * size, filename="test.wav", content_type="audio/wav")


@pytest.mark.parametrize(
    "text", ["", " \n", "x" * (MAX_SPEECH_CHARACTERS + 1)], ids=["empty", "blank", "oversized"]
)
def test_tts_rejects_empty_or_oversized_text(text: str) -> None:
    provider = OpenAITTSProvider(api_key=None, model="test-model", voice="test-voice")
    with pytest.raises(ValidationError):
        asyncio.run(provider.synthesize(text, "kk"))


@pytest.mark.parametrize("metadata", [{}, {"language": "russian", "duration": 1.5}])
def test_transcription_preserves_provider_metadata(
    monkeypatch: pytest.MonkeyPatch, audio_input: AudioInput, metadata: dict
) -> None:
    client = mocked_client(monkeypatch, "app.speech.stt.openai_provider")
    client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="Test transcript fixture", **metadata)
    )
    provider = OpenAISTTProvider(api_key="test-key", model="test-model")
    result = asyncio.run(provider.transcribe(audio_input))
    client.audio.transcriptions.create.assert_awaited_once_with(
        model="test-model",
        file=(audio_input.filename, audio_input.audio, audio_input.content_type),
        response_format="json",
    )
    assert result.text == "Test transcript fixture"
    assert result.detected_language == metadata.get("language")
    assert result.duration == metadata.get("duration")
    assert result.latency_ms >= 0
    client.__aexit__.assert_awaited_once()


def test_transcription_failure_is_explicit_and_payload_safe(
    monkeypatch: pytest.MonkeyPatch, audio_input: AudioInput
) -> None:
    client = mocked_client(monkeypatch, "app.speech.stt.openai_provider")
    client.audio.transcriptions.create = AsyncMock(side_effect=OpenAIError("private payload"))
    provider = OpenAISTTProvider(api_key="test-key", model="test-model")
    with pytest.raises(SpeechProviderError, match="transcription failed") as error:
        asyncio.run(provider.transcribe(audio_input))
    assert "private payload" not in str(error.value)


@pytest.mark.parametrize("chunks", [[b"", b"test ", b"MP3 fixture"], []])
def test_synthesis_reads_real_stream_interface_and_rejects_empty_audio(
    monkeypatch: pytest.MonkeyPatch, chunks: list[bytes]
) -> None:
    client = mocked_client(monkeypatch, "app.speech.tts.openai_provider")
    monkeypatch.setattr(
        "app.speech.tts.openai_provider.perf_counter", MagicMock(side_effect=[1.0, 1.125])
    )

    async def iter_bytes():
        for chunk in chunks:
            yield chunk

    response = MagicMock()
    response.iter_bytes = iter_bytes
    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=response)
    stream.__aexit__ = AsyncMock(return_value=None)
    client.audio.speech.with_streaming_response.create.return_value = stream
    provider = OpenAITTSProvider(api_key="test-key", model="test-model", voice="test-voice")

    if not chunks:
        with pytest.raises(SpeechProviderError, match="no audio"):
            asyncio.run(provider.synthesize("Test speech fixture", "mixed"))
    else:
        result = asyncio.run(provider.synthesize("Test speech fixture", "mixed"))
        assert result.audio == b"test MP3 fixture"
        assert result.content_type == "audio/mpeg"
        assert result.language == "mixed"
        assert result.first_audio_latency_ms == 125.0
    client.audio.speech.with_streaming_response.create.assert_called_once_with(
        model="test-model", voice="test-voice", input="Test speech fixture", response_format="mp3"
    )
    stream.__aexit__.assert_awaited_once()
    client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("error", [OpenAIError("private payload"), TimeoutError()])
def test_synthesis_failure_does_not_return_audio(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    client = mocked_client(monkeypatch, "app.speech.tts.openai_provider")
    client.audio.speech.with_streaming_response.create.side_effect = error
    provider = OpenAITTSProvider(api_key="test-key", model="test-model", voice="test-voice")
    with pytest.raises(SpeechProviderError, match="synthesis failed") as captured:
        asyncio.run(provider.synthesize("Test speech fixture", "ru"))
    assert "private payload" not in str(captured.value)
