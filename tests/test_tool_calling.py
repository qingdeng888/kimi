"""
工具调用功能测试
"""

import pytest

from app.kimi.tool_handler import (
    build_tool_instructions,
    inject_tool_instructions,
    extract_tool_names,
)
from app.kimi.tool_parser import (
    parse_tool_calls,
    detect_partial_tool_call,
)


def test_build_tool_instructions():
    """测试工具指令构建"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称"
                        }
                    },
                    "required": ["city"]
                }
            }
        }
    ]

    instruction = build_tool_instructions(tools)

    assert "get_weather" in instruction
    assert "获取指定城市的天气信息" in instruction
    assert "工具调用格式" in instruction
    assert "[function_calls]" in instruction


def test_inject_tool_instructions():
    """测试工具指令注入"""
    messages = [
        {"role": "user", "content": "帮我查询北京天气"}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取天气",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    result = inject_tool_instructions(messages, tools)

    # 应该在开头插入 system 消息
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert "get_weather" in result[0]["content"]
    assert result[1]["role"] == "user"


def test_inject_tool_instructions_with_existing_system():
    """测试向已有 system 消息注入工具指令"""
    messages = [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "查天气"}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取天气",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    result = inject_tool_instructions(messages, tools)

    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert "你是一个助手" in result[0]["content"]
    assert "get_weather" in result[0]["content"]


def test_extract_tool_names():
    """测试提取工具名称"""
    tools = [
        {
            "type": "function",
            "function": {"name": "tool1", "description": "Test"}
        },
        {
            "type": "function",
            "function": {"name": "tool2", "description": "Test"}
        }
    ]

    names = extract_tool_names(tools)
    assert names == ["tool1", "tool2"]


def test_parse_tool_calls_with_square_brackets():
    """测试解析方括号格式的工具调用"""
    text = """
[function_calls]
[call:get_weather]
{"city": "北京"}
[/call]
[/function_calls]
"""

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].function_name == "get_weather"
    assert '"city"' in result.tool_calls[0].function_arguments
    assert result.cleaned_text.strip() == ""


def test_parse_tool_calls_with_angle_brackets():
    """测试解析尖括号格式的工具调用"""
    text = """
<function_calls>
<call:search>
{"query": "Python教程"}
</call>
</function_calls>
"""

    result = parse_tool_calls(text, ["search"])

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].function_name == "search"


def test_parse_multiple_tool_calls():
    """测试解析多个工具调用"""
    text = """
[function_calls]
[call:get_weather]
{"city": "北京"}
[/call]
[call:get_weather]
{"city": "上海"}
[/call]
[/function_calls]
"""

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].function_name == "get_weather"
    assert result.tool_calls[1].function_name == "get_weather"


def test_parse_tool_calls_with_surrounding_text():
    """测试解析带有周围文本的工具调用"""
    text = """
我需要查询天气信息。

[function_calls]
[call:get_weather]
{"city": "北京"}
[/call]
[/function_calls]

查询完成后我会告诉你结果。
"""

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 1
    # 清理后的文本应该移除了工具调用标记
    assert "[function_calls]" not in result.cleaned_text
    assert "我需要查询天气信息" in result.cleaned_text


def test_parse_tool_calls_validates_tool_names():
    """测试工具名称验证"""
    text = """
[function_calls]
[call:unknown_tool]
{"param": "value"}
[/call]
[/function_calls]
"""

    result = parse_tool_calls(text, ["get_weather"])

    # 未知工具应该被过滤
    assert result.has_tool_calls is False
    assert len(result.tool_calls) == 0


def test_parse_tool_calls_repairs_json():
    """测试 JSON 修复功能"""
    text = """
[function_calls]
[call:get_weather]
{'city': '北京',}
[/call]
[/function_calls]
"""

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 1
    # 修复后的 JSON 应该是有效的
    assert '"city"' in result.tool_calls[0].function_arguments


def test_detect_partial_tool_call():
    """测试部分工具调用检测"""
    # 完整的工具调用
    is_partial, content = detect_partial_tool_call("[function_calls]")
    assert is_partial is True

    # 不包含工具调用
    is_partial, content = detect_partial_tool_call("这是普通文本")
    assert is_partial is False

    # 部分工具调用
    is_partial, content = detect_partial_tool_call("[function_calls]\n[call:get_weather]")
    assert is_partial is True


def test_parse_tool_calls_to_dict():
    """测试工具调用转换为字典格式"""
    text = """
[function_calls]
[call:get_weather]
{"city": "北京"}
[/call]
[/function_calls]
"""

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is True
    tool_call_dict = result.tool_calls[0].to_dict()

    assert tool_call_dict["type"] == "function"
    assert tool_call_dict["function"]["name"] == "get_weather"
    assert tool_call_dict["function"]["arguments"] == '{"city": "北京"}'
    assert "id" in tool_call_dict
    assert tool_call_dict["id"].startswith("call_")


def test_parse_no_tool_calls():
    """测试无工具调用的文本"""
    text = "这是一段普通的回答，没有任何工具调用。"

    result = parse_tool_calls(text, ["get_weather"])

    assert result.has_tool_calls is False
    assert len(result.tool_calls) == 0
    assert result.cleaned_text == text
