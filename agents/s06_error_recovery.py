"""
s06: Error Recovery -- Error Recovery and Failover

Builds on s05 by turning raw API exceptions into actionable policy decisions:
classify the error, then choose one of {retry w/ backoff, compress, fall back,
give up}. Also auto-continues when the model truncates with finish_reason=length.

Usage:
    export OPENAI_API_KEY=sk-xxx
    python agents/s06_error_recovery.py
"""

import json
import os
import random
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

# --- Fallback model (optional): 主模型不可用时切到备用模型 ---
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", BASE_URL)
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", API_KEY)

# --- Compression parameters (同 s05) ---
COMPRESSION_THRESHOLD = 50000
PROTECT_FIRST = 3
KEEP_RECENT_TOOL_RESULTS = 3
TAIL_TOKEN_BUDGET = 20000

# --- Retry parameters ---
MAX_RETRIES = 3                                        # 单轮 API 调用的最大重试次数
CONTINUE_MESSAGE = "Please continue from where you left off."
MAX_CONTINUATIONS = 3                                  # 连续被 length 截断时，最多再让模型续写几次

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
# System prompt + compression (reused from s04/s05)
# ===========================================================================


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
    parts = []

    soul_path = HERMES_HOME / "SOUL.md"
    if soul_path.exists():
        parts.append(soul_path.read_text(encoding="utf-8")[:20000])
    else:
        parts.append("You are a helpful assistant.")

    memory_path = HERMES_HOME / "memories" / "MEMORY.md"
    if memory_path.exists():
        memory_text = memory_path.read_text(encoding="utf-8")[:5000]
        parts.append(f"# Memory\n{memory_text}")

    project = find_project_context(cwd)
    if project:
        parts.append(f"# Project Context\n{project}")

    parts.append(
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {cwd}"
    )

    return "\n\n".join(parts)


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: character count / 4."""
    total_chars = sum(
        len(str(msg.get("content", "")))
        for msg in messages
    )
    return total_chars // 4


def compress(messages: list[dict]) -> list[dict]:
    """Perform one round of context compression."""
    # Prune old tool outputs
    tool_indices = [
        index
        for index, msg in enumerate(messages)
        if msg.get("role") == "tool"
    ]
    for index in tool_indices[:-KEEP_RECENT_TOOL_RESULTS]:
        messages[index] = {
            **messages[index],
            "content": "[Old tool output cleared]",
        }

    # Find compression boundaries
    head_end = PROTECT_FIRST
    tail_start = len(messages)
    tail_tokens = 0

    for index in range(len(messages) - 1, head_end - 1, -1):
        msg_tokens = len(str(messages[index].get("content", ""))) // 4
        if tail_tokens + msg_tokens > TAIL_TOKEN_BUDGET:
            break
        tail_tokens += msg_tokens
        tail_start = index

    if tail_start <= head_end:
        return messages

    # Summarize the middle section
    middle = messages[head_end:tail_start]
    summary_parts = [
        f"[{msg['role']}] {str(msg.get('content', ''))[:500]}"
        for msg in middle
    ]
    prompt = "Summarize concisely:\n" + "\n".join(summary_parts)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        summary = response.choices[0].message.content or "(summary failed)"
    except Exception as exc:
        summary = f"(summary error: {exc})"

    print(f"  [compress] {len(middle)} messages -> summary")

    return (
        messages[:head_end]
        + [{"role": "user", "content": f"[CONTEXT COMPACTION]\n{summary}"}]
        + messages[tail_start:]
    )


# ===========================================================================
# Error recovery (new in this chapter)
# ===========================================================================
# 将底层异常转成结构化"决策"：retryable / should_compress / should_fallback，
# 让调用点按 flag 执行相应动作，而不是在 except 里堆 if-elif


def classify_error(
    status_code: int | None,
    error_message: str,
) -> dict:
    """Classify an API error into an actionable decision."""
    # 429：限流，等等再试即可
    if status_code == 429:
        return {
            "reason": "rate_limit",
            "retryable": True,
            "should_compress": False,
            "should_fallback": False,
        }

    # 400 + 提到 context：上下文超限，压缩后重试
    if status_code == 400 and "context" in error_message.lower():
        return {
            "reason": "context_overflow",
            "retryable": True,
            "should_compress": True,
            "should_fallback": False,
        }

    # 5xx：服务端临时问题，等等再试
    if status_code in (500, 502, 503):
        return {
            "reason": "server_error",
            "retryable": True,
            "should_compress": False,
            "should_fallback": False,
        }

    # 401/403：鉴权失败，重试无意义；尝试切到 fallback（可能用不同的 key）
    if status_code in (401, 403):
        return {
            "reason": "auth",
            "retryable": False,
            "should_compress": False,
            "should_fallback": True,
        }

    # 404：主模型找不到了，直接切 fallback
    if status_code == 404:
        return {
            "reason": "model_not_found",
            "retryable": False,
            "should_compress": False,
            "should_fallback": True,
        }

    return {
        "reason": "unknown",
        "retryable": False,
        "should_compress": False,
        "should_fallback": False,
    }


def jittered_backoff(
    attempt: int,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
) -> float:
    """Calculate exponential backoff with random jitter."""
    # 指数退避避免雪崩；加随机抖动避免多客户端同时重试造成的"峰谷共振"
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = random.uniform(0, delay * 0.5)
    return delay + jitter


def switch_to_fallback():
    """Switch to the fallback model. Returns (new_client, new_model) or (None, None)."""
    if not FALLBACK_MODEL:
        return None, None
    print(f"  [fallback] Switching to fallback model: {FALLBACK_MODEL}")
    fallback_client = OpenAI(
        base_url=FALLBACK_BASE_URL,
        api_key=FALLBACK_API_KEY,
    )
    return fallback_client, FALLBACK_MODEL


# ===========================================================================
# Core conversation loop (s05 + error recovery + continuation)
# ===========================================================================

ENABLED_TOOLSETS = ["terminal", "file"]


def run_conversation(
    user_message: str,
    conn: sqlite3.Connection,
    session_id: str,
    cached_prompt: str,
) -> dict:
    """Run a conversation loop with error recovery and auto-continuation."""
    messages = get_session_messages(conn, session_id)
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    add_message(conn, session_id, user_msg)

    tools = registry.get_definitions(ENABLED_TOOLSETS)
    active_client = client
    active_model = MODEL
    retry_count = 0
    continuation_count = 0

    for iteration in range(MAX_ITERATIONS):
        if estimate_tokens(messages) >= COMPRESSION_THRESHOLD:
            messages = compress(messages)

        api_messages = (
            [{"role": "system", "content": cached_prompt}] + messages
        )

        # 本章核心：API 调用异常不再直接抛出，按 classify_error 决策 compress / fallback / retry
        try:
            response = active_client.chat.completions.create(
                model=active_model,
                messages=api_messages,
                tools=tools,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            classified = classify_error(status, str(exc))
            print(
                f"  [error] {classified['reason']} (status={status})"
            )

            # 优先级：压缩 > 切换模型 > 退避重试；一轮异常至多执行其中一个动作，然后 continue 重试
            if classified["should_compress"]:
                messages = compress(messages)
                continue

            if classified["should_fallback"]:
                fallback_client, fallback_model = switch_to_fallback()
                if fallback_client:
                    active_client = fallback_client
                    active_model = fallback_model
                    continue
                raise

            if classified["retryable"] and retry_count < MAX_RETRIES:
                retry_count += 1
                delay = jittered_backoff(retry_count)
                print(
                    f"  [retry] Retrying in {delay:.1f}s "
                    f"(attempt {retry_count}/{MAX_RETRIES})"
                )
                time.sleep(delay)
                continue

            # 不可恢复错误：抛给上层让 CLI 层统一处理
            raise

        # 成功一次就清零重试计数，下一次异常重新从 0 开始累计
        retry_count = 0
        assistant_msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

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

        # 自动续写：模型因 max_tokens 被截断时，注入 "请继续" 让它接着写
        if finish_reason == "length" and continuation_count < MAX_CONTINUATIONS:
            continuation_count += 1
            cont_msg = {"role": "user", "content": CONTINUE_MESSAGE}
            messages.append(cont_msg)
            add_message(conn, session_id, cont_msg)
            print(
                f"  [continue] Continuation "
                f"{continuation_count}/{MAX_CONTINUATIONS}"
            )
            continue

        if not assistant_msg.tool_calls:
            return {
                "final_response": assistant_msg.content,
                "messages": messages,
            }

        # 模型恢复使用工具，说明已经"回到正轨"；清零续写计数
        continuation_count = 0
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
    print("=== s06: Error Recovery ===")
    print(f"Model: {MODEL}")
    if FALLBACK_MODEL:
        print(f"Fallback: {FALLBACK_MODEL}")
    print(
        f"Max retries: {MAX_RETRIES} | "
        f"Max continuations: {MAX_CONTINUATIONS}"
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
