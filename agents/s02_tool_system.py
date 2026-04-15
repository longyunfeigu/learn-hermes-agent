"""
s02: Tool System -- Self-Registering Tool Registry

Builds on s01 by extracting the tool layer: each tool registers itself with a
ToolRegistry, and the loop dispatches via name lookup. Adding a new tool is now
a single register() call and doesn't touch the loop.

Usage:
    export OPENAI_API_KEY=sk-xxx
    python agents/s02_tool_system.py
"""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from openai import OpenAI


# ===========================================================================
# Configuration
# ===========================================================================

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("MODEL", "anthropic/claude-sonnet-4")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "You can run shell commands, read/write files, and search the web."
)


# ===========================================================================
# Tool registry
# ===========================================================================
# 工具的元数据 + 实现，一条一条登记到全局 registry 里。
# toolset 用于分组启用（例如只启用 "file" 类工具），见 get_definitions 的过滤


@dataclass
class ToolEntry:
    """A registered tool with its metadata and handler."""
    name: str
    toolset: str
    schema: dict
    handler: Callable


class ToolRegistry:
    """Central registry for all agent tools."""

    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}

    def register(
        self,
        name: str,
        toolset: str,
        schema: dict,
        handler: Callable,
    ):
        """Register a tool by name with its schema and handler."""
        self._tools[name] = ToolEntry(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
        )

    def dispatch(self, name: str, args: dict, **kwargs) -> str:
        """Look up a tool by name and execute its handler."""
        # 额外 kwargs 预留给后续章节（如 s03 传 conn / s09 传 session）
        entry = self._tools.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return entry.handler(args, **kwargs)

    def get_definitions(
        self,
        enabled_toolsets: list[str] | None = None,
    ) -> list[dict]:
        """Return OpenAI-format tool definitions, optionally filtered by toolset."""
        # 按 toolset 过滤，让不同场景的 agent 只看到允许的工具
        definitions = []
        for entry in self._tools.values():
            if enabled_toolsets and entry.toolset not in enabled_toolsets:
                continue
            definitions.append({
                "type": "function",
                "function": entry.schema,
            })
        return definitions


registry = ToolRegistry()


# ===========================================================================
# Tool implementations (each tool self-registers)
# ===========================================================================
# 模式：定义 handler -> 紧跟着调用 registry.register()。一个文件里看得到全部信息

BLOCKED_COMMANDS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
]


def handle_terminal(args, **kwargs):
    """Execute a shell command with safety checks."""
    command = args.get("command", "")

    for blocked in BLOCKED_COMMANDS:
        if blocked in command:
            return json.dumps({"error": f"Blocked: {blocked}"})

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        return output[:10000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "(command timed out after 30s)"
    except Exception as exc:
        return f"(error: {exc})"


registry.register(
    name="terminal",
    toolset="terminal",
    schema={
        "name": "terminal",
        "description": "Run a shell command and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command",
                }
            },
            "required": ["command"],
        },
    },
    handler=handle_terminal,
)


def handle_read_file(args, **kwargs):
    """Read a file and return its contents."""
    path = args.get("path", "")
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            content = file_handle.read(100_000)
        return content if content else "(empty file)"
    except Exception as exc:
        return f"(error: {exc})"


registry.register(
    name="read_file",
    toolset="file",
    schema={
        "name": "read_file",
        "description": "Read a file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path",
                }
            },
            "required": ["path"],
        },
    },
    handler=handle_read_file,
)


def handle_write_file(args, **kwargs):
    """Write content to a file, creating directories as needed."""
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as exc:
        return f"(error: {exc})"


registry.register(
    name="write_file",
    toolset="file",
    schema={
        "name": "write_file",
        "description": "Write content to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    handler=handle_write_file,
)


def handle_web_search(args, **kwargs):
    """Stub implementation for web search."""
    # 占位实现，教学里不依赖真实搜索；要接真实 API 只改这个函数即可
    query = args.get("query", "")
    return json.dumps({
        "note": "web_search is a stub in this teaching version",
        "query": query,
    })


registry.register(
    name="web_search",
    toolset="web",
    schema={
        "name": "web_search",
        "description": "Search the web for information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                }
            },
            "required": ["query"],
        },
    },
    handler=handle_web_search,
)


# ===========================================================================
# Core conversation loop (same as s01, but tools come from the registry)
# ===========================================================================
# 本章关键差异：tools/dispatch 都通过 registry，不再硬编码

ENABLED_TOOLSETS = ["terminal", "file", "web"]


def run_conversation(user_message: str) -> dict:
    """Run a conversation loop using registry-based tool dispatch."""
    messages = [{"role": "user", "content": user_message}]
    tools = registry.get_definitions(ENABLED_TOOLSETS)

    for iteration in range(MAX_ITERATIONS):
        api_messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        )

        response = client.chat.completions.create(
            model=MODEL,
            messages=api_messages,
            tools=tools,
        )

        assistant_msg = response.choices[0].message

        msg_dict: dict = {
            "role": "assistant",
            "content": assistant_msg.content or "",
        }
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in assistant_msg.tool_calls
            ]
        messages.append(msg_dict)

        if not assistant_msg.tool_calls:
            return {
                "final_response": assistant_msg.content,
                "messages": messages,
            }

        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            print(
                f"  [tool] {tool_name}: "
                f"{json.dumps(tool_args, ensure_ascii=False)[:120]}"
            )
            output = registry.dispatch(tool_name, tool_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })

    return {
        "final_response": "(max iterations reached)",
        "messages": messages,
    }


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    print("=== s02: Tool System ===")
    print(f"Model: {MODEL}")
    tools = registry.get_definitions(ENABLED_TOOLSETS)
    print(f"Tools: {[t['function']['name'] for t in tools]}")
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit"):
            break
        result = run_conversation(user_input)
        print(f"\nAssistant: {result['final_response']}\n")
