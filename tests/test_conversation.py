import json

from openai_420.conversation import Conversation
from openai_420.scratchpad import Entry


def test_conversation_starts_with_system_then_user_query():
    convo = Conversation(system="SYS", user_query="tabs or spaces?")

    assert convo.messages == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "tabs or spaces?"},
    ]


def test_add_own_turn_appends_an_assistant_message():
    convo = Conversation(system="SYS", user_query="Q")

    convo.add_own_turn("my answer")

    assert convo.messages[-1] == {"role": "assistant", "content": "my answer"}


def test_add_delta_appends_a_user_turn_with_entries_as_json():
    convo = Conversation(system="SYS", user_query="Q")

    convo.add_delta([Entry(round=1, author="Benjamin", kind="answer", content="B1")])

    last = convo.messages[-1]
    assert last["role"] == "user"
    assert json.loads(last["content"]) == [
        {"round": 1, "author": "Benjamin", "kind": "answer", "content": "B1"}
    ]


def test_add_user_message_appends_a_user_turn():
    convo = Conversation(system="SYS", user_query="Q")

    convo.add_user_message("Write the final answer now.")

    assert convo.messages[-1] == {
        "role": "user",
        "content": "Write the final answer now.",
    }


def test_add_assistant_message_appends_it_verbatim():
    convo = Conversation(system="SYS", user_query="Q")
    message = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "conclude", "arguments": '{"consensus": true}'},
            }
        ],
    }

    convo.add_assistant_message(message)

    assert convo.messages[-1] == message


def test_add_tool_result_appends_a_tool_message():
    convo = Conversation(system="SYS", user_query="Q")

    convo.add_tool_result(tool_call_id="c1", content="ok")

    assert convo.messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}
