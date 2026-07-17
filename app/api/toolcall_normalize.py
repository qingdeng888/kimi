"""
工具调用规范化模块

提供模型无关的工具名称匹配、Schema 类型转换和去重能力。
主调用链只在请求声明的工具集合内匹配，不包含 Qwen/Agent 专用固定别名。
"""

import re
import json
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# 工具名称规范化
# ============================================================================

def canonicalize_tool_name(name: str, available_tools: List[str]) -> Optional[str]:
    """
    规范化工具名称，支持：
    1. 精确匹配（忽略大小写）
    2. 安全标识符匹配（移除大小写与分隔符差异）
    """
    if not name or not isinstance(name, str):
        return None

    name = name.strip()
    if not name:
        return None

    # 创建工具名称的小写映射
    available_lower = {tool.lower(): tool for tool in available_tools}

    # 1. 精确匹配（忽略大小写）
    if name.lower() in available_lower:
        return available_lower[name.lower()]

    # 2. 仅在请求声明集合内做安全标识符匹配
    normalized_name = _normalize_identifier(name)
    for tool in available_tools:
        if _normalize_identifier(tool) == normalized_name:
            return tool

    return None


def _normalize_identifier(text: str) -> str:
    """移除特殊字符，只保留字母和数字"""
    return re.sub(r'[^a-z0-9]+', '', text.lower())


# ============================================================================
# 参数名称修复
# ============================================================================

def coerce_tool_parameters(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """保留调用方参数名；Kimi 通道不使用模型专用参数别名。"""
    return params.copy() if isinstance(params, dict) else params


# ============================================================================
# Schema 驱动的类型转换
# ============================================================================

def coerce_by_schema(
    tool_name: str,
    params: Dict[str, Any],
    tools: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    根据工具 Schema 转换参数类型

    参考 qwen2API 的 coerceToolInputBySchema 实现
    """
    if not isinstance(params, dict):
        return params

    # 获取工具 Schema
    schema = _get_tool_schema(tool_name, tools)
    if not schema:
        return params

    properties = schema.get("properties", {})
    if not properties:
        return params

    fixed = params.copy()

    # 对每个参数，根据 Schema 进行类型转换
    for param_name, param_value in fixed.items():
        if param_name not in properties:
            continue

        param_schema = properties[param_name]
        if not isinstance(param_schema, dict):
            continue

        fixed[param_name] = _coerce_value_by_schema(param_value, param_schema)

    return fixed


def _coerce_value_by_schema(value: Any, schema: Dict[str, Any]) -> Any:
    """根据 Schema 转换单个值的类型"""
    param_type = schema.get("type")

    # 如果 Schema 要求 array，但值是对象，包装成数组
    if param_type == "array":
        if isinstance(value, dict):
            return [value]
        elif isinstance(value, str):
            # 尝试解析为 JSON 数组
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    value = parsed
                elif isinstance(parsed, dict):
                    value = [parsed]
            except (json.JSONDecodeError, ValueError):
                pass
        if isinstance(value, list) and isinstance(schema.get("items"), dict):
            return [_coerce_value_by_schema(item, schema["items"]) for item in value]

    # 如果 Schema 要求 object，但值是字符串，尝试解析
    elif param_type == "object":
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    value = parsed
            except (json.JSONDecodeError, ValueError):
                pass
        if isinstance(value, dict):
            properties = schema.get("properties") or {}
            return {
                key: _coerce_value_by_schema(item, properties[key])
                if isinstance(properties.get(key), dict) else item
                for key, item in value.items()
            }

    # 如果 Schema 要求 string，但值是其他类型
    elif param_type == "string":
        if not isinstance(value, str):
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            else:
                return str(value)

    elif param_type == "integer":
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass

    elif param_type == "number":
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass

    elif param_type == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False

    return value


def _get_tool_schema(tool_name: str, tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """获取指定工具的 Schema"""
    for tool in tools:
        # 支持两种格式：
        # 1. {"name": "Tool", "parameters": {...}}
        # 2. {"function": {"name": "Tool", "parameters": {...}}}

        name = tool.get("name")
        schema = tool.get("parameters") or tool.get("input_schema")

        if "function" in tool and isinstance(tool["function"], dict):
            fn = tool["function"]
            if not name:
                name = fn.get("name")
            if not schema:
                schema = fn.get("parameters") or fn.get("input_schema")

        if name == tool_name and isinstance(schema, dict):
            return schema

    return None


# ============================================================================
# 综合规范化函数
# ============================================================================

def normalize_tool_call(
    tool_name: str,
    parameters: Dict[str, Any],
    available_tools: List[str],
    tools_schema: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    综合规范化工具调用

    返回：{"name": str, "parameters": dict} 或 None（如果无效）
    """
    # 1. 规范化工具名称
    canonical_name = canonicalize_tool_name(tool_name, available_tools)
    if not canonical_name:
        return None

    # 2. 修复参数名称
    fixed_params = coerce_tool_parameters(canonical_name, parameters)

    # 3. Schema 驱动的类型转换
    typed_params = coerce_by_schema(canonical_name, fixed_params, tools_schema)

    return {
        "name": canonical_name,
        "parameters": typed_params
    }


# ============================================================================
# 辅助函数
# ============================================================================

def deduplicate_tool_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    去重工具调用（基于工具名 + 参数哈希）

    参考 qwen2API 的 DedupeToolCalls 实现
    """
    seen: Set[str] = set()
    unique_calls = []

    for call in calls:
        if not isinstance(call, dict):
            continue

        name = call.get("function", {}).get("name", "")
        arguments = call.get("function", {}).get("arguments", "{}")

        if not name:
            continue

        # 创建唯一键：工具名 + 参数 JSON
        key = name.lower() + "\x00" + arguments

        if key not in seen:
            seen.add(key)
            unique_calls.append(call)

    return unique_calls
