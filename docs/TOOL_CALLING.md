# 工具调用功能 (Tool Calling)

Kimi2API 现在支持 OpenAI 兼容的工具调用功能，允许模型在需要时请求调用外部工具或函数。

## 功能特性

- ✅ **OpenAI 兼容接口** - 完全兼容 OpenAI 的 tools 和 tool_choice 参数
- ✅ **自动工具指令注入** - 将工具定义转换为 Kimi 可理解的提示词格式
- ✅ **智能工具调用解析** - 从模型响应中自动识别和提取工具调用
- ✅ **多格式支持** - 支持 `[function_calls]` 和 `<function_calls>` 两种标记格式
- ✅ **流式和非流式** - 同时支持流式和非流式输出
- ✅ **多轮对话** - 支持工具结果反馈和多轮交互

## 快速开始

### 基本示例

```python
from openai import OpenAI

client = OpenAI(
    api_key="your_api_key_here",
    base_url="http://127.0.0.1:8000/v1",
)

# 定义工具
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

# 发送请求
response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[
        {"role": "user", "content": "北京今天天气怎么样？"}
    ],
    tools=tools
)

# 检查是否需要调用工具
if response.choices[0].finish_reason == "tool_calls":
    tool_calls = response.choices[0].message.tool_calls
    for tool_call in tool_calls:
        function_name = tool_call.function.name
        arguments = tool_call.function.arguments
        print(f"调用工具: {function_name}")
        print(f"参数: {arguments}")
```

### 完整对话流程

```python
import json

# 第一轮：用户提问
messages = [
    {"role": "user", "content": "帮我查询北京的天气"}
]

response = client.chat.completions.create(
    model="kimi-k2.6",
    messages=messages,
    tools=tools
)

# 第二轮：执行工具并返回结果
if response.choices[0].finish_reason == "tool_calls":
    for tool_call in response.choices[0].message.tool_calls:
        # 执行工具
        result = execute_tool(tool_call.function.name, 
                            json.loads(tool_call.function.arguments))
        
        # 添加助手的工具调用请求
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [tool_call.model_dump()]
        })
        
        # 添加工具执行结果
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result)
        })
    
    # 第三轮：模型基于工具结果回答
    final_response = client.chat.completions.create(
        model="kimi-k2.6",
        messages=messages
    )
    
    print(final_response.choices[0].message.content)
```

### 流式输出

```python
stream = client.chat.completions.create(
    model="kimi-k2.6",
    messages=[{"role": "user", "content": "查询上海天气"}],
    tools=tools,
    stream=True
)

for chunk in stream:
    delta = chunk.choices[0].delta
    
    if delta.content:
        print(delta.content, end="", flush=True)
    
    if delta.tool_calls:
        print(f"\n工具调用: {delta.tool_calls}")
    
    if chunk.choices[0].finish_reason == "tool_calls":
        print("\n需要调用工具")
```

## API 参数

### tools

工具定义数组，每个工具包含：

```python
{
    "type": "function",  # 固定为 "function"
    "function": {
        "name": "工具名称",
        "description": "工具功能描述",
        "parameters": {
            # JSON Schema 格式的参数定义
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "参数描述"
                }
            },
            "required": ["param1"]
        }
    }
}
```

### tool_choice

控制模型是否使用工具：

- `"auto"` (默认) - 模型自动决定是否调用工具
- `"none"` - 禁用工具调用
- `{"type": "function", "function": {"name": "工具名"}}` - 强制调用特定工具

## 响应格式

### 非流式响应

当模型决定调用工具时：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "kimi-k2.6",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"city\": \"北京\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {...}
}
```

### 流式响应

```
data: {"id":"chatcmpl-xxx","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","choices":[{"index":0,"delta":{"tool_calls":[{"id":"call_abc","type":"function","function":{"name":"get_weather","arguments":"{\"city\":\"北京\"}"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}

data: [DONE]
```

## 工具调用格式

Kimi 模型会使用以下格式输出工具调用：

```
[function_calls]
[call:get_weather]
{"city": "北京"}
[/call]
[/function_calls]
```

或使用尖括号格式：

```
<function_calls>
<call:get_weather>
{"city": "北京"}
</call>
</function_calls>
```

Kimi2API 会自动解析这些格式并转换为 OpenAI 兼容的响应。

## 最佳实践

### 1. 工具描述要清晰

```python
{
    "name": "get_weather",
    "description": "获取指定城市的实时天气信息，包括温度、湿度、天气状况等",
    # 清晰的描述帮助模型正确判断何时使用工具
}
```

### 2. 参数验证

```python
import json

def execute_tool(name: str, arguments_str: str):
    try:
        args = json.loads(arguments_str)
        # 验证必需参数
        if name == "get_weather" and "city" not in args:
            return json.dumps({"error": "缺少必需参数: city"})
        
        # 执行工具逻辑
        return get_weather(args["city"])
    except json.JSONDecodeError:
        return json.dumps({"error": "参数格式错误"})
```

### 3. 错误处理

```python
try:
    response = client.chat.completions.create(
        model="kimi-k2.6",
        messages=messages,
        tools=tools
    )
except Exception as e:
    print(f"请求失败: {e}")
```

### 4. 多个工具

```python
tools = [
    {"type": "function", "function": {"name": "get_weather", ...}},
    {"type": "function", "function": {"name": "search_web", ...}},
    {"type": "function", "function": {"name": "calculate", ...}},
]

# 模型会根据用户问题选择合适的工具
```

## 示例代码

完整的示例代码请参考：

- `examples/tool_calling_example.py` - Python 示例
- `tests/test_tool_calling.py` - 单元测试

运行示例：

```bash
# 设置环境变量
export KIMI_TOKEN="your_token_here"

# 运行示例
python examples/tool_calling_example.py
```

## 注意事项

1. **工具调用不保证** - 模型可能选择直接回答而不调用工具
2. **JSON 格式** - 工具参数必须是有效的 JSON 格式
3. **多轮对话** - 工具调用需要多轮对话才能完成完整流程
4. **token 消耗** - 工具定义会注入到提示词中，增加 token 消耗

## 兼容性

- ✅ OpenAI Python SDK (>= 1.0.0)
- ✅ OpenAI Node.js SDK
- ✅ LangChain
- ✅ LlamaIndex
- ✅ 其他 OpenAI 兼容客户端

## 常见问题

### Q: 模型没有调用工具？

A: 确保工具描述清晰，并且用户的问题确实需要使用工具。可以尝试更明确的提示：

```python
messages = [
    {"role": "system", "content": "当用户询问天气时，使用 get_weather 工具查询。"},
    {"role": "user", "content": "北京天气"}
]
```

### Q: 工具参数格式错误？

A: Kimi2API 会尝试修复常见的 JSON 格式错误（如尾部逗号、单引号等），但建议在工具描述中明确参数格式。

### Q: 支持并行工具调用吗？

A: 是的，模型可以在一次响应中请求调用多个工具。

## 更新日志

### 2024-06-24

- ✅ 实现 OpenAI 兼容的工具调用支持
- ✅ 支持流式和非流式输出
- ✅ 自动工具指令注入
- ✅ 智能工具调用解析
- ✅ 完整的测试覆盖

## 参考

- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [ds2api 工具调用实现](https://github.com/CJackHwang/ds2api)
