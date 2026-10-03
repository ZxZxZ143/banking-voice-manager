"""Shared browser/phone selection. Local prototypes are not quality-approved yet."""

from app.speech.tts.openai_provider import OpenAITTSProvider


def build_tts_provider(settings):
    if settings.tts_provider == "browser":
        return None
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        return None
    if not settings.backend_tts_model or not settings.backend_tts_voice:
        return None
    if not settings.backend_tts_model.strip() or not settings.backend_tts_voice.strip():
        return None
    return OpenAITTSProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.backend_tts_model,
        voice=settings.backend_tts_voice,
        voice_ru=settings.backend_tts_voice_ru,
        voice_kk=settings.backend_tts_voice_kk,
        instructions_ru=settings.backend_tts_instructions_ru,
        instructions_kk=settings.backend_tts_instructions_kk,
    )
