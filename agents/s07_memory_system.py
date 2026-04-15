"""
s07: Memory System -- Cross-Session Persistent Knowledge

Builds on s06 by giving the agent a pair of Markdown memory files
(MEMORY.md for general facts, USER.md for user-profile notes), and a
`memory` tool for add/remove/read. The snapshot is frozen into the system
prompt at session start; mid-session writes hit disk immediately but the
prompt only picks them up on the next session.

Usage:
    export OPENAI_API_KEY=sk-xxx
    python agents/s07_memory_system.py
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

FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")
FALLBACK_BASE_URL = os.getenv("FALLBACK_BASE_URL", BASE_URL)
FALLBACK_API_KEY = os.getenv("FALLBACK_API_KEY", API_KEY)

COMPRESSION_THRESHOLD = 50000
PROTECT_FIRST = 3
KEEP_RECENT_TOOL_RESULTS = 3
TAIL_TOKEN_BUDGET = 20000
MAX_RETRIES = 3
CONTINUE_MESSAGE = "Please continue from where you left off."
MAX_CONTINUATIONS = 3

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
# Compression + error recovery (reused from s05/s06)
# ===========================================================================


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: character count / 4."""
    total_chars = sum(
        len(str(msg.get("content", "")))
        for msg in messages
    )
    return total_chars // 4


def compress(messages: list[dict]) -> list[dict]:
    """Perform one round of context compression."""
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


def classify_error(
    status_code: int | None,
    error_message: str,
) -> dict:
    """Classify an API error into an actionable decision."""
    if status_code == 429:
        return {
            "reason": "rate_limit",
            "retryable": True,
            "should_compress": False,
            "should_fallback": False,
        }
    if status_code == 400 and "context" in error_message.lower():
        return {
            "reason": "context_overflow",
            "retryable": True,
            "should_compress": True,
            "should_fallback": False,
        }
    if status_code in (500, 502, 503):
        return {
            "reason": "server_error",
            "retryable": True,
            "should_compress": False,
            "should_fallback": False,
        }
    if status_code in (401, 403):
        return {
            "reason": "auth",
            "retryable": False,
            "should_compress": False,
            "should_fallback": True,
        }
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
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    return delay + random.uniform(0, delay * 0.5)


def switch_to_fallback():
    """Switch to the fallback model. Returns (client, model) or (None, None)."""
    if not FALLBACK_MODEL:
        return None, None
    print(f"  [fallback] -> {FALLBACK_MODEL}")
    fallback_client = OpenAI(
        base_url=FALLBACK_BASE_URL,
        api_key=FALLBACK_API_KEY,
    )
    return fallback_client, FALLBACK_MODEL


# ===========================================================================
# Memory system (new in this chapter)
# ===========================================================================
# 两个文件 + 一个分隔符：简单到能用 grep/肉眼审阅，也方便以后迁移到别的后端

MEMORY_DIR = HERMES_HOME / "memories"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"            # 通用知识
USER_FILE = MEMORY_DIR / "USER.md"                # 用户画像
ENTRY_SEP = "\n\n\u00a7\n\n"                      # 用罕见的 § 做分隔符，避免与正文冲突
MEMORY_CHAR_LIMIT = 2200                          # 字符上限，超出按 FIFO 丢弃末尾
USER_CHAR_LIMIT = 1375


def parse_entries(text: str) -> list[str]:
    """Split section-mark-delimited text into a list of entries."""
    if not text.strip():
        return []
    return [entry.strip() for entry in text.split("\u00a7") if entry.strip()]


def render_entries(entries: list[str]) -> str:
    """Join entries back into section-mark-delimited text."""
    return ENTRY_SEP.join(entries)


def load_memory(file_path: Path) -> list[str]:
    """Load memory entries from a file."""
    if not file_path.exists():
        return []
    return parse_entries(file_path.read_text(encoding="utf-8"))


def save_memory(
    file_path: Path,
    entries: list[str],
    char_limit: int,
) -> str:
    """Save memory entries to a file, trimming if over the char limit."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    text = render_entries(entries)
    warning = ""

    # 超出上限就从末尾 pop（默认新条目在末尾追加，所以 FIFO 效果等价于"丢弃最早的新条目"）
    # 这里用 while 是为了处理"单条就超限"的极端情形
    if len(text) > char_limit:
        while entries and len(render_entries(entries)) > char_limit:
            entries.pop()
        text = render_entries(entries)
        warning = (
            f"Trimmed to {len(entries)} entries "
            f"to stay within {char_limit} char limit."
        )

    file_path.write_text(text, encoding="utf-8")
    return warning


def handle_memory(args, **kwargs):
    """Handle the memory tool: add / remove / read operations."""
    # 一个 tool 统管 add/remove/read，通过 action 参数分发；避免工具列表冗长
    action = args.get("action", "")
    target = args.get("target", "memory")
    content = args.get("content", "")

    file_path = USER_FILE if target == "user" else MEMORY_FILE
    char_limit = USER_CHAR_LIMIT if target == "user" else MEMORY_CHAR_LIMIT

    if action == "read":
        entries = load_memory(file_path)
        if not entries:
            return f"({target} is empty)"
        return (
            f"=== {target.upper()} ({len(entries)} entries) ===\n"
            + render_entries(entries)
        )

    elif action == "add":
        if not content:
            return "(error: content is required for add)"
        entries = load_memory(file_path)
        entries.append(content)
        warning = save_memory(file_path, entries, char_limit)
        message = f"Added to {target}. Total: {len(entries)} entries."
        if warning:
            message += f" Warning: {warning}"
        return message

    elif action == "remove":
        if not content:
            return "(error: content/keyword is required for remove)"
        entries = load_memory(file_path)
        before_count = len(entries)
        keyword = content.lower()
        entries = [
            entry for entry in entries
            if keyword not in entry.lower()
        ]
        removed_count = before_count - len(entries)
        if removed_count == 0:
            return f"No entries matching '{content}' found in {target}."
        save_memory(file_path, entries, char_limit)
        return (
            f"Removed {removed_count} entries from {target}. "
            f"Remaining: {len(entries)}."
        )

    return f"(error: unknown action '{action}'. Use add/remove/read)"


registry.register(
    name="memory",
    toolset="memory",
    schema={
        "name": "memory",
        "description": (
            "Manage persistent memory across sessions. "
            "Actions: add (save a fact), remove (delete by keyword), "
            "read (list all). "
            "Targets: 'memory' (general knowledge) or 'user' (user profile). "
            "Writes take effect immediately on disk but the system prompt "
            "updates next session."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "read"],
                    "description": "Operation to perform",
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                    "description": "Which memory file to operate on",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Entry text (for add) or keyword (for remove)"
                    ),
                },
            },
            "required": ["action"],
        },
    },
    handler=handle_memory,
)


# ===========================================================================
# System prompt (s04 improved: inject memory snapshot)
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
    """Assemble system prompt with frozen memory snapshot."""
    # 和 s04 的区别：多了两段 memory 快照（MEMORY.md / USER.md）被"冻结"进 system prompt
    # "冻结"的含义：会话中 memory 写入会进磁盘，但当前对话里的 system prompt 不再变
    parts = []

    soul_path = HERMES_HOME / "SOUL.md"
    if soul_path.exists():
        parts.append(soul_path.read_text(encoding="utf-8")[:20000])
    else:
        parts.append("You are a helpful assistant.")

    memory_entries = load_memory(MEMORY_FILE)
    if memory_entries:
        parts.append("# Memory\n" + render_entries(memory_entries))

    user_entries = load_memory(USER_FILE)
    if user_entries:
        parts.append("# User Profile\n" + render_entries(user_entries))

    project = find_project_context(cwd)
    if project:
        parts.append(f"# Project Context\n{project}")

    parts.append(
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {cwd}"
    )

    return "\n\n".join(parts)


# ===========================================================================
# Core conversation loop (s06 + memory tool)
# ===========================================================================

ENABLED_TOOLSETS = ["terminal", "file", "memory"]


def run_conversation(
    user_message: str,
    conn: sqlite3.Connection,
    session_id: str,
    cached_prompt: str,
) -> dict:
    """Run a conversation loop with memory tool support."""
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

        try:
            response = active_client.chat.completions.create(
                model=active_model,
                messages=api_messages,
                tools=tools,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            classified = classify_error(status, str(exc))
            print(f"  [error] {classified['reason']} (status={status})")

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
                time.sleep(jittered_backoff(retry_count))
                continue

            raise

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

        if finish_reason == "length" and continuation_count < MAX_CONTINUATIONS:
            continuation_count += 1
            cont_msg = {"role": "user", "content": CONTINUE_MESSAGE}
            messages.append(cont_msg)
            add_message(conn, session_id, cont_msg)
            print(
                f"  [continue] {continuation_count}/{MAX_CONTINUATIONS}"
            )
            continue

        if not assistant_msg.tool_calls:
            return {
                "final_response": assistant_msg.content,
                "messages": messages,
            }

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
    print("=== s07: Memory System ===")
    print(f"Model: {MODEL} | HERMES_HOME: {HERMES_HOME}")
    print(f"Memory file: {MEMORY_FILE}")
    print(f"User file:   {USER_FILE}")
    print(f"Limits: memory={MEMORY_CHAR_LIMIT}, user={USER_CHAR_LIMIT}")

    conn = init_db(DB_PATH)
    session_id = create_session(conn)
    # Freeze memory snapshot into system prompt at session start
    cached_prompt = build_system_prompt(os.getcwd())
    print(
        f"System prompt: {len(cached_prompt)} chars "
        f"(frozen for this session)"
    )
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
