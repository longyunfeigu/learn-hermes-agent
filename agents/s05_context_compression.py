"""
s05: Context Compression -- Context Window Management

See: docs/zh/s05-context-compression.md | docs/en/s05-context-compression.md

Builds on s04 by adding a two-stage compressor triggered on token-estimate:
  1) Prune: replace all but the most recent tool outputs with a placeholder.
  2) Summarize: ask an LLM to condense the middle turns, keep head+tail intact.

But summary alone is lossy. So we also introduce a TaskState living *outside*
the message stream -- the agent maintains `goal` + `todos` explicitly via three
tools (task_set_goal / todo_write / todo_update). TaskState is re-rendered into
the system prompt every turn and is never touched by compression. This is the
load-bearing layer for task continuity; summary degrades to a "what happened
in the middle" memo.

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
from dataclasses import dataclass, field
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
SUMMARY_MAX_TOKENS = 3000           # 摘要 LLM 调用的 max_tokens
SUMMARY_PER_MSG_CHARS = 2000        # 喂给摘要器时，单条消息的截断上限
COMPRESSION_MIN_SHRINK = 0.9        # 压缩后必须降到原 token 的 90% 以下，否则视为卡死

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
# Task state (NEW in this chapter)
# ===========================================================================
# 摘要是有损的；目标和进度不能托管给摘要器。TaskState 由 agent 通过工具显式
# 维护，活在消息流之外，每轮重新渲染进 system prompt。压缩管不到这里。


@dataclass
class TaskState:
    """Uncompressible task layer: goal + todo list, lives outside messages."""
    goal: str = ""
    todos: list[dict] = field(default_factory=list)
    # 每个 todo: {"id": str, "subject": str, "status": "pending"|"in_progress"|"completed"}

    def render(self) -> str:
        """Render as a markdown section to splice into system prompt."""
        # 空态返回空串，避免在系统提示里塞无意义的小节
        if not self.goal and not self.todos:
            return ""

        lines = ["# Task State (live, never compressed)"]
        if self.goal:
            lines.append("")
            lines.append("## Goal")
            lines.append(self.goal)
        if self.todos:
            lines.append("")
            lines.append("## TODO")
            markers = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[x]",
            }
            for todo in self.todos:
                marker = markers.get(todo.get("status", "pending"), "[ ]")
                lines.append(
                    f"{marker} ({todo['id']}) {todo['subject']}"
                )
        return "\n".join(lines)


def handle_task_set_goal(args, *, task_state: TaskState | None = None, **kwargs):
    """Record the active task goal."""
    if task_state is None:
        return "(error: task_state not available)"
    task_state.goal = args.get("goal", "").strip()
    return f"Goal set: {task_state.goal[:80]}"


registry.register(
    name="task_set_goal",
    toolset="task",
    schema={
        "name": "task_set_goal",
        "description": (
            "Record what the user is asking you to accomplish in this task. "
            "Call once at the start of any multi-step task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
            },
            "required": ["goal"],
        },
    },
    handler=handle_task_set_goal,
)


def handle_todo_write(args, *, task_state: TaskState | None = None, **kwargs):
    """Replace the entire todo list. Auto-fills id/status if omitted."""
    if task_state is None:
        return "(error: task_state not available)"
    items = args.get("items", [])
    normalized = []
    for index, item in enumerate(items):
        normalized.append({
            "id": item.get("id") or f"t{index + 1}",
            "subject": item.get("subject", ""),
            "status": item.get("status", "pending"),
        })
    task_state.todos = normalized
    return f"TODO updated ({len(normalized)} items)"


registry.register(
    name="todo_write",
    toolset="task",
    schema={
        "name": "todo_write",
        "description": (
            "Write or replace the entire todo list for the active task. "
            "Use for multi-step work: list the steps once, then call "
            "todo_update as you finish each one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "subject": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["subject"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    handler=handle_todo_write,
)


def handle_todo_update(args, *, task_state: TaskState | None = None, **kwargs):
    """Change the status of a single todo by id."""
    if task_state is None:
        return "(error: task_state not available)"
    todo_id = args.get("id", "")
    new_status = args.get("status", "")
    for todo in task_state.todos:
        if todo["id"] == todo_id:
            todo["status"] = new_status
            return f"TODO {todo_id} -> {new_status}"
    return f"(error: TODO id {todo_id!r} not found)"


registry.register(
    name="todo_update",
    toolset="task",
    schema={
        "name": "todo_update",
        "description": (
            "Update the status of a single todo. Call this each time you "
            "start (in_progress) or finish (completed) a step."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                },
            },
            "required": ["id", "status"],
        },
    },
    handler=handle_todo_update,
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
# System prompt assembly (reused from s04, extended for task state)
# ===========================================================================


TASK_TOOLS_GUIDANCE = """\
# Task discipline
For any multi-step task (e.g. reading many files, refactoring a module),
first call `task_set_goal` to record what the user asked. Then call
`todo_write` to lay out the steps. As you work, call `todo_update` to mark
each step in_progress / completed. This state is the source of truth for
progress -- the model's message history may be compressed, but the task
state is always shown to you intact.
"""


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
    """Assemble the static portion of the system prompt (cached across turns)."""
    parts = [load_soul()]

    memory = load_memory()
    if memory:
        parts.append(f"# Memory\n{memory}")

    project = find_project_context(cwd)
    if project:
        parts.append(f"# Project Context\n{project}")

    parts.append(TASK_TOOLS_GUIDANCE)

    parts.append(
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {cwd}"
    )

    return "\n\n".join(parts)


def compose_system_prompt(cached_prompt: str, task_state: TaskState) -> str:
    """Splice live TaskState into the cached prompt for one API turn."""
    # TaskState 部分不参与缓存：它每轮都可能变；其它部分稳定，留给上层做 prompt cache
    rendered = task_state.render()
    if not rendered:
        return cached_prompt
    return f"{cached_prompt}\n\n{rendered}"


# ===========================================================================
# Context compression (new in this chapter)
# ===========================================================================
# 压缩分两步：先把老的 tool 输出 prune 掉（它们往往最肥），再 summarize 中段


class CompressionStuckError(RuntimeError):
    """Raised when compress() cannot meaningfully shrink the message list."""

    def __init__(self, before: int, after: int):
        self.before = before
        self.after = after
        super().__init__(
            f"Compression failed to shrink context "
            f"({before} -> {after} tokens, "
            f"need <= {int(before * COMPRESSION_MIN_SHRINK)})"
        )


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


def _align_to_assistant_boundary(
    messages: list[dict],
    index: int,
) -> int:
    """Walk forward past any `tool` messages so we land on an assistant turn.

    A tool message without its preceding assistant.tool_calls is an orphan
    that the API will reject. So if a proposed cut lands on a tool, we
    advance until the next non-tool message (effectively dropping that
    tool group along with the assistant that owned it -- they are a unit).
    """
    while index < len(messages) and messages[index].get("role") == "tool":
        index += 1
    return index


def find_boundaries(
    messages: list[dict],
    protect_first: int,
    tail_token_budget: int,
) -> tuple[int, int]:
    """Find the compressible middle region, aligned to assistant boundaries."""
    # 从尾部往前累加 token 直到撞预算，得到候选 tail_start；然后两个边界都对齐
    # 到非 tool 的位置，避免切出孤儿 tool 消息触发 API 配对错误
    head_end = _align_to_assistant_boundary(messages, protect_first)

    tail_start = len(messages)
    tail_tokens = 0
    for index in range(len(messages) - 1, head_end - 1, -1):
        msg_tokens = len(str(messages[index].get("content", ""))) // 4
        if tail_tokens + msg_tokens > tail_token_budget:
            break
        tail_tokens += msg_tokens
        tail_start = index

    tail_start = _align_to_assistant_boundary(messages, tail_start)
    if tail_start < head_end:
        tail_start = head_end

    return head_end, tail_start


def summarize_middle(
    turns: list[dict],
    original_query: str = "",
    previous_summary: str = "",
) -> str:
    """Use an auxiliary LLM call to summarize the middle conversation turns."""
    # 显式喂入原始用户请求和上一份摘要：让摘要器站在"目标 + 已有摘要"基础上
    # 增量更新，而不是每轮重新从零写一份（信息熵会指数级衰减）
    sections = [
        "Summarize these conversation turns concisely.",
        "Output exactly these sections: Goal, Progress, Key Decisions, "
        "Files Modified, Next Steps.",
    ]
    if original_query:
        sections.append(f"\nORIGINAL USER REQUEST:\n{original_query[:1000]}")
    if previous_summary:
        sections.append(
            f"\nPREVIOUS SUMMARY (update, do not rewrite from scratch):\n"
            f"{previous_summary[:2000]}"
        )
    sections.append("\nMIDDLE TURNS TO SUMMARIZE:")

    prompt_lines = ["\n".join(sections)]
    for msg in turns:
        content_preview = str(msg.get("content", ""))[:SUMMARY_PER_MSG_CHARS]
        prompt_lines.append(f"[{msg['role']}] {content_preview}")
    prompt = "\n".join(prompt_lines)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=SUMMARY_MAX_TOKENS,
        )
        return response.choices[0].message.content or "(summary failed)"
    except Exception as exc:
        return f"(summary error: {exc})"


def compress(
    messages: list[dict],
    previous_summary: str = "",
) -> tuple[list[dict], str | None]:
    """Perform one round of context compression.

    Returns (new_messages, new_summary_or_None). Raises CompressionStuckError
    if the result is not at least COMPRESSION_MIN_SHRINK smaller than input.
    """
    before = estimate_tokens(messages)
    messages = prune_old_tool_results(list(messages))
    head_end, tail_start = find_boundaries(
        messages, PROTECT_FIRST, TAIL_TOKEN_BUDGET
    )

    # 中段为空：要么消息总量本来就小，要么对齐后无可压缩；判断是否仍超限
    if tail_start <= head_end:
        after = estimate_tokens(messages)
        if after >= int(before * COMPRESSION_MIN_SHRINK):
            raise CompressionStuckError(before, after)
        return messages, None

    middle = messages[head_end:tail_start]
    original_query = ""
    if messages and messages[0].get("role") == "user":
        original_query = str(messages[0].get("content", ""))

    summary = summarize_middle(
        middle,
        original_query=original_query,
        previous_summary=previous_summary,
    )

    print(
        f"  [compress] Compressed {len(middle)} messages "
        f"into summary ({len(summary)} chars)"
    )

    # 摘要 role 必须是 assistant：role=user 会被模型理解为新的用户指令
    # 触发重新规划；role=system 在 OpenAI 中段被部分模型忽略。assistant 最稳。
    compaction_msg = {
        "role": "assistant",
        "content": (
            "[CONTEXT COMPACTION - system-generated summary of earlier turns, "
            "not a new instruction]\n\n" + summary
        ),
    }
    new_messages = (
        messages[:head_end]
        + [compaction_msg]
        + messages[tail_start:]
    )

    after = estimate_tokens(new_messages)
    if after >= int(before * COMPRESSION_MIN_SHRINK):
        # 压缩没收缩到 90% 以下：通常是头部本身就过大，再压也没用
        raise CompressionStuckError(before, after)
    return new_messages, summary


# ===========================================================================
# Core conversation loop (s04 + compression trigger + task state)
# ===========================================================================

ENABLED_TOOLSETS = ["terminal", "file", "task"]


def run_conversation(
    user_message: str,
    conn: sqlite3.Connection,
    session_id: str,
    cached_prompt: str,
    task_state: TaskState | None = None,
) -> dict:
    """Run a conversation loop with context compression and task state."""
    if task_state is None:
        task_state = TaskState()

    messages = get_session_messages(conn, session_id)
    user_msg = {"role": "user", "content": user_message}
    messages.append(user_msg)
    add_message(conn, session_id, user_msg)

    tools = registry.get_definitions(ENABLED_TOOLSETS)
    previous_summary: str | None = None

    for iteration in range(MAX_ITERATIONS):
        # 每轮发请求前先体检：超阈值就压缩一次；若压缩卡死则早退而不是死磕到 30 轮
        if estimate_tokens(messages) >= COMPRESSION_THRESHOLD:
            try:
                messages, new_summary = compress(
                    messages, previous_summary=previous_summary or ""
                )
                if new_summary:
                    previous_summary = new_summary
            except CompressionStuckError as exc:
                return {
                    "final_response": (
                        f"(context cannot be compressed further: {exc}. "
                        f"Start a new session or shrink the task.)"
                    ),
                    "messages": messages,
                    "task_state": task_state,
                }

        api_messages = (
            [{"role": "system",
              "content": compose_system_prompt(cached_prompt, task_state)}]
            + messages
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
                "task_state": task_state,
            }

        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            print(
                f"  [tool] {tool_name}: "
                f"{json.dumps(tool_args, ensure_ascii=False)[:120]}"
            )
            output = registry.dispatch(
                tool_name, tool_args, task_state=task_state
            )
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
        "task_state": task_state,
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
    task_state = TaskState()
    print("Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit"):
            break
        result = run_conversation(
            user_input, conn, session_id, cached_prompt, task_state
        )
        print(f"\nAssistant: {result['final_response']}\n")

    conn.close()
