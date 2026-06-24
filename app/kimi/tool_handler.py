"""
Kimi 工具调用支持模块

参考 ds2api 实现，将 OpenAI 格式的工具定义转换为 Kimi 可理解的提示词注入
"""

import json
from typing import Any, Dict, List, Optional


def build_tool_instructions(tools: List[Dict[str, Any]]) -> str:
    """
    构建工具调用指令，注入到系统提示词中

    Args:
        tools: OpenAI 格式的工具定义列表

    Returns:
        格式化的工具指令文本
    """
    if not tools:
        return ""

    tool_descriptions = []

    for tool in tools:
        if tool.get("type") == "function":
            function = tool.get("function", {})
            name = function.get("name", "")
            description = function.get("description", "")
            parameters = function.get("parameters", {})

            # 构建参数描述
            param_desc = json.dumps(parameters, ensure_ascii=False, indent=2)

            tool_desc = f"""### {name}
描述: {description}
参数格式:
{param_desc}"""
            tool_descriptions.append(tool_desc)

    if not tool_descriptions:
        return ""

    # 构建完整的工具调用指令
    instruction = f"""# 工具调用说明

你可以使用以下工具来帮助回答用户的问题。当需要使用工具时，请按照指定格式输出。

## 可用工具

{chr(10).join(tool_descriptions)}

## 工具调用格式

当你需要调用工具时，请使用以下格式：

[function_calls]
[call:工具名称]
{{"参数名1": "值1", "参数名2": "值2"}}
[/call]
[/function_calls]

注意：
1. 可以在 [function_calls] 标签内调用多个工具
2. 参数必须是有效的 JSON 格式
3. 调用工具后，等待用户提供工具执行结果，然后基于结果继续回答
"""

    return instruction


def inject_tool_instructions(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    将工具指令注入到消息列表中

    Args:
        messages: 原始消息列表
        tools: 工具定义列表

    Returns:
        注入工具指令后的消息列表
    """
    if not tools:
        return messages

    tool_instruction = build_tool_instructions(tools)
    if not tool_instruction:
        return messages

    # 查找是否已有 system 消息
    result = []
    system_found = False

    for msg in messages:
        if msg.get("role") == "system" and not system_found:
            # 将工具指令追加到第一个 system 消息中
            content = msg.get("content", "")
            new_content = f"{content}\n\n{tool_instruction}".strip()
            result.append({**msg, "content": new_content})
            system_found = True
        else:
            result.append(msg)

    # 如果没有 system 消息，在开头插入
    if not system_found:
        result.insert(0, {
            "role": "system",
            "content": tool_instruction
        })

    return result


def extract_tool_names(tools: Optional[List[Dict[str, Any]]]) -> List[str]:
    """
    提取工具名称列表

    Args:
        tools: 工具定义列表

    Returns:
        工具名称列表
    """
    if not tools:
        return []

    names = []
    for tool in tools:
        if tool.get("type") == "function":
            function = tool.get("function", {})
            name = function.get("name")
            if name:
                names.append(name)

    return names
