import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.speech.errors import SpeechProviderError
from app.speech.tts.factory import build_tts_provider
from app.speech.tts.normalization import prepare_speech
from app.speech.tts.openai_provider import OpenAITTSProvider


@pytest.mark.parametrize(
    "text,language,expected",
    [
        ("10,47%", "ru", "десять целых сорок семь сотых процента"),
        ("10,47 процента", "ru", "десять целых сорок семь сотых процента"),
        ("0,1%", "ru", "ноль целых одна десятая процента"),
        ("10 000 ₸", "ru", "десять тысяч тенге"),
        ("1 250,50 USD", "ru", "одна тысяча двести пятьдесят целых пятьдесят сотых доллара США"),
        ("21 USD", "ru", "двадцать один доллар США"),
        ("22 USD", "ru", "двадцать два доллара США"),
        ("11 USD", "ru", "одиннадцать долларов США"),
        ("10,47%", "kk", "он бүтін жүзден қырық жеті пайыз"),
        ("10 000 KZT", "kk", "он мың теңге"),
        ("1 250,50 USD", "kk", "бір мың екі жүз елу бүтін жүзден елу АҚШ доллары"),
        ("000123", "ru", "ноль ноль ноль один два три"),
        ("000123", "kk", "нөл нөл нөл бір екі үш"),
        ("+7 000 000 00 00", "ru", "плюс семь ноль ноль ноль ноль ноль ноль ноль ноль ноль ноль"),
        ("01.10.2026", "ru", "один октября, год две тысячи двадцать шесть"),
        ("2026-10-01", "kk", "бір қазан, жыл екі мың жиырма алты"),
        ("31.02.2026", "ru", "31.02.2026"),
        ("SQ-OGPO-123456", "ru", "SQ-OGPO-сто двадцать три тысячи четыреста пятьдесят шесть"),
    ],
)
def test_speech_values_are_preserved_without_rounding(text, language, expected):
    assert prepare_speech(text, language) == expected


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_speech_preparation_keeps_facts_and_plain_text_idempotent(language):
    text = "Риск высокий. Не сообщайте код. **10,47%**; 10 000 KZT.\n- Вопрос?"
    prepared = prepare_speech(text, language)
    assert text.startswith("Риск высокий.")
    assert "Риск высокий. Не сообщайте код." in prepared
    assert "Вопрос?" in prepared
    assert prepare_speech(prepared, language) == prepared
    assert "**" not in prepared


@pytest.mark.parametrize(
    "provider,key,expected",
    [
        ("auto", None, False),
        ("auto", "fixture", True),
        ("openai", "fixture", True),
        ("openai", None, False),
        ("browser", "fixture", False),
    ],
)
def test_backend_selection_never_substitutes_mock_or_unvalidated_local(provider, key, expected):
    actual = build_tts_provider(Settings(_env_file=None, tts_provider=provider, openai_api_key=key))
    assert isinstance(actual, OpenAITTSProvider) is expected


@pytest.mark.parametrize("language", ["ru", "kk"])
def test_openai_receives_normalized_text_and_configured_language_instructions(
    monkeypatch, language
):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    stream = MagicMock()
    response = MagicMock()

    async def chunks():
        yield b"fixture MP3"

    response.iter_bytes = chunks
    stream.__aenter__ = AsyncMock(return_value=response)
    stream.__aexit__ = AsyncMock(return_value=None)
    client.audio.speech.with_streaming_response.create.return_value = stream
    monkeypatch.setattr(
        "app.speech.tts.openai_provider.AsyncOpenAI", MagicMock(return_value=client)
    )
    provider = OpenAITTSProvider(
        api_key="fixture",
        model="gpt-4o-mini-tts",
        voice="marin",
        instructions_ru="RU configuration",
        instructions_kk="KK configuration",
    )
    result = asyncio.run(provider.synthesize("10,47%", language))
    assert result.language == language
    kwargs = client.audio.speech.with_streaming_response.create.call_args.kwargs
    assert kwargs["input"] == prepare_speech("10,47%", language)
    assert kwargs["instructions"] == f"{language.upper()} configuration"
    assert kwargs["voice"] == "marin"
    assert provider._active == 0


def test_provider_cancellation_closes_client_and_releases_capacity(monkeypatch):
    entered = asyncio.Event()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    stream = MagicMock()

    async def entering(*_):
        entered.set()
        await asyncio.Future()

    stream.__aenter__ = entering
    stream.__aexit__ = AsyncMock(return_value=None)
    client.audio.speech.with_streaming_response.create.return_value = stream
    monkeypatch.setattr(
        "app.speech.tts.openai_provider.AsyncOpenAI", MagicMock(return_value=client)
    )
    provider = OpenAITTSProvider(api_key="fixture", model="test", voice="test")

    async def flow():
        task = asyncio.create_task(provider.synthesize("Проверка", "ru"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(flow())
    assert provider._active == 0
    client.__aexit__.assert_awaited_once()


def test_provider_rejects_unbounded_normalized_output_and_concurrency():
    provider = OpenAITTSProvider(api_key="fixture", model="test", voice="test")
    with pytest.raises(SpeechProviderError, match="limit"):
        asyncio.run(provider.synthesize("123456789 " * 300, "ru"))
    provider._active = 2
    with pytest.raises(SpeechProviderError, match="busy"):
        asyncio.run(provider.synthesize("Проверка", "ru"))
