"""
s05: Context Compression -- Context Window Management

Builds on s04 by adding a two-stage compressor triggered on token-estimate:
  1) Prune: replace all but the most recent tool outputs with a placeholder.
  2) Summarize: ask an LLM to condense the middle turns, keep head+tail intact.
The summary is spliced back in as a [CONTEXT COMPACTION] message, so the model
keeps task continuity without carrying the full history.

Usage:
    export OPENAI_API_KEY=sk-xxx
    python agents/s05_context_compression.py
"""

import json
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from openai import OpenAI


# ===========================================================================
# Configuration
# ===========================================================================

BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("MODEL", "anthropic/claude-sonnet-4")
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "30"))
DB_PATH = os.getenv("DB_PATH", "state.db")
HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))

# --- Compression parameters ---
COMPRESSION_THRESHOLD = 50000       # 估算 token 超过这个阈值就触发压缩
PROTECT_FIRST = 3                   # 头部保护区消息数（user 首问 + 早期工具成果往往最关键）
KEEP_RECENT_TOOL_RESULTS = 3        # 仅保留最近 N 条 tool 输出原文，更早的清空占位
TAIL_TOKEN_BUDGET = 20000           # 尾部预算：从后往前累加，直到撞线，留给模型"最近记忆"

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# ===========================================================================
# Tool registry (reused from s02)
# ===========================================================================


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
        entry = self._tools.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return entry.handler(args, **kwargs)

    def get_definitions(
        self,
        enabled_toolsets: list[str] | None = None,
    ) -> list[dict]:
        """Return OpenAI-format tool definitions filtered by toolset."""
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


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def handle_terminal(args, **kwargs):
    """Execute a shell command with safety checks."""
    command = args.get("command", "")
    for blocked in ["rm -rf /", "mkfs", "dd if=", "shutdown"]:
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
        return "(timed out)"
    except Exception as exc:
        return f"(error: {exc})"


registry.register(
    name="terminal",
    toolset="terminal",
    schema={
        "name": "terminal",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    handler=handle_terminal,
)


def handle_read_file(args, **kwargs):
    """Read a file and return its contents."""
    try:
        with open(args["path"], "r", encoding="utf-8") as file_handle:
            return file_handle.read(100_000) or "(empty)"
    except Exception as exc:
        return f"(error: {exc})"


registry.register(
    name="read_file",
    toolset="file",
    schema={
        "name": "read_file",
        "description": "Read a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    handler=handle_read_file,
)


def handle_write_file(args, **kwargs):
    """Write content to a file, creating directories as needed."""
    try:
        os.makedirs(os.path.dirname(args["path"]) or ".", exist_ok=True)
        with open(args["path"], "w", encoding="utf-8") as file_handle:
            file_handle.write(args["content"])
        return f"Written {len(args['content'])} chars"
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
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    handler=handle_write_file,
)


# ===========================================================================
# SQLite persistence (reused from s03, simplified)
# ===========================================================================


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize the SQLite database with WAL mode and required tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            started_at REAL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            timestamp REAL
        );
    """)
    return conn


def create_session(conn: sqlite3.Connection) -> str:
    """Create a new session and return its ID."""
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?)",
        (session_id, "cli", time.time()),
    )
    conn.commit()
    return session_id


def add_message(
    conn: sqlite3.Connection,
    session_id: str,
    msg: dict,
):
    """Persist a message to the database."""
    tool_calls_json = None
    if msg.get("tool_calls"):
        tool_calls_json = json.dumps(msg["tool_calls"])

    conn.execute(
        """
        INSERT INTO messages
            (session_id, role, content, tool_calls, tool_call_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            msg["role"],
            msg.get("content", ""),
            tool_calls_json,
            msg.get("tool_call_id"),
            time.time(),
        ),
    )
    conn.commit()


def get_session_messages(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict]:
    """Load all messages for a session from the database."""
    rows = conn.execute(
        """
        SELECT role, content, tool_calls, tool_call_id
        FROM messages
        WHERE session_id = ?
        ORDER BY id
        """,
        (session_id,),
    ).fetchall()

    messages = []
    for role, content, tool_calls_json, tool_call_id in rows:
        msg: dict = {"role": role, "content": content or ""}
        if tool_calls_json:
            msg["tool_calls"] = json.loads(tool_calls_json)
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        messages.append(msg)
    return messages


# ===========================================================================
# System prompt assembly (reused from s04)
# ===========================================================================


def load_soul() -> str:
    """Load the agent's core identity from SOUL.md."""
    soul_path = HERMES_HOME / "SOUL.md"
    if soul_path.exists():
        return soul_path.read_text(encoding="utf-8")[:20000]
    return "You are a helpful assistant."


def load_memory() -> str:
    """Load persistent memory entries from MEMORY.md."""
    memory_path = HERMES_HOME / "memories" / "MEMORY.md"
    if memory_path.exists():
        return memory_path.read_text(encoding="utf-8")[:5000]
    return ""


def find_project_context(cwd: str) -> str:
    """Find and load the project configuration file by priority."""
    for name in [".hermes.md", "HERMES.md"]:
        path = Path(cwd) / name
        if path.exists():
            return path.read_text(encoding="utf-8")[:20000]

    for name in ["AGENTS.md", "CLAUDE.md", ".cursorrules"]:
        path = Path(cwd) / name
        if path.exists():
            return path.read_text(encoding="utf-8")[:20000]

    return ""


def build_system_prompt(cwd: str) -> str:
    """Assemble the system prompt from multiple sources."""
    parts = [load_soul()]

    memory = load_memory()
    if memory:
        parts.append(f"# Memory\n{memory}")

    project = find_project_context(cwd)
    if project:
        parts.append(f"# Project Context\n{project}")

    parts.append(
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {cwd}"
    )

    return "\n\n".join(parts)


# ===========================================================================
# Context compression (new in this chapter)
# ===========================================================================
# 压缩分两步：先把老的 tool 输出 prune 掉（它们往往最肥），再 summarize 中段


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: character count / 4."""
    # 粗略但够用：英文约 4 char/token，中文更高估，偏保守是好事
    total_chars = sum(
        len(str(msg.get("content", "")))
        for msg in messages
    )
    return total_chars // 4


def prune_old_tool_results(
    messages: list[dict],
    keep_recent: int = KEEP_RECENT_TOOL_RESULTS,
) -> list[dict]:
    """Replace old tool outputs with placeholders, keeping only the recent ones."""
    # 只替换 content，不删除消息本身——必须保留 tool_call_id 以维持 assistant↔tool 的配对
    tool_indices = [
        index
        for index, msg in enumerate(messages)
        if msg.get("role") == "tool"
    ]

    for index in tool_indices[:-keep_recent]:
        messages[index] = {
            **messages[index],
            "content": "[Old tool output cleared]",
        }

    return messages


def find_boundaries(
    messages: list[dict],
    protect_first: int,
    tail_token_budget: int,
) -> tuple[int, int]:
    """Find the compressible middle region: protect head + protect tail."""
    # 从尾部往前累加 token，直到 tail_start 处的累计量逼近预算；中间段 [head_end, tail_start) 就是要摘要的部分
    head_end = protect_first
    tail_start = len(messages)
    tail_tokens = 0

    for index in range(len(messages) - 1, head_end - 1, -1):
        msg_tokens = len(str(messages[index].get("content", ""))) // 4
        if tail_tokens + msg_tokens > tail_token_budget:
            break
        tail_tokens += msg_tokens
        tail_start = index

    return head_end, tail_start


def summarize_middle(turns: list[dict]) -> str:
    """Use an auxiliary LLM call to summarize the middle conversation turns."""
    # 固定段落结构让模型照格子填，便于后面主对话复用；每条消息截 500 字避免 prompt 爆炸
    prompt = (
        "Summarize these conversation turns concisely.\n"
        "Sections: Goal, Progress, Key Decisions, "
        "Files Modified, Next Steps.\n\n"
    )
    for msg in turns:
        content_preview = str(msg.get("content", ""))[:500]
        prompt += f"[{msg['role']}] {content_preview}\n"

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        return response.choices[0].message.content or "(summary failed)"
    except Exception as exc:
        return f"(summary error: {exc})"


def compress(messages: list[dict]) -> list[dict]:
    """Perform one round of context compression."""
    # 1) prune 老 tool 输出；2) 定位中段；3) LLM 摘要后拼回
    messages = prune_old_tool_results(list(messages))
    head_end, tail_start = find_boundaries(
        messages, PROTECT_FIRST, TAIL_TOKEN_BUDGET
    )

    # 尾部已经覆盖到头部保护区之前：说明总量本来就不大，不值得摘要
    if tail_start <= head_end:
        return messages

    middle = messages[head_end:tail_start]
    summary = summarize_middle(middle)

    print(
        f"  [compress] Compressed {len(middle)} messages "
        f"into summary ({len(summary)} chars)"
    )

    # 用一条 [CONTEXT COMPACTION] user 消息替换原中段
    # 伪装成 user 消息是为了避开 assistant/tool 配对校验
    return (
        messages[:head_end]
        + [{"role": "user", "content": f"[CONTEXT COMPACTION]\n{summary}"}]
        + messages[tail_start:]
    )


# ===========================================================================
# Core conversation loop (s04 + compression trigger)
# ===========================================================================

ENABLED_TOOLSETS = ["terminal", "file"]


def run_conversation(
    user_message: str,
    conn: sqlite3.Connection,
    session_id: str,
    cached_prompt: str,
) -> dict:
    """Run a conversation loop with context compression."""
    messages = get_session_messages(conn, session_id)
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    add_message(conn, session_id, user_msg)

    tools = registry.get_definitions(ENABLED_TOOLSETS)

    for iteration in range(MAX_ITERATIONS):
        # 每轮发请求前先体检：超阈值就压缩一次；压缩是幂等的，不会重复损伤消息
        if estimate_tokens(messages) >= COMPRESSION_THRESHOLD:
            messages = compress(messages)

        api_messages = (
            [{"role": "system", "content": cached_prompt}] + messages
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
        add_message(conn, session_id, msg_dict)

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
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            }
            messages.append(tool_msg)
            add_message(conn, session_id, tool_msg)

    return {
        "final_response": "(max iterations reached)",
        "messages": messages,
    }


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    print("=== s05: Context Compression ===")
    print(
        f"Model: {MODEL} | "
        f"Compression threshold: {COMPRESSION_THRESHOLD} tokens"
    )

    conn = init_db(DB_PATH)
    session_id = create_session(conn)
    cached_prompt = build_system_prompt(os.getcwd())
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit"):
            break
        result = run_conversation(
            user_input, conn, session_id, cached_prompt
        )
        print(f"\nAssistant: {result['final_response']}\n")

    conn.close()
