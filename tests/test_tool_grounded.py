"""Unit tests for the tool-call loop (agents.run_with_tool_loop) and the tool orchestrators.

The loop is driven by a SCRIPTED fake client — no network — so the control flow (offer tool →
execute deterministically → feed result back → re-invoke; stop on a no-tool reply; force a final
answer when the budget is exhausted) is asserted exactly. The sandbox itself (run_python) runs for
real, so these also confirm the loop wires monty in end to end.
"""

from __future__ import annotations

import json

import httpx
import openai
import pytest

from openai_420 import orchestrators
from openai_420.agents import _execute_tool_call, run_with_tool_loop
from openai_420.conversation import Conversation

pytest.importorskip("pydantic_monty")


# ------------------------------------------------------------------ scripted fake client
class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _Fn(name, arguments)


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        dumped = {"role": "assistant", "content": self.content}
        if self.tool_calls is not None:
            dumped["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        return {k: v for k, v in dumped.items() if not (exclude_none and v is None)}


class _Choice:
    def __init__(self, message):
        self.message = message
        self.finish_reason = "stop"


class _Response:
    def __init__(self, message):
        self.choices = [_Choice(message)]
        self.usage = None


class _Completions:
    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Response(item)


class FakeClient:
    def __init__(self, script):
        self.chat = type("_Chat", (), {"completions": _Completions(script)})()


def _tool(call_id, code):
    return _ToolCall(call_id, "run_python", json.dumps({"code": code}))


def _bad_request(message):
    response = httpx.Response(400, request=httpx.Request("POST", "http://x"))
    return openai.BadRequestError(message, response=response, body=None)


def _tool_use_failed_error():
    """A 400 like Groq's gpt-oss emits when its tool-call arguments aren't valid JSON."""
    return _bad_request(
        "Error code: 400 - tool_use_failed: Failed to parse tool call arguments"
    )


# ------------------------------------------------------------------ loop control flow
@pytest.mark.asyncio
async def test_loop_executes_tool_and_feeds_result_back():
    client = FakeClient(
        [
            _Message(tool_calls=[_tool("c1", "print(6 * 7)")]),
            _Message(content="checked it.\n[[ANSWER]] 42"),
        ]
    )
    conversation = Conversation(system="s", user_query="q")
    content, trace = await run_with_tool_loop(
        client, "m", conversation, tool_budget=3, who="x", stage="respond"
    )
    assert "42" in content
    assert trace == [{"code": "print(6 * 7)", "result": "42"}]
    # the tool result was appended to the conversation for the model's next turn
    assert any(
        m.get("role") == "tool" and m["content"] == "42" for m in conversation.messages
    )
    # the tool was actually offered on the first call
    assert client.chat.completions.calls[0]["tools"]
    assert client.chat.completions.calls[0]["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_loop_returns_directly_when_model_calls_no_tool():
    client = FakeClient([_Message(content="no need.\n[[ANSWER]] 5")])
    conversation = Conversation(system="s", user_query="q")
    content, trace = await run_with_tool_loop(
        client, "m", conversation, tool_budget=3, who="x", stage="respond"
    )
    assert "5" in content
    assert trace == []


@pytest.mark.asyncio
async def test_loop_forces_final_answer_when_budget_exhausted():
    client = FakeClient(
        [
            _Message(tool_calls=[_tool("c1", "1 + 1")]),
            _Message(tool_calls=[_tool("c2", "2 + 2")]),
            _Message(tool_calls=[_tool("c3", "3 + 3")]),  # still wants to compute
            _Message(content="forced.\n[[ANSWER]] done"),
        ]
    )
    conversation = Conversation(system="s", user_query="q")
    content, trace = await run_with_tool_loop(
        client, "m", conversation, tool_budget=2, who="x", stage="respond"
    )
    assert "done" in content
    assert [t["result"] for t in trace] == ["2", "4", "6"]
    # the final, forced completion must NOT offer tools (so the model has to answer)
    assert "tools" not in client.chat.completions.calls[-1]


@pytest.mark.asyncio
async def test_loop_degrades_to_plain_answer_when_tool_calls_keep_failing():
    # The backend rejects every tool-offered completion (malformed tool args, gpt-oss quirk);
    # after exhausting retries the loop must still produce an answer, ungrounded, not crash.
    client = FakeClient(
        [_tool_use_failed_error() for _ in range(4)]
        + [_Message(content="answered without the tool.\n[[ANSWER]] 7")]
    )
    conversation = Conversation(system="s", user_query="q")
    content, trace = await run_with_tool_loop(
        client, "m", conversation, tool_budget=3, who="x", stage="respond"
    )
    assert "7" in content
    assert trace == []
    # the degraded completion was a plain one — no tools offered
    assert "tools" not in client.chat.completions.calls[-1]


@pytest.mark.asyncio
async def test_loop_degrades_immediately_on_non_tool_use_failed_400():
    # A different tool-related 400 (not tool_use_failed) must degrade at once, not burn retries.
    client = FakeClient(
        [_bad_request("Error code: 400 - Tool choice validation failed")]
        + [_Message(content="plain.\n[[ANSWER]] 9")]
    )
    conversation = Conversation(system="s", user_query="q")
    content, trace = await run_with_tool_loop(
        client, "m", conversation, tool_budget=3, who="x", stage="respond"
    )
    assert "9" in content
    assert trace == []
    assert len(client.chat.completions.calls) == 2  # one tooled (failed) + one plain


# ------------------------------------------------------------------ tool-call execution guards
@pytest.mark.asyncio
async def test_execute_rejects_unknown_tool():
    out = await _execute_tool_call(_ToolCall("c", "delete_everything", "{}"))
    assert "unknown tool" in out


@pytest.mark.asyncio
async def test_execute_handles_malformed_arguments():
    out = await _execute_tool_call(_ToolCall("c", "run_python", "{not valid json"))
    assert "could not parse" in out


@pytest.mark.asyncio
async def test_execute_runs_real_sandbox():
    out = await _execute_tool_call(_tool("c", "import math\nprint(math.isqrt(169))"))
    assert out == "13"


# ------------------------------------------------------------------ registration + wiring
def test_tool_orchestrators_are_registered():
    assert "tool_grounded_verification" in orchestrators.names()
    assert "tool_single" in orchestrators.names()


def test_from_args_threads_tool_budget_and_rounds():
    built = orchestrators.get("tool_grounded_verification").from_args(
        client=object(),
        model="m",
        gen_params={},
        group="A",
        max_rounds=2,
        tool_budget=5,
    )
    assert built._tool_budget == 5
    assert built._max_rounds == 2


def test_tool_single_from_args_threads_tool_budget():
    built = orchestrators.get("tool_single").from_args(
        client=object(), model="m", gen_params={}, tool_budget=7
    )
    assert built._tool_budget == 7
