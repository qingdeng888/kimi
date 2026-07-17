import json

from app.api.toolcall import (
    ToolCallSieve,
    build_tool_prompt_block,
    has_tools,
    inject_tool_call_context,
    parse_tool_calls_from_text,
    serialize_assistant_tool_calls,
    serialize_tool_result,
)
from app.kimi.chunks import content_chunk, role_chunk, stop_chunk
from app.kimi.protocol import (
    ChatCompletion,
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionUsage,
)

WEATHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": ["city"],
            },
        },
    }
]

NEUTRAL_RESPONSE = (
    "Sure, let me check.\n"
    '<tool_call>{"name":"get_weather","arguments":{"city":"Shenzhen","days":"3"}}</tool_call>'
)


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def test_has_tools_detects_function_tools():
    assert has_tools({"tools": WEATHER_TOOLS}) is True


def test_has_tools_respects_tool_choice_none():
    assert has_tools({"tools": WEATHER_TOOLS, "tool_choice": "none"}) is False


def test_has_tools_ignores_builtin_web_search_tool():
    assert has_tools({"tools": [{"type": "web_search"}]}) is False


def test_has_tools_handles_missing_tools():
    assert has_tools({}) is False
    assert has_tools({"tools": []}) is False


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def test_build_tool_prompt_block_lists_only_function_tools():
    block = build_tool_prompt_block(WEATHER_TOOLS + [{"type": "web_search"}])
    assert "get_weather" in block
    assert "<tool_call>" in block
    assert "<tool_call>" in block
    assert "web_search" not in block
    assert '"city"' in block  # schema is embedded


# ---------------------------------------------------------------------------
# Non-streaming parsing
# ---------------------------------------------------------------------------

def test_parse_tool_calls_returns_text_when_no_block():
    content, calls = parse_tool_calls_from_text("just a normal reply")
    assert content == "just a normal reply"
    assert calls == []


def test_parse_neutral_tool_call_applies_whitelist_and_schema():
    content, calls = parse_tool_calls_from_text(NEUTRAL_RESPONSE, WEATHER_TOOLS)
    assert content == "Sure, let me check."
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "city": "Shenzhen",
        "days": 3,
    }


def test_parse_neutral_tool_call_rejects_undeclared_tool():
    text = '<tool_call>{"name":"delete_everything","arguments":{}}</tool_call>'
    content, calls = parse_tool_calls_from_text(text, WEATHER_TOOLS)
    assert content == ""
    assert calls == []


def test_parse_tool_calls_handles_multiple_blocks_and_types():
    text = (
        '<tool_call>{"name":"a","arguments":{"flag":true}}</tool_call>\n'
        '<tool_call>{"name":"b","arguments":{"obj":{"k":[1,2]}}}</tool_call>'
    )
    content, calls = parse_tool_calls_from_text(text)
    assert content == ""
    assert len(calls) == 2
    assert json.loads(calls[0]["function"]["arguments"])["flag"] is True
    assert json.loads(calls[1]["function"]["arguments"])["obj"] == {"k": [1, 2]}


# ---------------------------------------------------------------------------
# Serialization / message rewriting
# ---------------------------------------------------------------------------

def test_serialize_assistant_tool_calls_round_trips():
    serialized = serialize_assistant_tool_calls(
        [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'},
            }
        ]
    )
    assert serialized.startswith("<tool_call>")
    _, calls = parse_tool_calls_from_text(serialized, WEATHER_TOOLS)
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Tokyo"}


def test_serialize_tool_result_uses_neutral_json_block():
    rendered = serialize_tool_result({"tool_call_id": "call_1", "content": "sunny"})
    assert rendered.startswith("<tool_result>")
    assert '"tool_call_id":"call_1"' in rendered
    assert '"content":"sunny"' in rendered


def test_inject_tool_call_context_rewrites_messages():
    messages = [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "rainy"},
    ]
    injected = inject_tool_call_context(messages, WEATHER_TOOLS)

    assert injected[0]["role"] == "system"
    assert "get_weather" in injected[0]["content"]
    assert injected[1] == {"role": "user", "content": "weather?"}
    assert "<tool_call>" in injected[2]["content"]
    assert "tool_calls" not in injected[2]
    assert injected[3]["role"] == "user"
    assert "tool_result" in injected[3]["content"]


# ---------------------------------------------------------------------------
# Streaming sieve
# ---------------------------------------------------------------------------

def _drive_sieve(sieve, chunks):
    text = ""
    deltas = []
    for chunk in chunks:
        text_delta, tool_delta = sieve.push(chunk)
        text += text_delta
        if tool_delta:
            deltas.extend(tool_delta)
    flush_text, flush_delta = sieve.flush()
    text += flush_text
    if flush_delta:
        deltas.extend(flush_delta)
    return text, deltas


def test_sieve_passes_through_plain_text():
    text, deltas = _drive_sieve(ToolCallSieve(), ["Hello ", "world", "!"])
    assert text == "Hello world!"
    assert deltas == []


def test_sieve_parses_neutral_protocol_across_chunks():
    chunks = [NEUTRAL_RESPONSE[i:i + 3] for i in range(0, len(NEUTRAL_RESPONSE), 3)]
    text, deltas = _drive_sieve(ToolCallSieve(WEATHER_TOOLS), chunks)
    assert text == "Sure, let me check.\n"
    assert len(deltas) == 1
    assert json.loads(deltas[0]["function"]["arguments"])["days"] == 3


def test_sieve_does_not_intercept_tool_example_inside_code_fence():
    example = '```xml\n<tool_call>{"name":"get_weather","arguments":{}}</tool_call>\n```'
    text, deltas = _drive_sieve(ToolCallSieve(WEATHER_TOOLS), [example[:8], example[8:]])
    assert text == example
    assert deltas == []


def test_sieve_holds_back_partial_open_marker():
    sieve = ToolCallSieve()
    first, _ = sieve.push("abc<tool_")
    assert first == "abc"
    rest, deltas = sieve.push(
        'call>{"name":"f","arguments":{}}</tool_call>'
    )
    assert rest == ""
    flush_text, deltas = sieve.flush()
    assert flush_text == ""
    assert deltas and deltas[0]["function"]["name"] == "f"


# ---------------------------------------------------------------------------
# End-to-end route integration
# ---------------------------------------------------------------------------

def _make_completion(content):
    return ChatCompletion(
        id="conv-1",
        created=123,
        model="kimi-k2.6",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(0, 0, 0),
    )


def _install_fake_client(monkeypatch, content):
    captured = {}
    pieces = [content[i : i + 6] for i in range(0, len(content), 6)]

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            if kwargs.get("stream"):

                async def generator():
                    yield role_chunk(chunk_id="c", created=1, model="kimi-k2.6")
                    for piece in pieces:
                        yield content_chunk(
                            chunk_id="c", created=1, model="kimi-k2.6", content=piece
                        )
                    yield stop_chunk(chunk_id="c", created=1, model="kimi-k2.6")

                return generator()
            return _make_completion(content)

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeKimi:
        def __init__(self, *args, **kwargs):
            self.chat = FakeChat()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def close(self):
            return None

    monkeypatch.setattr("app.api.routes.Kimi2API", FakeKimi)
    monkeypatch.setattr("app.api.streaming.Kimi2API", FakeKimi)
    return captured


def _sse_events(body):
    events = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[len("data: ") :]
        if data.strip() == "[DONE]":
            continue
        events.append(json.loads(data))
    return events


def test_chat_completion_non_streaming_returns_tool_calls(
    api_client, configured_api_key, monkeypatch
):
    captured = _install_fake_client(monkeypatch, NEUTRAL_RESPONSE)

    response = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {configured_api_key.key}"},
        json={
            "model": "kimi-k2.6",
            "messages": [{"role": "user", "content": "weather in Shenzhen?"}],
            "tools": WEATHER_TOOLS,
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Sure, let me check."
    tool_calls = choice["message"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {
        "city": "Shenzhen",
        "days": 3,
    }

    # the tool prompt was injected into the upstream messages
    sent = captured["messages"]
    assert sent[0]["role"] == "system"
    assert "get_weather" in sent[0]["content"]


def test_chat_completion_without_tools_is_unaffected(
    api_client, configured_api_key, monkeypatch
):
    _install_fake_client(monkeypatch, "plain answer")

    response = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {configured_api_key.key}"},
        json={
            "model": "kimi-k2.6",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == "plain answer"
    assert "tool_calls" not in choice["message"]


def test_chat_completion_streaming_emits_tool_calls(
    api_client, configured_api_key, monkeypatch
):
    _install_fake_client(monkeypatch, NEUTRAL_RESPONSE)

    with api_client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {configured_api_key.key}"},
        json={
            "model": "kimi-k2.6",
            "stream": True,
            "messages": [{"role": "user", "content": "weather in Shenzhen?"}],
            "tools": WEATHER_TOOLS,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "data: [DONE]" in body

    events = _sse_events(body)
    text = ""
    tool_calls = []
    finish_reasons = []
    for event in events:
        for choice in event["choices"]:
            delta = choice.get("delta", {})
            if delta.get("content"):
                text += delta["content"]
            if delta.get("tool_calls"):
                tool_calls.extend(delta["tool_calls"])
            if choice.get("finish_reason"):
                finish_reasons.append(choice["finish_reason"])

    assert text == "Sure, let me check.\n"
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "get_weather"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {
        "city": "Shenzhen",
        "days": 3,
    }
    assert finish_reasons == ["tool_calls"]
