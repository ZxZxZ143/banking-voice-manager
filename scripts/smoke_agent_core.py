"""Paced live API smoke checks using fresh synthetic conversations.

Run against a separately started backend (this script never reads credentials):
    ./.venv/Scripts/python.exe scripts/smoke_agent_core.py --pace-seconds 15

Nine successful message requests can invoke the configured model. A final request
checks closed-session rejection. Calls are sequential, with no automatic retries.
Only bounded routing/status/language/timing summaries are printed, never payloads.
These fixtures are hand-written smoke examples, not development-evaluation data.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

STATUSES = {"active", "awaiting_user", "awaiting_confirmation", "handoff", "ended"}
LANGUAGES = {"ru", "kk", "mixed"}
READ_ONLY_ACTIONS = {
    "kb_lookup",
    "get_offices",
    "find_client",
    "get_policy",
    "get_claim",
}
SCENARIO_ID = re.compile(r"(?:SC\d{2}|SYS_(?:UNCLEAR|OUT_OF_SCOPE|GOODBYE))\Z")


class SmokeFailure(Exception):
    """Contains only fixed diagnostics and bounded metadata, never API payloads."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    scenarios: tuple[str, ...]
    language: str
    status: str
    active: str | None = None
    pending: tuple[str, ...] = ()


CASES = (
    Case(
        "ru-office",
        "Подскажите, пожалуйста, в какие часы открыт ваш офис в Астане?",
        ("SC33",),
        "ru",
        "active",
    ),
    Case(
        "kk-payment",
        "Полис ақысын қандай тәсілдермен төлеуге болады?",
        ("SC31",),
        "kk",
        "active",
    ),
    Case(
        "mixed-renewal",
        "Полисті продлить хочу, срок скоро аяқталады.",
        ("SC27",),
        "mixed",
        "awaiting_user",
        active="SC27",
    ),
    Case(
        "multiple-intents",
        "Хочу продлить страховой полис и внести в него ещё одного водителя.",
        ("SC27", "SC04"),
        "ru",
        "awaiting_user",
        active="SC27",
        pending=("SC04",),
    ),
    Case(
        "unclear",
        "Хочу уточнить кое-что по страховке, но пока не могу сформулировать вопрос.",
        ("SYS_UNCLEAR",),
        "ru",
        "awaiting_user",
    ),
    Case(
        "out-of-scope",
        "Можно заказать у вас доставку овощей на завтра?",
        ("SYS_OUT_OF_SCOPE",),
        "ru",
        "awaiting_user",
    ),
)


def validate_contract(body: object, session_id: str, text: str, turn: int) -> list[str]:
    require(isinstance(body, dict), "response must be an object")
    require(
        {
            "session_id",
            "response_text",
            "routing",
            "state",
            "trace",
            "conversation_status",
        }
        <= body.keys(),
        "response is missing required fields",
    )
    require(body["session_id"] == session_id, "response session ID mismatch")
    require(
        isinstance(body["response_text"], str) and bool(body["response_text"].strip()),
        "response_text must be a nonblank string",
    )
    status = body["conversation_status"]
    require(
        isinstance(status, str) and status in STATUSES, "invalid conversation status"
    )
    routing, state, trace = (body[key] for key in ("routing", "state", "trace"))
    require(
        all(isinstance(value, dict) for value in (routing, state, trace)),
        "invalid objects",
    )
    language = routing.get("language")
    require(
        isinstance(language, str) and language in LANGUAGES, "invalid routing language"
    )
    selections = routing.get("scenarios")
    require(
        isinstance(selections, list) and bool(selections), "missing scenario selections"
    )
    ids = []
    for selection in selections:
        require(isinstance(selection, dict), "invalid scenario selection")
        scenario_id = selection.get("scenario_id")
        require(
            isinstance(scenario_id, str)
            and SCENARIO_ID.fullmatch(scenario_id) is not None,
            "invalid scenario identifier",
        )
        confidence = selection.get("confidence")
        require(number(confidence) and confidence <= 1, "invalid scenario confidence")
        require(isinstance(selection.get("reason"), str), "missing scenario reason")
        ids.append(scenario_id)
    require(len(ids) == len(set(ids)), "duplicate scenario selections")
    require(isinstance(routing.get("slots"), dict), "routing slots must be an object")
    require(
        isinstance(routing.get("alternatives"), list),
        "routing alternatives must be a list",
    )
    require(state.get("session_id") == session_id, "state session ID mismatch")
    require(state.get("turn_number") == turn, "state turn did not advance exactly once")
    require(
        state.get("conversation_status") == status, "state conversation status mismatch"
    )
    require(state.get("language") == language, "state language mismatch")
    require(state.get("response_language") in ("ru", "kk"), "invalid response language")
    require(isinstance(state.get("slots"), dict), "state slots must be an object")
    require(isinstance(state.get("scenario_stack"), list), "state stack must be a list")
    require(
        isinstance(state.get("pending_scenarios"), list),
        "pending scenarios must be a list",
    )
    history = state.get("history")
    require(
        isinstance(history, list) and len(history) == turn * 2,
        "unexpected history length",
    )
    require(
        history[-2] == {"role": "user", "text": text}, "latest user history mismatch"
    )
    require(
        history[-1] == {"role": "assistant", "text": body["response_text"]},
        "latest assistant history mismatch",
    )
    require(trace.get("session_id") == session_id, "trace session ID mismatch")
    require(
        trace.get("turn") == turn and trace.get("turn_number") == turn,
        "trace turn mismatch",
    )
    require(trace.get("transcript") == text, "trace transcript mismatch")
    require(trace.get("conversation_status") == status, "trace status mismatch")
    require(
        trace.get("active_scenario") == state.get("active_scenario"),
        "trace active mismatch",
    )
    require(
        trace.get("pending_scenarios") == state["pending_scenarios"],
        "trace pending mismatch",
    )
    require(trace.get("scenarios") == selections, "trace selections mismatch")
    actions = trace.get("actions")
    require(isinstance(actions, list), "trace actions must be a list")
    require(
        all(
            isinstance(action, str) and action in READ_ONLY_ACTIONS
            for action in actions
        ),
        "unexpected non-read-only action",
    )
    require(isinstance(trace.get("source_keys"), list), "missing trace source keys")
    latency = trace.get("latency_ms")
    require(isinstance(latency, dict), "missing latency object")
    for component in ("router", "policy", "response", "total"):
        require(number(latency.get(component)), f"invalid {component} latency")
    for component in ("router", "policy", "response"):
        require(
            latency[component] <= latency["total"], "component latency exceeds total"
        )
    return ids


class SmokeRunner:
    def __init__(self, client: httpx.Client, pace_seconds: float) -> None:
        self.client = client
        self.pace_seconds = pace_seconds
        self.last_finished: float | None = None
        self.label = "startup"
        self.summary = ""
        self.requests = 0

    def request(
        self, label: str, session_id: str, text: str
    ) -> tuple[httpx.Response, float]:
        self.label, self.summary = label, ""
        if self.last_finished is not None:
            time.sleep(
                max(0.0, self.pace_seconds - (time.monotonic() - self.last_finished))
            )
        started = time.perf_counter()
        self.requests += 1
        try:
            response = self.client.post(
                "api/message", json={"session_id": session_id, "text": text}
            )
        except httpx.HTTPError as exc:
            raise SmokeFailure(
                f"HTTP transport failed ({type(exc).__name__}); no retry"
            ) from None
        finally:
            self.last_finished = time.monotonic()
        return response, (time.perf_counter() - started) * 1000

    @staticmethod
    def json_body(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            raise SmokeFailure("response is not valid JSON") from None

    def turn(
        self, case: Case, session_id: str, turn: int = 1, previous: dict | None = None
    ) -> dict:
        response, elapsed = self.request(case.name, session_id, case.text)
        require(response.status_code == 200, f"unexpected HTTP {response.status_code}")
        body = self.json_body(response)
        ids = validate_contract(body, session_id, case.text, turn)
        state, trace = body["state"], body["trace"]
        timing = trace["latency_ms"]
        self.summary = (
            f"scenarios={','.join(ids)} status={body['conversation_status']} "
            f"language={body['routing']['language']} turn={turn} "
            f"http_ms={elapsed:.0f} router_ms={timing['router']:.0f} total_ms={timing['total']:.0f}"
        )
        require(set(ids) == set(case.scenarios), "unexpected scenario selection")
        require(
            body["routing"]["language"] == case.language, "unexpected detected language"
        )
        if case.language in {"ru", "kk"}:
            require(
                body["state"]["response_language"] == case.language,
                "unexpected response language for monolingual smoke input",
            )
        require(
            body["conversation_status"] == case.status, "unexpected conversation status"
        )
        require(state["active_scenario"] == case.active, "unexpected active scenario")
        require(
            state["pending_scenarios"] == list(case.pending),
            "unexpected pending scenarios",
        )
        if previous is not None:
            require(
                state["history"][:-2] == previous["state"]["history"],
                "earlier history changed",
            )
        if case.name == "unclear":
            require(
                trace.get("clarification") is True, "unclear request did not clarify"
            )
            require(
                trace.get("policy_outcome") == "clarify",
                "unclear policy outcome mismatch",
            )
        if case.name == "renewal-number":
            require(
                state["slots"].get("policy_number") == "SQ-OGPO-731204",
                "policy slot lost",
            )
            require(
                trace.get("policy_outcome") == "continue", "follow-up did not continue"
            )
        print(f"PASS {case.name}: {self.summary}", flush=True)
        return body

    def closed_session(self, session_id: str) -> None:
        response, elapsed = self.request(
            "closed-session", session_id, "Есть ещё один вопрос."
        )
        require(response.status_code == 409, "closed session must return HTTP 409")
        body = self.json_body(response)
        require(
            isinstance(body, dict) and isinstance(body.get("error"), dict),
            "invalid error",
        )
        require(
            body["error"].get("code") == "session_closed",
            "wrong closed-session error code",
        )
        print(f"PASS closed-session: HTTP=409 http_ms={elapsed:.0f}", flush=True)


def nonnegative(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "must be a nonnegative finite number"
        ) from None
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative finite number")
    return parsed


def base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path in {"", "/"}
        )
        _ = (
            parsed.port
        )  # Validate port syntax without including the original URL in errors.
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError(
            "use an HTTP(S) origin without credentials or query"
        )
    return value.rstrip("/") + "/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", type=base_url, default="http://127.0.0.1:8000/")
    parser.add_argument(
        "--pace-seconds",
        type=nonnegative,
        default=15.0,
        help="pause after each request (default: 15)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=nonnegative,
        default=90.0,
        help="per-request timeout (default: 90)",
    )
    args = parser.parse_args()
    if args.timeout_seconds == 0:
        parser.error("--timeout-seconds must be greater than zero")
    print(
        "LIVE API smoke: 9 routed turns + closed-session check; sequential, no retries.",
        flush=True,
    )
    with httpx.Client(
        base_url=args.base_url, timeout=args.timeout_seconds, follow_redirects=False
    ) as client:
        runner = SmokeRunner(client, args.pace_seconds)
        try:
            for case in CASES:
                runner.turn(case, f"smoke-{uuid4().hex}")
            session_id = f"smoke-{uuid4().hex}"
            turns = (
                Case(
                    "renewal-start",
                    "Хочу продлить действующий полис на автомобиль.",
                    ("SC27",),
                    "ru",
                    "awaiting_user",
                    active="SC27",
                ),
                Case(
                    "renewal-number",
                    "Номер полиса SQ-OGPO-731204.",
                    ("SC27",),
                    "ru",
                    "awaiting_user",
                    active="SC27",
                ),
                Case(
                    "goodbye",
                    "На этом всё, до свидания.",
                    ("SYS_GOODBYE",),
                    "ru",
                    "ended",
                    active="SC27",
                ),
            )
            previous = None
            for turn, case in enumerate(turns, start=1):
                previous = runner.turn(case, session_id, turn, previous)
            runner.closed_session(session_id)
        except SmokeFailure as exc:
            print(f"FAIL {runner.label}: {exc}", file=sys.stderr, flush=True)
            if runner.summary:
                print(f"  {runner.summary}", file=sys.stderr, flush=True)
            return 1
        except KeyboardInterrupt:
            print(
                "Interrupted; current request outcome may be unconfirmed.",
                file=sys.stderr,
            )
            return 130
    print(f"PASS all checks ({runner.requests} HTTP requests).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
