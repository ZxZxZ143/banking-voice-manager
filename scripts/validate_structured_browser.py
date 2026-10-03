"""Local synthetic browser audio harness: live STT, real core, fixture business router.

Run from repository root. No microphone, PSTN, customer data, or production database.
"""

# ruff: noqa: E402
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.main import create_app
from app.packs.insurance_manager.agent.schemas import RouterDecision
from app.packs.insurance_manager.state import ConversationState, DialogState
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

FIXTURE_IDS = [
    "region_code-02",
    "phone-04",
    "iin-01",
    "policy_number-01",
    "vehicle_plate-01",
]
fixtures = {
    row["id"]: row
    for row in json.loads((ROOT / "data/speech/structured_utterances.json").read_text("utf-8"))
    if row["id"] in FIXTURE_IDS
}
sessions = {}


class FixtureRouter:
    async def route(self, text, state):
        return RouterDecision(
            language=state.response_language,
            scenarios=[
                dict(
                    scenario_id=state.active_scenario,
                    confidence=0.95,
                    reason="Synthetic browser fixture business router",
                )
            ],
        )


app = create_app(
    Settings(
        frontend_origin="http://127.0.0.1:8012",
        event_db_path=ROOT / "work/structured-speech/harness.db",
        twilio_enabled=False,
        vonage_enabled=False,
        enable_dev_stand=False,
    ),
    router_override=FixtureRouter(),
)


@app.get("/validation/seed/{fixture_id}")
def seed(fixture_id: str):
    if fixture_id not in fixtures:
        raise HTTPException(404)
    row = fixtures[fixture_id]
    slot = "region" if row["kind"] == "region_code" else row["kind"]
    session_id = str(uuid4())
    sessions[session_id] = row
    app.state.services.dialogs.save(
        DialogState(
            session_id=session_id,
            active_scenario="SC01" if slot in {"region", "vehicle_plate"} else "SC25",
            slots={"vehicle_type": "car"},
            response_language="kk" if row["language"] == "kk" else "ru",
            conversation=ConversationState(expected_slot=slot),
        )
    )
    return {"session_id": session_id, "expected_kind": row["kind"]}


@app.get("/validation/audio/{fixture_id}")
def sample(fixture_id: str):
    if fixture_id not in fixtures:
        raise HTTPException(404)
    return FileResponse(
        ROOT / "work/structured-speech" / (fixture_id + ".mp3"), media_type="audio/mpeg"
    )


@app.get("/validation/check/{session_id}")
def check(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404)
    row = sessions[session_id]
    slot = "region" if row["kind"] == "region_code" else row["kind"]
    state = app.state.services.dialogs.get(session_id)
    expected = "almaty" if slot == "region" else row["expected"]
    result = dict(
        fixture=row["id"],
        canonical_correct=state.slots.get(slot) == expected,
        progressed=state.conversation.expected_slot != slot,
        next_slot=state.conversation.expected_slot,
        status=state.conversation_status,
    )
    with (ROOT / "work/structured-speech/browser-results.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(result) + "\n")
    return result


@app.get("/")
def page():
    buttons = "".join(f"<button onclick=\"run('{fid}')\">{fid}</button>" for fid in FIXTURE_IDS)
    return HTMLResponse(
        """<!doctype html><meta charset=utf-8><title>Structured speech validation</title>
    <h1>Synthetic browser audio validation</h1>
    <p>Live OpenAI STT; real parser/core/business lookups; fixture scenario router.
    No microphone/PSTN.</p>
    """
        + buttons
        + """<pre id=results></pre><script>
    const output=document.querySelector('#results');
    let busy=false;
    async function run(id){if(busy)return;busy=true;
      const buttons=[...document.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
      let context,ws;
      try{
        output.textContent+='Running '+id+'\\n';
        const seed=await (await fetch('/validation/seed/'+id)).json();
        context=new AudioContext({sampleRate:24000});await context.resume();
        const file=await(await fetch('/validation/audio/'+id)).arrayBuffer();
        const audio=await context.decodeAudioData(file);
        const samples=audio.getChannelData(0), began=performance.now();
        const final=await new Promise((resolve,reject)=>{
          ws=new WebSocket('ws://'+location.host+'/api/v1/voice');
          const deadline=setTimeout(()=>{ws.close();reject(Error('bounded timeout'));},145000);
          ws.onopen=()=>ws.send(JSON.stringify({type:'start',session_id:seed.session_id,
            sample_rate:24000,channels:1,pause_ms:2500}));
          ws.onerror=()=>{clearTimeout(deadline);reject(Error('connection failed'));};
          ws.onmessage=async ({data})=>{
            const event=JSON.parse(data);
            if(event.type==='ready'){
              const started=performance.now();
              for(let offset=0;offset<samples.length && ws.readyState===1;offset+=2400){
                const buffer=new ArrayBuffer(4800),view=new DataView(buffer);
                for(let i=0;i<2400;i++)view.setInt16(i*2,
                  Math.round(Math.max(-1,Math.min(1,samples[offset+i]??0))*32767),true);
                const delay=Math.max(0,started+(offset+2400)/24-performance.now());
                await new Promise(r=>setTimeout(r,delay));
                if(ws.readyState===1)ws.send(buffer);
              }
              if(ws.readyState===1)ws.send(JSON.stringify({type:'finish'}));
            }else if(event.type==='utterance.final'){clearTimeout(deadline);resolve(event);}
            else if(event.type==='error'||event.type==='empty'){
              clearTimeout(deadline);reject(Error(event.message||event.type));
            }
          };
        });
        output.textContent+=JSON.stringify({raw_transcript:final.text,recognition:final.recognition})+'\\n';
        const response=await fetch('/api/message',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({session_id:seed.session_id,text:final.text,channel:'voice',
                               recognition_id:final.recognition_id})});
        if(!response.ok)throw Error('message status '+response.status);
        const message=await response.json();
        const result=await(await fetch('/validation/check/'+seed.session_id)).json();
        output.textContent+=JSON.stringify({...result,reply:message.response_text,
          total_ms:performance.now()-began})+'\\n';
      }catch(error){output.textContent+='Failed '+id+': '+error.message+'\\n';}
      finally{ws?.close();await context?.close();busy=false;buttons.forEach(b=>b.disabled=false);}
    }
    </script>"""
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8012)
