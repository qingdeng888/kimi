"""OpenAI-style function calling support for the Kimi Web transport.

The Kimi web backend has no native function-calling API, so tool support is
implemented purely at the prompt level:

* **Request side** - inject a compact, model-neutral JSON envelope prompt and
  serialise prior tool calls/results into the same neutral context format.
* **Response side** - parse ``<tool_call>{JSON}</tool_call>`` blocks back into
  OpenAI ``tool_calls`` with a strict non-streaming JSON fallback.
  For streaming responses a stateful :class:`ToolCallSieve` separates ordinary
  text deltas from tool-call blocks without leaking protocol markup.

Optimized implementation with:
- Chinese-optimized prompt engineering for higher compliance
- Robust parsing with multiple fallback strategies
- Improved streaming sieve with better partial block handling
- Support for tool_choice modes (auto, required, none)
- Comprehensive logging for debugging tool call failures
- Debug mode for detailed tool call tracing
"""

import json
import logging
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from .toolcall_normalize import coerce_by_schema, deduplicate_tool_calls

logger = logging.getLogger("kimi2api.toolcall")


def _debug_log(message: str, *args, **kwargs):
    """详细的调试日志，仅在 DEBUG_TOOL_CALLS=true 时输出"""
    if Config.DEBUG_TOOL_CALLS:
        logger.info(f"[TOOL_CALL_DEBUG] {message}", *args, **kwargs)


def _log_tool_call_detection(text: str, strategy: str, tool_names: List[str]):
    """记录工具调用检测结果"""
    if Config.DEBUG_TOOL_CALLS:
        logger.info(
            f"[TOOL_CALL_DEBUG] Strategy '{strategy}' detected {len(tool_names)} tool(s): {tool_names}\n"
            f"Text length: {len(text)} chars\n"
            f"Text preview: {text[:200]}..."
        )

TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"

# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def _is_function_tool(tool: Any) -> bool:
    """Return True for OpenAI function tools (excludes built-ins like web_search)."""
    if not isinstance(tool, dict):
        return False
    tool_type = tool.get("type")
    if isinstance(tool_type, str) and tool_type.strip().lower() not in ("function", ""):
        return False
    return bool(tool.get("function") or tool.get("name"))


def _function_tools(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if _is_function_tool(tool)]


def has_tools(payload: Dict[str, Any]) -> bool:
    """Whether the request should use prompt-level function calling.

    Requires at least one OpenAI function tool and ``tool_choice`` other than
    ``"none"``.
    """
    if not _function_tools(payload.get("tools")):
        return False

    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, str) and tool_choice.strip().lower() == "none":
        return False
    return True


def _get_tool_choice_mode(payload: Dict[str, Any]) -> str:
    """Extract the tool_choice mode: 'auto', 'required', or a specific function name."""
    tool_choice = payload.get("tool_choice")
    if tool_choice is None:
        return "auto"
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower()
    if isinstance(tool_choice, dict):
        # {"type": "function", "function": {"name": "specific_fn"}}
        fn = tool_choice.get("function", {})
        if isinstance(fn, dict) and fn.get("name"):
            return f"function:{fn['name']}"
    return "auto"


# ---------------------------------------------------------------------------
# Request side - prompt construction & message rewriting
# ---------------------------------------------------------------------------

def build_tool_prompt_block(tools: Optional[List[Any]], tool_choice: str = "auto") -> str:
    """构造面向 Kimi 的简洁、中性工具调用提示词。"""
    tool_list = _function_tools(tools)
    _debug_log(f"Building tool prompt for {len(tool_list)} tools with tool_choice={tool_choice}")

    declarations: List[Dict[str, Any]] = []
    for tool in tool_list:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        params = fn.get("parameters") or fn.get("input_schema") or {}
        declarations.append({
            "name": name,
            "description": str(fn.get("description") or ""),
            "parameters": params if isinstance(params, dict) else {},
        })

    choice_instruction = "按需调用工具；无需调用时直接回答。"
    if tool_choice == "required":
        choice_instruction = "本次回复必须至少调用一个工具。"
    elif tool_choice.startswith("function:"):
        fn_name = tool_choice[len("function:"):]
        choice_instruction = f"本次回复必须调用工具 `{fn_name}`。"

    tools_json = json.dumps(declarations, ensure_ascii=False, separators=(",", ":"))
    return "\n".join([
        "# 工具调用",
        choice_instruction,
        "需要调用工具时，在回复末尾输出一个或多个以下格式的块：",
        '<tool_call>{"name":"工具名称","arguments":{"参数名":"参数值"}}</tool_call>',
        "规则：",
        "1. 标签内部必须是有效 JSON，arguments 必须是对象。",
        "2. 只能调用下方声明的工具，参数必须遵循对应 JSON Schema。",
        "3. 工具调用块后不要再输出任何内容；多个调用使用多个连续的 <tool_call> 块。",
        "可用工具：",
        tools_json,
    ])


def serialize_assistant_tool_calls(tool_calls: Any) -> str:
    """将 OpenAI assistant ``tool_calls`` 序列化为中性 JSON 协议。"""
    if not isinstance(tool_calls, list) or not tool_calls:
        return ""

    blocks: List[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        name = str((fn or {}).get("name") or "").strip()
        if not name:
            continue
        args = (fn or {}).get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                pass
        if not isinstance(args, dict):
            args = {}
        payload = json.dumps(
            {"name": name, "arguments": args},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        blocks.append(f"{TOOL_CALL_OPEN}{payload}{TOOL_CALL_CLOSE}")

    if not blocks:
        return ""
    return "\n".join(blocks)


def serialize_tool_result(message: Dict[str, Any]) -> str:
    """将 OpenAI ``tool`` 消息序列化为中性 JSON 结果块。"""
    tool_id = message.get("tool_call_id") or ""
    name = message.get("name") or ""
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            content = str(content)

    payload = json.dumps(
        {"tool_call_id": tool_id, "name": name, "content": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<tool_result>{payload}</tool_result>"


def _build_tool_result_context(results: List[str]) -> str:
    """Wrap tool results with context explanation for the model."""
    header = "以下是工具调用的结果，请根据这些结果继续回复用户："
    return header + "\n" + "\n".join(results)


def inject_tool_call_context(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Any]],
    tool_choice: str = "auto",
) -> List[Dict[str, Any]]:
    """Rewrite OpenAI messages so the Kimi backend can understand tool usage.

    Enhanced to:
    - Support tool_choice modes
    - Better handle consecutive tool messages
    - Preserve context for multi-turn tool conversations
    """
    rewritten: List[Dict[str, Any]] = []
    pending_tool_results: List[str] = []

    for message in messages or []:
        if not isinstance(message, dict):
            rewritten.append(message)
            continue

        role = message.get("role")

        if (
            role == "assistant"
            and isinstance(message.get("tool_calls"), list)
            and message["tool_calls"]
        ):
            # Flush any pending tool results before the assistant message
            if pending_tool_results:
                rewritten.append({"role": "user", "content": "\n".join(pending_tool_results)})
                pending_tool_results = []

            serialized_calls = serialize_assistant_tool_calls(message["tool_calls"])
            base_text = message.get("content")
            base_text = base_text if isinstance(base_text, str) else ""
            merged = f"{base_text}\n{serialized_calls}" if base_text else serialized_calls
            out = {key: value for key, value in message.items() if key != "tool_calls"}
            out["content"] = merged
            rewritten.append(out)
            continue

        if role == "tool":
            # Collect consecutive tool results to batch them together
            pending_tool_results.append(serialize_tool_result(message))
            continue

        # Flush pending tool results before any non-tool message
        if pending_tool_results:
            rewritten.append({"role": "user", "content": _build_tool_result_context(pending_tool_results)})
            pending_tool_results = []

        rewritten.append(message)

    # Flush remaining tool results
    if pending_tool_results:
        rewritten.append({"role": "user", "content": _build_tool_result_context(pending_tool_results)})

    prompt_block = build_tool_prompt_block(tools, tool_choice)
    return [{"role": "system", "content": prompt_block}, *rewritten]


# ---------------------------------------------------------------------------
# Response side - non-streaming parsing
# ---------------------------------------------------------------------------

def _normalize_parsed_calls(
    calls: List[Dict[str, Any]],
    tools: Optional[List[Any]],
) -> List[Dict[str, Any]]:
    """按请求声明的工具动态校正名称和参数类型。"""
    if not calls:
        return []
    tool_list = _function_tools(tools)
    if tools is None:
        return deduplicate_tool_calls(calls)

    registry: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    normalized_registry: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for tool in tool_list:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        schema = fn.get("parameters") or fn.get("input_schema") or {}
        entry = (name, schema if isinstance(schema, dict) else {})
        registry[name.lower()] = entry
        normalized_registry[_normalize_tool_identifier(name)] = entry

    normalized_calls: List[Dict[str, Any]] = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            continue
        raw_name = str(function.get("name") or "").strip()
        entry = registry.get(raw_name.lower())
        if entry is None:
            entry = normalized_registry.get(_normalize_tool_identifier(raw_name))
        if entry is None:
            logger.warning("Ignoring undeclared tool call: %s", raw_name)
            continue

        canonical_name, _ = entry
        raw_arguments = function.get("arguments", "{}")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except (TypeError, ValueError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        arguments = coerce_by_schema(canonical_name, arguments, tool_list)
        normalized_calls.append({
            "id": call.get("id") or "call_" + secrets.token_hex(8),
            "type": "function",
            "function": {
                "name": canonical_name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        })
    return deduplicate_tool_calls(normalized_calls)


def _normalize_tool_identifier(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _try_parse_neutral_tool_calls(text: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """解析响应末尾一个或多个 ``<tool_call>{JSON}</tool_call>`` 块。"""
    pattern = re.compile(
        re.escape(TOOL_CALL_OPEN) + r"\s*(.*?)\s*" + re.escape(TOOL_CALL_CLOSE),
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if not matches or text[matches[-1].end():].strip():
        return None

    first = matches[0]
    cursor = first.start()
    calls: List[Dict[str, Any]] = []
    for match in matches:
        if text[cursor:match.start()].strip():
            return None
        parsed = _parse_json_as_tool_calls(match.group(1).strip())
        if len(parsed) != 1:
            return None
        calls.extend(parsed)
        cursor = match.end()
    return text[:first.start()].rstrip(), calls


def parse_tool_calls_from_text(
    text: Optional[str],
    tools: Optional[List[Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """解析中性工具调用块，并在非流式场景回退解析末尾 JSON。"""
    if not text or not isinstance(text, str):
        return text or "", []

    _debug_log("=== Starting tool call parsing ===")
    _debug_log(f"Input text length: {len(text)} chars")
    _debug_log(f"Input text preview: {text[:500]}...")

    # Strategy 1: Kimi-neutral JSON envelope
    neutral = _try_parse_neutral_tool_calls(text)
    if neutral is not None:
        content, calls = neutral
        calls = _normalize_parsed_calls(calls, tools)
        if calls:
            _log_tool_call_detection(text, "Neutral tool_call", [c["function"]["name"] for c in calls])
        return content, calls

    # Strategy 2: strict trailing JSON fallback (non-streaming only)
    calls = _try_parse_json_tool_calls(text)
    if calls is not None:
        content_text, tool_calls = calls
        tool_names = [c["function"]["name"] for c in tool_calls]
        _log_tool_call_detection(text, "JSON fallback", tool_names)
        logger.debug("Tool calls parsed via JSON fallback: %s", tool_names)
        tool_calls = _normalize_parsed_calls(tool_calls, tools)
        return content_text, tool_calls

    _debug_log("No tool calls detected in response text")
    logger.debug("No tool calls detected in response text (length=%d)", len(text))
    return text, []


# ---------------------------------------------------------------------------
# Response side - streaming sieve
# ---------------------------------------------------------------------------

class ToolCallSieve:
    """流式过滤器：拦截中性工具协议并在流结束时统一解析。"""

    _OPEN_MARKERS = (TOOL_CALL_OPEN,)

    def __init__(self, tools: Optional[List[Any]] = None) -> None:
        self._tools = tools
        self._buffer = ""
        self._capturing = False
        self._capture = ""
        self._next_index = 0
        self._finished = False
        self._inside_code_fence = False

    def push(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        if self._finished:
            return "", None

        if self._capturing:
            self._capture += chunk
            return "", None

        self._buffer += chunk
        marker_pos = self._find_open_marker()
        if marker_pos is not None:
            idx, _ = marker_pos
            before = self._buffer[:idx]
            self._capture = self._buffer[idx:]
            self._buffer = ""
            self._capturing = True
            self._update_fence_state(before)
            return before, None

        hold_len = self._compute_hold_length()
        if hold_len:
            out = self._buffer[:-hold_len]
            self._buffer = self._buffer[-hold_len:]
            self._update_fence_state(out)
            return out, None

        out = self._buffer
        self._buffer = ""
        self._update_fence_state(out)
        return out, None

    def flush(self) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        if self._finished:
            return "", None

        if self._capturing:
            content, calls = parse_tool_calls_from_text(self._capture, self._tools)
            if calls:
                self._finished = True
                return "", self._as_deltas(calls)
            if content != self._capture:
                self._finished = True
                return "", None
            out = self._capture
            self._capture = ""
            self._capturing = False
            return out, None

        out = self._buffer
        self._buffer = ""
        return out, None

    def _find_open_marker(self) -> Optional[Tuple[int, str]]:
        candidates: List[Tuple[int, str]] = []
        for marker in self._OPEN_MARKERS:
            start = 0
            while True:
                idx = self._buffer.find(marker, start)
                if idx < 0:
                    break
                inside = self._inside_code_fence ^ (self._buffer[:idx].count("```") % 2 == 1)
                if not inside:
                    candidates.append((idx, marker))
                    break
                start = idx + len(marker)
        return min(candidates, default=None, key=lambda item: item[0])

    def _update_fence_state(self, text: str) -> None:
        if text.count("```") % 2 == 1:
            self._inside_code_fence = not self._inside_code_fence

    def _compute_hold_length(self) -> int:
        """保留可能跨 chunk 的任一开始标记前缀。"""
        best = 0
        for marker in self._OPEN_MARKERS:
            for size in range(1, len(marker)):
                if self._buffer.endswith(marker[:size]):
                    best = max(best, size)
        return best

    def _as_deltas(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deltas: List[Dict[str, Any]] = []
        for call in calls:
            deltas.append(
                {
                    "index": self._next_index,
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    },
                }
            )
            self._next_index += 1
        return deltas


# ---------------------------------------------------------------------------
# Internal helpers - JSON repair
# ---------------------------------------------------------------------------

def _repair_json(text: str) -> str:
    """尝试修复常见的 JSON 格式问题

    参考 qingdeng888/kimi 项目实现

    Args:
        text: 可能损坏的 JSON 文本

    Returns:
        修复后的 JSON 字符串，失败返回空字符串
    """
    if not text:
        return ""

    text = text.strip()

    # 尝试多种修复策略
    repairs = [
        # 策略 1: 原始文本
        lambda t: t,
        # 策略 2: 移除尾部逗号
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t),
        # 策略 3: 单引号转双引号
        lambda t: t.replace("'", '"'),
        # 策略 4: 组合修复（移除尾部逗号 + 单引号转双引号）
        lambda t: re.sub(r',(\s*[}\]])', r'\1', t.replace("'", '"')),
    ]

    for repair_fn in repairs:
        try:
            repaired = repair_fn(text)
            parsed = json.loads(repaired)
            return json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    return ""


def _try_parse_json_tool_calls(text: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Try to detect and parse JSON-formatted tool calls as a fallback.

    Some models may output a trailing JSON tool call when the wrapper prompt
    is not followed perfectly.

    This catches common patterns like:
    1. {"name": "fn", "arguments": {...}}
    2. [{"type": "function", "function": {"name": "fn", "arguments": "..."}}]
    3. ```json\n{"name": "fn", "parameters": {...}}\n```
    4. function_call: {"name": "fn", "arguments": {...}}

    Enhanced to better handle:
    - Large data payloads (file contents, base64 data)
    - Nested JSON structures
    - Multiple consecutive JSON blocks
    """
    # Look for JSON tool call patterns at the end of the text.
    # Strategy 1: Try to find a JSON block at the end (possibly in markdown)
    # Use a simpler approach: find markdown fence and extract content
    md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```\s*$', text, re.DOTALL)
    if md_match:
        json_text = md_match.group(1).strip()
        # Check if it looks like a tool call
        if '"name"' in json_text or '"function"' in json_text:
            calls = _parse_json_as_tool_calls(json_text)
            if calls:
                content = re.sub(r"\s+$", "", text[:md_match.start()])
                logger.debug("Parsed JSON tool call from markdown block (length: %d)", len(json_text))
                return content, calls

    # Strategy 2: Look for "function_call:" or "tool_calls:" prefix
    prefix_match = re.search(
        r'(?:function_call|tool_calls?)\s*:\s*(\{.*?\}|\[.*?\])\s*$',
        text,
        re.DOTALL,
    )
    if prefix_match:
        json_text = prefix_match.group(1).strip()
        calls = _parse_json_as_tool_calls(json_text)
        if calls:
            content = re.sub(r"\s+$", "", text[:prefix_match.start()])
            logger.debug("Parsed JSON tool call from prefixed format")
            return content, calls

    # Strategy 3: Look for a complete JSON object at the end with tool call structure
    # This pattern handles both simple and deeply nested objects
    trailing_json_match = re.search(
        r'(\{(?:[^{}]|(?:\{(?:[^{}]|\{[^{}]*\})*\}))*"(?:name|function)"(?:[^{}]|(?:\{(?:[^{}]|\{[^{}]*\})*\}))*"(?:arguments|parameters|params)"(?:[^{}]|(?:\{(?:[^{}]|\{[^{}]*\})*\}))*\})\s*$',
        text,
        re.DOTALL,
    )
    if trailing_json_match:
        json_text = trailing_json_match.group(1).strip()
        calls = _parse_json_as_tool_calls(json_text)
        if calls:
            content = re.sub(r"\s+$", "", text[:trailing_json_match.start()])
            logger.debug("Parsed JSON tool call from trailing object (length: %d)", len(json_text))
            return content, calls

    # Strategy 4: Look for OpenAI-style function_call in message
    openai_match = re.search(
        r'"function_call"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"[^}]*"arguments"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}\s*$',
        text,
    )
    if openai_match:
        name = openai_match.group(1)
        args_str = openai_match.group(2).replace('\\"', '"').replace('\\\\', '\\')
        try:
            json.loads(args_str)  # Validate JSON
            calls = [{
                "id": "call_" + secrets.token_hex(8),
                "type": "function",
                "function": {"name": name, "arguments": args_str},
            }]
            content = re.sub(r"\s+$", "", text[:openai_match.start()])
            logger.debug("Parsed OpenAI-style function_call")
            return content, calls
        except (ValueError, TypeError):
            pass

    return None


def _parse_json_as_tool_calls(json_text: str) -> List[Dict[str, Any]]:
    """Try to parse a JSON string as tool calls.

    Enhanced to better handle:
    - Large data payloads (base64, file contents)
    - Deeply nested structures
    - Common JSON formatting issues
    """
    calls: List[Dict[str, Any]] = []

    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        # Try the existing JSON repair mechanism
        repaired = _repair_json(json_text)
        if repaired:
            try:
                data = json.loads(repaired)
                logger.debug("Successfully repaired and parsed JSON tool call")
            except (ValueError, TypeError):
                logger.debug("JSON repair failed for tool call")
                return []
        else:
            logger.debug("Failed to parse JSON tool call (length: %d)", len(json_text))
            return []

    if isinstance(data, dict):
        # Single tool call: {"name": "fn", "arguments": {...}}
        call = _extract_single_json_call(data)
        if call:
            calls.append(call)
    elif isinstance(data, list):
        # Array of tool calls
        for item in data:
            if isinstance(item, dict):
                call = _extract_single_json_call(item)
                if call:
                    calls.append(call)

    return calls


def _extract_single_json_call(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a tool call from a single JSON object."""
    name = None
    arguments = None

    # Pattern 1: {"name": "fn", "arguments": {...}}
    if "name" in data and ("arguments" in data or "parameters" in data or "params" in data):
        name = str(data["name"])
        arguments = data.get("arguments") or data.get("parameters") or data.get("params") or {}

    # Pattern 2: {"function": {"name": "fn", "arguments": "..."}, "type": "function"}
    elif "function" in data and isinstance(data["function"], dict):
        fn = data["function"]
        name = str(fn.get("name", ""))
        arguments = fn.get("arguments") or fn.get("parameters") or {}

    if not name:
        return None

    # Normalize arguments to JSON string
    if isinstance(arguments, str):
        # Verify it's valid JSON
        try:
            json.loads(arguments)
            args_str = arguments
        except (ValueError, TypeError):
            args_str = json.dumps({"value": arguments}, ensure_ascii=False)
    elif isinstance(arguments, dict):
        args_str = json.dumps(arguments, ensure_ascii=False)
    else:
        args_str = "{}"

    return {
        "id": "call_" + secrets.token_hex(8),
        "type": "function",
        "function": {
            "name": name,
            "arguments": args_str,
        },
    }
