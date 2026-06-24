"""
工具调用解析器

从 Kimi 响应文本中检测和解析工具调用
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple


class ParsedToolCall:
    """解析后的工具调用"""

    def __init__(
        self,
        id: str,
        type: str,
        function_name: str,
        function_arguments: str,
    ):
        self.id = id
        self.type = type
        self.function_name = function_name
        self.function_arguments = function_arguments

    def to_dict(self) -> Dict[str, Any]:
        """转换为 OpenAI 格式的字典"""
        return {
            "id": self.id,
            "type": self.type,
            "function": {
                "name": self.function_name,
                "arguments": self.function_arguments,
            }
        }


class ToolCallParseResult:
    """工具调用解析结果"""

    def __init__(
        self,
        tool_calls: List[ParsedToolCall],
        cleaned_text: str,
        has_tool_calls: bool,
    ):
        self.tool_calls = tool_calls
        self.cleaned_text = cleaned_text
        self.has_tool_calls = has_tool_calls


def parse_tool_calls(
    text: str,
    available_tools: Optional[List[str]] = None
) -> ToolCallParseResult:
    """
    从文本中解析工具调用

    支持的格式：
    1. [function_calls]...[/function_calls]
    2. <function_calls>...</function_calls>

    Args:
        text: 待解析的文本
        available_tools: 可用工具名称列表（用于验证）

    Returns:
        ToolCallParseResult 解析结果
    """
    if not text:
        return ToolCallParseResult(
            tool_calls=[],
            cleaned_text="",
            has_tool_calls=False,
        )

    # 尝试多种标记格式
    patterns = [
        (r'\[function_calls\](.*?)\[/function_calls\]', r'\[call:(.*?)\](.*?)\[/call\]'),
        (r'<function_calls>(.*?)</function_calls>', r'<call:(.*?)>(.*?)</call>'),
    ]

    tool_calls: List[ParsedToolCall] = []
    cleaned_text = text

    for wrapper_pattern, call_pattern in patterns:
        # 查找所有 function_calls 块
        wrapper_matches = re.finditer(wrapper_pattern, text, re.DOTALL)

        for wrapper_match in wrapper_matches:
            function_calls_content = wrapper_match.group(1)

            # 在块内查找所有单独的调用
            call_matches = re.finditer(call_pattern, function_calls_content, re.DOTALL)

            for call_match in call_matches:
                function_name = call_match.group(1).strip()
                arguments_text = call_match.group(2).strip()

                # 验证工具名称
                if available_tools and function_name not in available_tools:
                    continue

                # 验证并格式化参数
                try:
                    # 尝试解析 JSON 以验证格式
                    parsed_args = json.loads(arguments_text)
                    # 重新序列化确保格式统一
                    formatted_args = json.dumps(parsed_args, ensure_ascii=False)
                except json.JSONDecodeError:
                    # 如果解析失败，尝试修复常见问题
                    formatted_args = _repair_json(arguments_text)
                    if not formatted_args:
                        continue

                # 创建工具调用对象
                tool_call = ParsedToolCall(
                    id=f"call_{uuid.uuid4().hex[:24]}",
                    type="function",
                    function_name=function_name,
                    function_arguments=formatted_args,
                )
                tool_calls.append(tool_call)

            # 从清理后的文本中移除整个 function_calls 块
            cleaned_text = cleaned_text.replace(wrapper_match.group(0), "").strip()

    # 如果找到工具调用，进一步清理文本
    if tool_calls:
        # 移除可能残留的标记
        cleaned_text = re.sub(r'\[/?function_calls\]|\[/?call:.*?\]', '', cleaned_text)
        cleaned_text = re.sub(r'</?function_calls>|</?call:.*?>', '', cleaned_text)
        cleaned_text = re.sub(r'\n\s*\n+', '\n\n', cleaned_text).strip()

    return ToolCallParseResult(
        tool_calls=tool_calls,
        cleaned_text=cleaned_text,
        has_tool_calls=len(tool_calls) > 0,
    )


def _repair_json(text: str) -> str:
    """
    尝试修复常见的 JSON 格式问题

    Args:
        text: 可能损坏的 JSON 文本

    Returns:
        修复后的 JSON 字符串，失败返回空字符串
    """
    if not text:
        return ""

    # 移除可能的前后空白和换行
    text = text.strip()

    # 尝试常见修复
    repairs = [
        # 原始文本
        lambda t: t,
        # 移除尾部逗号
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t),
        # 单引号转双引号
        lambda t: t.replace("'", '"'),
        # 组合修复
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t.replace("'", '"')),
    ]

    for repair_fn in repairs:
        try:
            repaired = repair_fn(text)
            parsed = json.loads(repaired)
            return json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, Exception):
            continue

    return ""


def detect_partial_tool_call(text: str) -> Tuple[bool, str]:
    """
    检测文本中是否包含部分工具调用（用于流式处理）

    Args:
        text: 待检测的文本

    Returns:
        (是否检测到, 提取的部分内容)
    """
    # 检测工具调用开始标记
    start_patterns = [
        r'\[function_calls\]',
        r'<function_calls>',
        r'\[call:',
        r'<call:',
    ]

    for pattern in start_patterns:
        if re.search(pattern, text):
            # 提取已有内容
            match = re.search(r'(\[function_calls\].*|\<function_calls\>.*)', text, re.DOTALL)
            if match:
                return True, match.group(1)

    return False, ""
