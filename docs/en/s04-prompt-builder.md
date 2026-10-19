# s04: Prompt Builder

`s00 > s01 > s02 > s03 > [ s04 ] > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The system prompt is not a hard-coded string. It is assembled layer by layer from six or seven different sources.*

## What Problem This Chapter Solves

By `s03` the agent has a tool system and session persistence.

But one question has been deferred all along: **where does the system prompt come from?**

In the s01 minimal loop the system prompt was a hard-coded string. In a real system, the agent needs to know:

- Who it is (persona)
- What the user's preferences are (memory)
- What rules the current project has (project configuration)
- What skills are available (skill index)
- What time it is (timestamp)
- How it should use tools (behavioral guidance)

This information comes from different files and runtime state. If it were all hard-coded together, every change would require a code change.

So Hermes Agent splits the system prompt into a **layered assembly**: each source is maintained independently, and they are concatenated in order at startup.

## Key Terms

### What Is SOUL.md

The persona file. Lives in the `~/.hermes/` directory. Defines the agent's identity and behavioral style.

For example:

```text
You are a concise, direct programming assistant.
Keep answers as short as possible.
Do not add a summary at the end of every reply.
```

### What Is HERMES.md / AGENTS.md

Project-level configuration files. Placed in the project directory, they tell the agent the rules for this project.

For example:

```text
This is a Python project.
Testing framework: pytest.
Code style follows PEP 8.
Do not modify the migrations/ directory.
```

### What Is Prompt Caching

Once assembled, the system prompt is cached. All API calls within the same session reuse the same copy.

Why cache? Two reasons:

1. No need to re-read files and concatenate strings every time
2. Anthropic's prompt caching requires the system prompt to stay unchanged across turns. If it changes, the cache is invalidated and costs go up

![System Prompt Six-Layer Assembly](../../illustrations/en/s04-prompt-builder/01-infographic-six-layers.png)

## Minimal Mental Model

```text
_build_system_prompt()
  |
  v
Layer 1: Persona (SOUL.md, or a default identity)
  |
  v
Layer 2: Behavioral guidance (tool usage conventions, model-specific guidance)
  |
  v
Layer 3: Memory (MEMORY.md + USER.md snapshot)
  |
  v
Layer 4: Skill index (index of installed skills)
  |
  v
Layer 5: Project configuration (HERMES.md / AGENTS.md / CLAUDE.md / .cursorrules)
  |
  v
Layer 6: Timestamp + model information
  |
  v
Concatenated into a single string, cached
```

Key point: **these layers have priority.** If both HERMES.md and AGENTS.md exist, only HERMES.md is used (higher priority). This prevents duplicate injection.

## Key Data Structures

### prompt_parts

During assembly, content from each source is collected into a list:

```python
prompt_parts = [
    "You are a programming assistant...",     # Layer 1: Persona
    "When you need to take action...",        # Layer 2: Behavioral guidance
    "# Memory\nUser preferences...",          # Layer 3: Memory
    "# Skills\nAvailable skills...",          # Layer 4: Skills
    "# Project Context\nProject rules...",    # Layer 5: Project configuration
    "Conversation started: ...",              # Layer 6: Timestamp
]
```

Finally joined with `"\n\n".join(prompt_parts)` into a single string.

### Project Configuration Priority

```text
.hermes.md / HERMES.md   (highest -- searched upward from cwd to git root)
AGENTS.md / agents.md     (current directory only)
CLAUDE.md / claude.md     (current directory only)
.cursorrules              (current directory only)
```

**Only the first one found is used.** They are not all loaded.

The purpose of this design is compatibility: projects migrating from other agent frameworks may already have a CLAUDE.md or .cursorrules. Hermes Agent uses them directly; the user doesn't need to rewrite anything.

### Per-Source Truncation

Each file is capped at 20,000 characters. Anything beyond that is truncated.

This prevents a massive AGENTS.md from consuming the entire context window.

## Minimal Implementation

### Step 1: Load the Persona

```python
def load_soul():
    soul_path = HERMES_HOME / "SOUL.md"
    if soul_path.exists():
        return soul_path.read_text()[:20000]
    return "You are a helpful assistant."
```

### Step 2: Load Project Configuration (Priority Chain)

```python
def load_project_context(cwd):
    for name in [".hermes.md", "HERMES.md"]:
        # Search upward from cwd to git root
        path = find_up(cwd, name)
        if path:
            return path.read_text()[:20000]
    
    for name in ["AGENTS.md", "CLAUDE.md", ".cursorrules"]:
        path = Path(cwd) / name
        if path.exists():
            return path.read_text()[:20000]
    
    return ""
```

### Step 3: Assemble

```python
def build_system_prompt(soul, memory, skills, project_context):
    parts = [soul]
    
    if memory:
        parts.append(f"# Memory\n{memory}")
    if skills:
        parts.append(f"# Skills\n{skills}")
    if project_context:
        parts.append(f"# Project Context\n{project_context}")
    
    parts.append(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    return "\n\n".join(parts)
```

### Step 4: Cache

```python
class AIAgent:
    def __init__(self):
        self._cached_system_prompt = None
    
    def run_conversation(self, user_message, ...):
        if self._cached_system_prompt is None:
            self._cached_system_prompt = build_system_prompt(...)
        
        # Every API call uses the same copy
        api_messages = [
            {"role": "system", "content": self._cached_system_prompt}
        ] + messages
```

Assembled once, never rebuilt afterward. Only a context compression event clears the cache and triggers a rebuild.

![Prompt Caching Strategy](../../illustrations/en/s04-prompt-builder/02-flowchart-cache-strategy.png)

## Unique Designs in Hermes Agent

### 1. Gateway Reads the Prompt from SQLite When Resuming a Session

Gateway creates a new AIAgent instance for every message. If the system prompt were reassembled each time:

- MEMORY.md may have been modified by the agent in a previous turn
- The newly assembled prompt would differ from the previous one
- Anthropic's prompt cache prefix would be invalidated

So Hermes Agent stores the system prompt in SQLite after the first assembly (see `s03`). Subsequent instances read from the cache rather than reassembling.

### 2. ephemeral_system_prompt Does Not Enter the Cache

Some system-level instructions are injected temporarily at API call time only (for example, Gateway ephemeral configuration). They are not stored in SQLite and do not enter the cache.

They are appended to the cached prompt at each API call:

```python
effective_system = cached_prompt + "\n\n" + ephemeral_prompt
```

### 3. Memory Injection Has Two Paths

- Built-in memory (MEMORY.md / USER.md) -> goes into the system prompt
- External memory providers (plugins) -> injected into the user message, not the system prompt

Why doesn't external memory go into the system prompt? Because its content may change every turn (depending on the user's question). Putting it in the system prompt would break the cache.

## Most Common Beginner Mistakes

### 1. Concatenating All Sources into One Giant Hard-Coded String

Changing anything requires a code change. Each source should be maintained independently and assembled in order.

### 2. Reassembling on Every API Call

Wastes time and breaks the prompt cache. Assemble once, cache, and reuse.

### 3. Not Truncating File Contents

A 50 KB AGENTS.md will eat a huge chunk of the context window, leaving less room for the conversation.

### 4. Loading All Project Configuration Files Instead of Only the Highest-Priority One

Loading HERMES.md, AGENTS.md, and .cursorrules all at once -- their contents may conflict or overlap.

### 5. Putting the System Prompt Inside the Messages List

The system prompt should be prepended at the time of each API call, not stored as part of the messages list in SQLite. Otherwise it gets compressed, duplicated, and persisted as a historical message.

## Teaching Boundary

What this chapter covers:

**The system prompt is assembled from multiple sources in layers. It is assembled once, cached, and reused.**

Deliberately left out:

- The full design of the memory system -> `s07`
- The logic for building the skill index -> `s08`
- The complete flow for Gateway session resumption -> `s12`
- Prompt rebuilding after context compression triggers -> `s05`

If you can achieve "the system prompt is assembled from multiple files -- changing the persona only requires editing SOUL.md, changing project rules only requires editing HERMES.md," you have completed this chapter.

## One Sentence to Remember

**The Hermes Agent system prompt is assembled from six or seven sources -- SOUL.md, memory, skills, project configuration, and more -- in priority order. It is assembled once, cached for reuse, and when Gateway resumes a session it reads from SQLite rather than reassembling.**
