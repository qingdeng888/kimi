#!/usr/bin/env python3
"""
工具调用示例脚本

演示如何使用 Kimi2API 的工具调用功能
"""

import asyncio
import json
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.kimi import Kimi2API


# 定义工具
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的当前天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称，例如：北京、上海"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "在互联网上搜索信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


# 模拟工具执行
def execute_tool(tool_name: str, arguments: dict) -> str:
    """模拟执行工具调用"""
    if tool_name == "get_weather":
        city = arguments.get("city", "")
        unit = arguments.get("unit", "celsius")
        # 模拟天气数据
        return json.dumps({
            "city": city,
            "temperature": 22 if unit == "celsius" else 72,
            "unit": unit,
            "condition": "晴朗",
            "humidity": 45
        }, ensure_ascii=False)

    elif tool_name == "search_web":
        query = arguments.get("query", "")
        # 模拟搜索结果
        return json.dumps({
            "query": query,
            "results": [
                {"title": "搜索结果1", "snippet": "相关内容摘要..."},
                {"title": "搜索结果2", "snippet": "更多相关信息..."}
            ]
        }, ensure_ascii=False)

    return "工具执行失败"


async def example_sync_tool_call():
    """示例：同步模式工具调用"""
    print("\n" + "="*60)
    print("示例 1: 同步模式工具调用")
    print("="*60)

    messages = [
        {"role": "user", "content": "帮我查询北京和上海的天气"}
    ]

    async with Kimi2API() as client:
        print("\n🔄 发送请求...")
        response = await client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            print("\n✅ 模型请求调用工具:")

            # 执行工具调用
            for tool_call in choice.tool_calls:
                function_name = tool_call["function"]["name"]
                arguments = json.loads(tool_call["function"]["arguments"])

                print(f"\n  📞 调用工具: {function_name}")
                print(f"     参数: {json.dumps(arguments, ensure_ascii=False)}")

                # 执行工具
                result = execute_tool(function_name, arguments)
                print(f"     结果: {result}")

                # 将工具结果添加到消息历史
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result
                })

            # 再次调用模型，让它基于工具结果回答
            print("\n🔄 发送工具结果给模型...")
            final_response = await client.chat.completions.create(
                model="kimi-k2.6",
                messages=messages
            )

            print("\n💬 模型最终回答:")
            print(f"   {final_response.choices[0].message.content}")
        else:
            print("\n💬 模型直接回答:")
            print(f"   {choice.message.content}")


async def example_stream_tool_call():
    """示例：流式模式工具调用"""
    print("\n" + "="*60)
    print("示例 2: 流式模式工具调用")
    print("="*60)

    messages = [
        {"role": "user", "content": "搜索一下人工智能的最新进展"}
    ]

    async with Kimi2API() as client:
        print("\n🔄 发送流式请求...")
        stream = await client.chat.completions.create(
            model="kimi-k2.6",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True
        )

        print("\n📡 接收流式响应:")
        tool_calls = []
        content_parts = []

        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.get("delta", {})

            if delta.get("role"):
                print(f"   角色: {delta['role']}")

            if delta.get("content"):
                content_parts.append(delta["content"])
                print(f"   内容: {delta['content']}", end="", flush=True)

            if delta.get("tool_calls"):
                tool_calls.extend(delta["tool_calls"])
                print(f"\n   🔧 工具调用: {json.dumps(delta['tool_calls'], ensure_ascii=False)}")

            if choice.get("finish_reason"):
                print(f"\n   完成原因: {choice['finish_reason']}")

        if tool_calls:
            print("\n✅ 检测到工具调用，可以执行工具并继续对话")


async def example_multi_turn_conversation():
    """示例：多轮对话与工具调用"""
    print("\n" + "="*60)
    print("示例 3: 多轮对话与工具调用")
    print("="*60)

    messages = [
        {"role": "system", "content": "你是一个有帮助的助手，可以查询天气和搜索网络信息。"},
        {"role": "user", "content": "北京今天天气怎么样？"}
    ]

    async with Kimi2API() as client:
        for turn in range(3):  # 最多3轮对话
            print(f"\n--- 第 {turn + 1} 轮 ---")
            print(f"👤 用户: {messages[-1]['content']}")

            response = await client.chat.completions.create(
                model="kimi-k2.6",
                messages=messages,
                tools=TOOLS
            )

            choice = response.choices[0]

            if choice.finish_reason == "tool_calls":
                print("🤖 助手: [调用工具]")

                # 执行所有工具调用
                for tool_call in choice.tool_calls:
                    function_name = tool_call["function"]["name"]
                    arguments = json.loads(tool_call["function"]["arguments"])
                    result = execute_tool(function_name, arguments)

                    print(f"   📞 {function_name}({json.dumps(arguments, ensure_ascii=False)})")
                    print(f"   ✅ 结果: {result}")

                    # 添加到消息历史
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result
                    })
            else:
                print(f"🤖 助手: {choice.message.content}")
                messages.append({
                    "role": "assistant",
                    "content": choice.message.content
                })
                break  # 正常回答，结束对话


async def main():
    """主函数"""
    print("\n" + "="*60)
    print("Kimi2API 工具调用功能演示")
    print("="*60)

    # 检查环境变量
    if not os.getenv("KIMI_TOKEN") and not os.getenv("ADMIN_PASSWORD"):
        print("\n⚠️  警告: 未设置 KIMI_TOKEN 环境变量")
        print("请设置环境变量或在 .env 文件中配置")
        return

    try:
        # 运行示例
        await example_sync_tool_call()
        await asyncio.sleep(1)

        await example_stream_tool_call()
        await asyncio.sleep(1)

        await example_multi_turn_conversation()

        print("\n" + "="*60)
        print("✅ 所有示例执行完成")
        print("="*60)

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
