"""Local progressive MP3 prototype, fixed synthetic samples only, never production ingress."""
# ruff: noqa: E402

import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.speech.tts.normalization import prepare_speech
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from openai import AsyncOpenAI

app = FastAPI()
settings = Settings()
samples = {
    row["id"]: row
    for row in json.loads((ROOT / "data/tts/eval_samples.json").read_text(encoding="utf-8"))
}


@app.get("/")
def page():
    return HTMLResponse("""<!doctype html><meta charset=utf-8><title>TTS streaming prototype</title>
    <h1>Synthetic TTS: browser playback timing</h1><p>No subjective scores are assigned.</p>
    <button onclick="run('buffered')">Buffered RU</button>
    <button onclick="run('streaming')">Streaming RU</button>
    <button onclick="run('streaming','kk_greeting')">Streaming KK</button>
    <button onclick="stop()">Cancel playback</button>
    <audio controls id=audio></audio><pre id=results></pre>
    <script>
    const player=document.querySelector('#audio'), output=document.querySelector('#results');
    let began=0, current='', heard=false;
    function stop(){player.pause();player.removeAttribute('src');player.load();}
    function run(mode,sample='ru_greeting'){
      stop();began=performance.now();current=mode+' '+sample;heard=false;
      player.src='/audio/'+mode+'/'+sample+'?run='+Date.now();player.play().catch(e=>output.textContent+=e.name+'\\n');}
    player.onplaying=()=>{if(!heard){heard=true;output.textContent+=JSON.stringify({case:current,first_audible_ms:performance.now()-began})+'\\n';}};
    player.onended=()=>output.textContent+=JSON.stringify({case:current,total_playback_ms:performance.now()-began,duration:player.duration})+'\\n';
    player.onerror=()=>output.textContent+='playback_failed\\n';
    </script>""")


@app.get("/audio/{mode}/{sample_id}")
async def audio(mode: str, sample_id: str):
    if mode not in {"buffered", "streaming"} or sample_id not in samples:
        raise HTTPException(404)
    sample = samples[sample_id]
    voice = (
        settings.backend_tts_voice_kk
        if sample["language"] == "kk"
        else settings.backend_tts_voice_ru
    ) or settings.backend_tts_voice
    started = perf_counter()
    first = None

    async def chunks():
        nonlocal first
        count = 0
        try:
            async with asyncio.timeout(60):
                async with AsyncOpenAI(
                    api_key=settings.openai_api_key.get_secret_value(),
                    timeout=60,
                    max_retries=0,
                ) as client:
                    async with client.audio.speech.with_streaming_response.create(
                        model=settings.backend_tts_model,
                        voice=voice,
                        input=prepare_speech(sample["text"], sample["language"]),
                        instructions=settings.backend_tts_instructions_kk
                        if sample["language"] == "kk"
                        else settings.backend_tts_instructions_ru,
                        response_format="mp3",
                    ) as stream:
                        async for chunk in stream.iter_bytes(chunk_size=4096):
                            if chunk:
                                first = first or (perf_counter() - started) * 1000
                                count += len(chunk)
                                if count > 8_000_000:
                                    raise ValueError("Prototype audio bound")
                                yield chunk
            print(
                json.dumps(
                    {
                        "sample": sample_id,
                        "mode": mode,
                        "first_chunk_ms": first,
                        "full_synthesis_ms": (perf_counter() - started) * 1000,
                        "bytes": count,
                    }
                ),
                flush=True,
            )
        except asyncio.CancelledError:
            print(
                json.dumps({"sample": sample_id, "mode": mode, "cancelled": True}),
                flush=True,
            )
            raise

    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if mode == "streaming":
        return StreamingResponse(chunks(), media_type="audio/mpeg", headers=headers)
    data = b"".join([chunk async for chunk in chunks()])
    return Response(data, media_type="audio/mpeg", headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8011)
