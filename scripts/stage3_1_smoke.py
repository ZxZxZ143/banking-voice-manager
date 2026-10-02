"""Live in-process reproduction, no fixture model responses or hidden retries."""

import asyncio
import json

from app.core.config import Settings
from app.core.services import build_services


async def main():
    services = build_services(Settings())
    result = await services.messages.process(
        "stage31-smoke", "", "insurance_manager", start_scenario=True
    )
    print(result.response_text, flush=True)
    for text in [
        "здравствуйте",
        "У меня проблема со страховкой",
        "разобраться с существующим",
        "у меня уже есть полис",
        "Хочу проверить срок действия",
        "87010000001",
    ]:
        result = await services.messages.process("stage31-smoke", text)
        print(
            json.dumps(
                {
                    "response": result.response_text,
                    "trace": result.trace.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        assert result.conversation_status not in {"ended", "handoff"}


if __name__ == "__main__":
    asyncio.run(main())
