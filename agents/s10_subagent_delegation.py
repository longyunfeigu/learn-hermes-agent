"""
s10: Subagent Delegation -- Child Agent Task Delegation

Builds on s09 with a `delegate_task` tool that spawns a child agent in an
isolated message list. The child runs its own loop (with a smaller iteration
budget), then returns only its final text to the parent — intermediate tool
noise never pollutes the parent's context. Child is denied the delegating /
memory-writing tools to prevent recursion and side-effect leakage.

Usage:
    export OPENAI_API_KEY=sk-xxx
    python agents/s10_subagent_delegation.py
"""

import json
import os
import random
import re
import shutil
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

    def get_tool_names(
        self,
        enabled_toolsets: list[str] | None = None,
    ) -> list[str]:
        """Return tool names, optionally filtered by toolset."""
        return [
            entry.name
            for entry in self._tools.values()
            if not enabled_toolsets or entry.toolset in enabled_toolsets
        ]


registry = ToolRegistry()


# ===========================================================================
# Dangerous command detection and approval (reused from s09)
# ===========================================================================

DANGEROUS_PATTERNS = [
    (
        r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*--no-preserve-root)",
        "Recursive/force file deletion",
    ),
    (r"rm\s+-[a-zA-Z]*r", "Recursive file deletion"),
    (r"mkfs\.", "Filesystem format"),
    (r"dd\s+if=", "Raw disk write"),
    (r">\s*/dev/sd[a-z]", "Direct device write"),
    (r"chmod\s+(-R\s+)?777", "World-writable permissions"),
    (r"chown\s+-R\s+", "Recursive ownership change"),
    (r"shutdown|reboot|poweroff|init\s+[06]", "System shutdown/reboot"),
    (r"kill\s+-9\s+(-1|1\b)", "Kill all processes"),
    (r":\(\)\s*\{\s*:\|\s*:\s*&\s*\}\s*;", "Fork bomb"),
    (r"DROP\s+(TABLE|DATABASE|INDEX)", "SQL destructive"),
    (r"TRUNCATE\s+TABLE", "SQL truncate"),
    (r"DELETE\s+FROM\s+\w+\s*;?\s*$", "SQL delete without WHERE"),
    (r"curl\s+.*\|\s*(bash|sh|zsh)", "Pipe remote script to shell"),
    (r"wget\s+.*\|\s*(bash|sh|zsh)", "Pipe remote script to shell"),
]

_compiled_patterns = [
    (re.compile(pattern, re.IGNORECASE), description)
    for pattern, description in DANGEROUS_PATTERNS
]
_session_approved: set[int] = set()
_ALLOWLIST_FILE = HERMES_HOME / "allowlist.json"


def _load_allowlist() -> set[str]:
    """Load the permanent allowlist."""
    if _ALLOWLIST_FILE.exists():
        try:
            return set(
                json.loads(_ALLOWLIST_FILE.read_text(encoding="utf-8"))
            )
        except Exception:
            pass
    return set()


def _save_allowlist(allowlist: set[str]):
    """Save the permanent allowlist to disk."""
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    _ALLOWLIST_FILE.write_text(
        json.dumps(sorted(allowlist)),
        encoding="utf-8",
    )


_permanent_allowlist: set[str] = _load_allowlist()


def detect_dangerous_command(
    command: str,
) -> list[tuple[int, str, str]]:
    """Detect if a command matches dangerous patterns."""
    matches = []
    for index, (regex, description) in enumerate(_compiled_patterns):
        if regex.search(command):
            matches.append((
                index,
                DANGEROUS_PATTERNS[index][0],
                description,
            ))
    return matches


def approve_command(
    command: str,
    matches: list[tuple[int, str, str]],
) -> bool:
    """Prompt the user to approve a dangerous command."""
    global _permanent_allowlist

    unapproved = [
        (index, pattern_str, description)
        for index, pattern_str, description in matches
        if index not in _session_approved
        and pattern_str not in _permanent_allowlist
    ]
    if not unapproved:
        return True

    print(f"\n  *** DANGEROUS COMMAND ***\n  Command: {command}")
    for _, _, description in unapproved:
        print(f"  - {description}")
    print("  [o]nce / [s]ession / [a]lways / [d]eny")

    choice = input("  Approve? ").strip().lower()

    if choice in ("o", "once"):
        return True

    if choice in ("s", "session"):
        for index, _, _ in unapproved:
            _session_approved.add(index)
        return True

    if choice in ("a", "always"):
        for _, pattern_str, _ in unapproved:
            _permanent_allowlist.add(pattern_str)
        _save_allowlist(_permanent_allowlist)
        for index, _, _ in unapproved:
            _session_approved.add(index)
        return True

    return False


# ===========================================================================
# Tool implementations
# ===========================================================================


def run_terminal(args, **kwargs):
    """Terminal tool handler with dangerous command detection."""
    command = args.get("command", "")

    matches = detect_dangerous_command(command)
    if matches and not approve_command(command, matches):
        return json.dumps({"error": "Command denied by user."})

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
    handler=run_terminal,
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
    return sum(len(str(msg.get("content", ""))) for msg in messages) // 4


def compress(messages: list[dict]) -> list[dict]:
    """Perform one round of context compression."""
    tool_indices = [
        index for index, msg in enumerate(messages)
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
# Memory system (reused from s07, simplified)
# ===========================================================================

MEMORY_DIR = HERMES_HOME / "memories"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"
USER_FILE = MEMORY_DIR / "USER.md"
ENTRY_SEP = "\n\n\u00a7\n\n"
MEMORY_CHAR_LIMIT = 2200
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

    if len(text) > char_limit:
        while entries and len(render_entries(entries)) > char_limit:
            entries.pop()
        text = render_entries(entries)
        warning = f"Trimmed to {len(entries)} entries."

    file_path.write_text(text, encoding="utf-8")
    return warning


def handle_memory(args, **kwargs):
    """Handle the memory tool: add / remove / read operations."""
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
            return "(error: content required)"
        entries = load_memory(file_path)
        entries.append(content)
        warning = save_memory(file_path, entries, char_limit)
        message = f"Added to {target}. Total: {len(entries)}."
        if warning:
            message += f" {warning}"
        return message

    elif action == "remove":
        if not content:
            return "(error: keyword required)"
        entries = load_memory(file_path)
        before_count = len(entries)
        entries = [
            entry for entry in entries
            if content.lower() not in entry.lower()
        ]
        if before_count == len(entries):
            return f"No match for '{content}'."
        save_memory(file_path, entries, char_limit)
        removed_count = before_count - len(entries)
        return (
            f"Removed {removed_count}. Remaining: {len(entries)}."
        )

    return f"(error: unknown action '{action}')"


registry.register(
    name="memory",
    toolset="memory",
    schema={
        "name": "memory",
        "description": (
            "Manage persistent memory. Actions: add/remove/read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "read"],
                },
                "target": {
                    "type": "string",
                    "enum": ["memory", "user"],
                },
                "content": {
                    "type": "string",
                },
            },
            "required": ["action"],
        },
    },
    handler=handle_memory,
)


# ===========================================================================
# Skill system (reused from s08, simplified)
# ===========================================================================

SKILLS_DIR = HERMES_HOME / "skills"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse SKILL.md frontmatter and body."""
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    metadata = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()

    return metadata, parts[2].strip()


def _render_skill(name: str, description: str, body: str) -> str:
    """Render frontmatter + body into SKILL.md content."""
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


def discover_skills() -> list[dict]:
    """Scan the skills directory and return a list of skill summaries."""
    if not SKILLS_DIR.exists():
        return []

    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        metadata, _ = _parse_frontmatter(
            skill_file.read_text(encoding="utf-8")
        )
        skills.append({
            "name": metadata.get("name", skill_dir.name),
            "description": metadata.get("description", ""),
        })

    return skills


def handle_skill_view(args, **kwargs):
    """Load and return the full content of a skill by name."""
    skill_file = SKILLS_DIR / args.get("name", "") / "SKILL.md"
    if not skill_file.exists():
        return "(error: skill not found)"

    metadata, body = _parse_frontmatter(
        skill_file.read_text(encoding="utf-8")
    )
    return (
        f"=== Skill: {metadata.get('name', '')} ===\n"
        f"{metadata.get('description', '')}\n\n{body}"
    )


def handle_skill_manage(args, **kwargs):
    """Manage skills: create / edit / delete."""
    action = args.get("action", "")
    name = args.get("name", "")

    if not name:
        return "(error: name required)"

    skill_dir = SKILLS_DIR / name
    skill_file = skill_dir / "SKILL.md"

    if action == "create":
        if skill_file.exists():
            return "(error: exists)"
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = _render_skill(
            name,
            args.get("description", ""),
            args.get("body", ""),
        )
        skill_file.write_text(content, encoding="utf-8")
        return f"Created '{name}'."

    elif action == "edit":
        if not skill_file.exists():
            return "(error: not found)"
        metadata, old_body = _parse_frontmatter(
            skill_file.read_text(encoding="utf-8")
        )
        new_description = (
            args.get("description")
            or metadata.get("description", "")
        )
        new_body = args.get("body") or old_body
        content = _render_skill(name, new_description, new_body)
        skill_file.write_text(content, encoding="utf-8")
        return f"Updated '{name}'."

    elif action == "delete":
        if not skill_file.exists():
            return "(error: not found)"
        shutil.rmtree(skill_dir)
        return f"Deleted '{name}'."

    return "(error: unknown action)"


registry.register(
    name="skill_view",
    toolset="skill",
    schema={
        "name": "skill_view",
        "description": "Load full skill content.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    handler=handle_skill_view,
)

registry.register(
    name="skill_manage",
    toolset="skill",
    schema={
        "name": "skill_manage",
        "description": "Manage skills: create/edit/delete.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "edit", "delete"],
                },
                "name": {"type": "string"},
                "description": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["action", "name"],
        },
    },
    handler=handle_skill_manage,
)


# ===========================================================================
# System prompt
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
    """Assemble the full system prompt."""
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

    skills = discover_skills()
    if skills:
        lines = [
            f"- **{skill['name']}**: {skill['description']}"
            for skill in skills
        ]
        parts.append("# Available Skills\n" + "\n".join(lines))

    parts.append(
        "# Permissions\n"
        "Dangerous commands require user approval."
    )

    project = find_project_context(cwd)
    if project:
        parts.append(f"# Project Context\n{project}")

    parts.append(
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {cwd}"
    )

    return "\n\n".join(parts)


# ===========================================================================
# Subagent delegation (new in this chapter)
# ===========================================================================
# 子代理的三条隔离约束：
#   1) 消息列表独立（父不看子的探索过程，只拿最终文本）
#   2) 工具白名单裁剪：去掉 delegate_task（防无穷递归）/memory/skill_manage（防副作用外溢）
#   3) 独立较小的迭代预算，避免子任务拖垮整体

# 禁用给子代理的工具：delegate_task 防递归；memory/skill_manage 防写入污染全局状态
DELEGATE_BLOCKED_TOOLS = {"delegate_task", "memory", "skill_manage"}
MAX_CHILD_ITERATIONS = 15


def build_child_agent(
    goal: str,
    context: str,
    toolsets: list[str],
) -> dict:
    """Build a child agent environment: isolated messages, restricted tools."""
    # 从父 registry 同一个工具池里取，但按黑名单过滤 —— 子代理和父代理共享 registry 但不共享权限
    child_tools = []
    for tool_def in registry.get_definitions(toolsets):
        function_name = tool_def["function"]["name"]
        if function_name not in DELEGATE_BLOCKED_TOOLS:
            child_tools.append(tool_def)

    # 子代理的 system prompt 是一次性的、任务专属的；不继承父的 SOUL/MEMORY
    # 显式告诉它"不要再 delegate、不要改 memory/skills"——双保险（代码层也拦截）
    child_prompt = (
        "You are a focused sub-agent. "
        "Complete the assigned task and report results.\n"
        "Do NOT delegate further. "
        "Do NOT modify memory or skills.\n\n"
        f"# Task\n{goal}\n\n"
    )
    if context:
        child_prompt += f"# Context\n{context}\n\n"

    child_prompt += (
        f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Working directory: {os.getcwd()}"
    )

    child_messages = [{"role": "user", "content": goal}]

    return {
        "system_prompt": child_prompt,
        "messages": child_messages,
        "tools": child_tools,
    }


def run_child_conversation(child_env: dict) -> str:
    """Run the child agent's conversation loop and return the final response."""
    messages = child_env["messages"]
    tools = child_env["tools"]
    system_prompt = child_env["system_prompt"]
    active_client = client
    active_model = MODEL

    for iteration in range(MAX_CHILD_ITERATIONS):
        api_messages = (
            [{"role": "system", "content": system_prompt}] + messages
        )

        try:
            response = active_client.chat.completions.create(
                model=active_model,
                messages=api_messages,
                tools=tools if tools else None,
            )
        except Exception as exc:
            return f"(child agent error: {exc})"

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
            return assistant_msg.content or "(child returned empty response)"

        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name

            # 双保险：即便某个禁用工具意外出现在 child_tools 里，这里再拦一次
            if tool_name in DELEGATE_BLOCKED_TOOLS:
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": (
                        f"(error: tool '{tool_name}' is not "
                        f"available to sub-agents)"
                    ),
                }
            else:
                tool_args = json.loads(tool_call.function.arguments)
                print(
                    f"    [child-tool] {tool_name}: "
                    f"{json.dumps(tool_args, ensure_ascii=False)[:100]}"
                )
                output = registry.dispatch(tool_name, tool_args)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output,
                }
            messages.append(tool_msg)

    return "(child agent: max iterations reached)"


def handle_delegate(args, **kwargs):
    """Handle the delegate_task tool: spawn a child agent for a focused task."""
    # 父 agent 的视角：这个函数看起来就是一条普通 tool 调用，输入任务，返回文本
    # 所有子代理的"来回折腾"都被封在这里，父的 messages 只多一条 tool 结果
    goal = args.get("goal", "")
    context = args.get("context", "")
    toolsets = args.get("toolsets", ["terminal", "file"])

    if not goal:
        return "(error: goal is required)"

    print(f"  [delegate] Starting child agent for: {goal[:80]}")

    child_env = build_child_agent(goal, context, toolsets)
    result = run_child_conversation(child_env)

    print(f"  [delegate] Child agent finished ({len(result)} chars)")
    return result


registry.register(
    name="delegate_task",
    toolset="delegate",
    schema={
        "name": "delegate_task",
        "description": (
            "Delegate a focused task to a sub-agent with its own "
            "isolated context. The sub-agent has access to specified "
            "tools but cannot delegate further, modify memory, or "
            "manage skills. Returns only the final result text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "Clear description of the task to accomplish"
                    ),
                },
                "context": {
                    "type": "string",
                    "description": (
                        "Relevant context the sub-agent needs"
                    ),
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Tool sets available to the sub-agent "
                        "(default: terminal, file)"
                    ),
                },
            },
            "required": ["goal"],
        },
    },
    handler=handle_delegate,
)


# ===========================================================================
# Core conversation loop (s09 + delegate toolset)
# ===========================================================================

ENABLED_TOOLSETS = ["terminal", "file", "memory", "skill", "delegate"]


def run_conversation(
    user_message: str,
    conn: sqlite3.Connection,
    session_id: str,
    cached_prompt: str,
) -> dict:
    """Run a conversation loop with subagent delegation support."""
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
    print("=== s10: Subagent Delegation ===")
    print(f"Model: {MODEL} | HERMES_HOME: {HERMES_HOME}")
    print(
        f"Max parent iterations: {MAX_ITERATIONS} | "
        f"Max child iterations: {MAX_CHILD_ITERATIONS}"
    )
    print(f"Blocked tools for children: {DELEGATE_BLOCKED_TOOLS}")

    conn = init_db(DB_PATH)
    session_id = create_session(conn)
    cached_prompt = build_system_prompt(os.getcwd())
    print(f"System prompt: {len(cached_prompt)} chars")
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
