import json

from app.kimi.protocol import Message, _format_messages


def test_format_messages_serializes_assistant_tool_calls_with_neutral_protocol():
    output = _format_messages([
        Message(
            role="assistant",
            content="",
            tool_calls=[{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": json.dumps({"city": "北京"}, ensure_ascii=False),
                },
            }],
        )
    ])

    assert output.startswith("assistant:<tool_call>")
    assert '"name":"get_weather"' in output
    assert '"city":"北京"' in output


def test_format_messages_serializes_tool_result_with_neutral_protocol():
    output = _format_messages([
        Message(
            role="tool",
            content={"temperature": 26},
            name="get_weather",
            tool_call_id="call_1",
        )
    ])

    assert output.startswith("user:<tool_result>")
    assert '"tool_call_id":"call_1"' in output
    assert '"name":"get_weather"' in output
    assert "temperature" in output
