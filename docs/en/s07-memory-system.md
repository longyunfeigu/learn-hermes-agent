# s07: Memory System

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > [ s07 ] > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Not everything belongs in memory; only information that remains valuable across sessions is worth keeping.*

## What problem does this chapter solve

If an agent starts completely from scratch every new session, it keeps forgetting things like:

- What code style the user prefers
- Mistakes the user has corrected multiple times
- Project conventions that are not obvious from the code itself
- Where certain external resources can be found

This makes the system feel like "every interaction is a first meeting."

That is why memory is needed.

## But first, a boundary: memory is not for storing everything

This is where this chapter is most easily led astray.

Memory is not "write down everything useful." If you do that, two problems appear quickly:

1. Memory becomes a junk drawer, increasingly messy over time
2. The agent starts relying on stale memories instead of reading the current ground truth

So this chapter must establish a principle first:

**Only information that remains valuable across sessions and cannot be easily inferred from the current project state belongs in memory.**

![MEMORY.md vs USER.md](../../illustrations/en/s07-memory-system/01-comparison-memory-types.png)

## Key terms explained

### What is MEMORY.md

The agent's working notebook. When injected into the system prompt, it is headed:

```text
MEMORY (your personal notes) [62% -- 1,364/2,200 chars]
```

It stores information the agent has learned during its work **about the environment and project**. Not about who the user is, but about "what this working environment looks like."

Concrete examples:

```text
$ Project uses pytest, not unittest. Run tests with pytest -x for fail-fast
$ This machine is macOS ARM; Homebrew path is /opt/homebrew
$ Auth module rewrite is driven by compliance, not tech debt
$ CI config is at .github/workflows/ci.yml; must pass lint before merge
$ Do not use asyncio.run(); this project has a persistent event loop, use bridge_async()
```

In one sentence: **MEMORY.md records "how this project / environment works."**

### What is USER.md

The user profile. When injected into the system prompt, it is headed:

```text
USER PROFILE (who the user is) [48% -- 660/1,375 chars]
```

It stores information the agent has learned **about the user personally**. Not about the project, but about "who this person is, what they like, and what they dislike."

Concrete examples:

```text
$ Name is Zhang San, backend engineer, 10 years of Go, 2 years of Python
$ Hates mock tests -- last time mocks diverged from production and caused an outage
$ Keep answers concise; do not add a summary of what was just done at the end
$ Prefers tabs for indentation, snake_case for variables
$ Timezone UTC+8, typical working hours 10:00-22:00
```

In one sentence: **USER.md records "who this person is and how to collaborate with them smoothly."**

### Why two separate files

In the source code, both files are operated through the same `memory` tool, distinguished by the `target` parameter:

```python
# Write to MEMORY.md
memory(action="add", target="memory", content="Project uses pytest for testing")

# Write to USER.md
memory(action="add", target="user", content="User prefers tabs for indentation")
```

The core reason for the split is **different lifecycles**:

| | MEMORY.md | USER.md |
|---|---|---|
| About whom | Project and environment | The user personally |
| Character limit | 2,200 | 1,375 |
| When switching projects | Mostly needs to be rebuilt | Directly reusable |
| When switching users | Mostly still useful | Needs to be rebuilt |

For example: when you switch from Project A to Project B, USER.md entries like "user prefers tabs" and "keep answers concise" still hold. But MEMORY.md entries like "project uses pytest" might be wrong -- the new project uses vitest.

The Hermes Agent Profile system (`s11`) gives each profile its own `memories/` directory, so both files can be independent when switching profiles.

### A simple rule for deciding which file to use

Ask yourself: **"If I switched to a completely different project, would this piece of information still be useful?"**

- Yes -> USER.md (because it describes the user, not the project)
- No -> MEMORY.md (because it describes the current environment)

Edge case: "User hates mock tests" -> store in USER.md. Although it relates to testing, it describes a **user preference** that holds regardless of project.

### What is a "frozen snapshot"

Hermes Agent reads MEMORY.md and USER.md at the start of a session and freezes them as part of the system prompt.

**Mid-session changes to memory are written to disk immediately, but they do not alter the current session's system prompt.**

Why? Because changing the system prompt would break Anthropic's prompt cache. New memories take effect when the next session starts.

## What to store and what not to store

This matters more than "how to implement it."

### What to store

| Type | Example |
|---|---|
| User preferences | "Prefers tabs for indentation," "Keep answers concise" |
| User corrections | "Do not mock the database; use a real test database" |
| Project conventions | "The auth rewrite is driven by compliance, not tech debt" |
| External resources | "Bug tracking is in the INGEST project on Linear" |

### What NOT to store

| Do not store | Why |
|---|---|
| File structure, function signatures, directory layout | Can be rediscovered by reading the code |
| Current task progress | This is a task / plan, not memory |
| Current branch name, current PR number | Goes stale quickly |
| Specific code for fixing a bug | The code and commit history are the accurate source |
| Secrets, passwords | Security risk |

This boundary must hold firm. Otherwise memory shifts from "helping the system get smarter over time" to "helping the system hallucinate over time."

## Minimal mental model

```text
Session 1: User says "I hate mock tests"
   |
   v
Agent calls the memory tool, writes to MEMORY.md
   |
   v
Session ends; MEMORY.md is on disk

------ time passes ------

Session 2 starts
   |
   v
Read MEMORY.md -> freeze as part of the system prompt
   |
   v
Agent knows not to use mocks -> writes real tests directly
```

Key point: **Writing is immediate (disk), but taking effect is deferred (next session).** This design protects the prompt cache.

## Key data structures

### 1. Memory entry

Hermes Agent's memory is not a structured database. It is simply entries in a markdown file, delimited by `$`:

```text
$ User prefers tabs over spaces for indentation
$ Project uses pytest, not unittest. Run with `pytest -x` for fail-fast
$ Auth rewrite is driven by legal/compliance, not tech debt
```

Each entry is a single sentence or short paragraph. Simple, readable, and directly readable/writable by the agent.

### 2. Character limit

MEMORY.md defaults to a maximum of 2200 characters. USER.md defaults to a maximum of 1375 characters.

Why so tight? Because memory is injected into the system prompt for every session. If memory grows without bound, it eats more and more of the context window.

When space runs low, the agent must decide which old entries to remove to make room. This forces the agent to keep memory concise.

### 3. Frozen snapshot

```python
snapshot = {
    "memory": "$ User prefers tabs...\n$ Project uses pytest...",
    "user": "$ Senior engineer, prefers concise answers...",
}
```

Generated when the session starts and never changed afterward. Tool calls return the real-time state from disk, but the system prompt uses the frozen snapshot.

## Minimal implementation

### Step 1: Define the storage format

```python
ENTRY_DELIMITER = "$"

def parse_entries(text):
    return [e.strip() for e in text.split(ENTRY_DELIMITER) if e.strip()]

def render_entries(entries):
    return "\n".join(f"{ENTRY_DELIMITER} {e}" for e in entries)
```

### Step 2: Read and write to disk

```python
def load_memory(path):
    if not path.exists():
        return []
    return parse_entries(path.read_text())

def save_memory(path, entries):
    path.write_text(render_entries(entries))
```

### Step 3: Provide the memory tool

Minimal parameters: `action` (add / replace / remove / read) + `content`.

```python
def handle_memory(action, content=None, target="memory"):
    entries = load_memory(path_for(target))
    
    if action == "add":
        entries.append(content)
        # If over the character limit, require the agent to clean up
        save_memory(path_for(target), entries)
        return f"Added. {len(entries)} entries, {char_count} chars."
    
    if action == "remove":
        # Use substring matching to find the entry to delete
        entries = [e for e in entries if content not in e]
        save_memory(path_for(target), entries)
        return f"Removed. {len(entries)} entries remaining."
    
    if action == "read":
        return render_entries(entries)
```

### Step 4: Freeze the snapshot when the session starts

```python
# Inside _build_system_prompt()
memory_block = memory_store.format_for_system_prompt("memory")
user_block = memory_store.format_for_system_prompt("user")
if memory_block:
    prompt_parts.append(memory_block)
if user_block:
    prompt_parts.append(user_block)
```

This step connects with `s04` (prompt assembly). Memory is one of the sources for the system prompt.

## Hermes Agent's unique design choices here

### 1. Frozen snapshot + real-time disk

Most agents' memory takes effect immediately after modification. Hermes Agent deliberately separates two layers:

- Disk writes are immediate (durable)
- System prompt injection is frozen (stable)

This is for prompt caching. If the system prompt were updated every time memory changes, Anthropic's cache prefix would be invalidated and the full prompt would need to be re-sent on every API call.

### 2. File locking

In a Gateway scenario, multiple sessions may write to MEMORY.md simultaneously. Hermes Agent uses file locking (`fcntl.flock`) to ensure atomicity.

### 3. External memory providers

Beyond the built-in MEMORY.md / USER.md, Hermes Agent also supports plugging in external memory providers (such as vector databases) via plugins.

External memory content does not go into the system prompt (that would break caching). Instead, it is injected into user messages. This keeps the system prompt stable while external memory's dynamic content takes a separate path.

### 4. Periodic memory reminders (two trigger mechanisms)

Hermes Agent has two independent memory trigger mechanisms addressing different scenarios:

#### Mechanism A: Periodic background review (nudge)

```python
self._memory_nudge_interval = 10   # Trigger every 10 user turns by default
self._turns_since_memory = 0       # Counter
```

Every time the user sends a message, the counter increments by 1. When it reaches `nudge_interval`:

```text
User turn 1 -> counter 1
User turn 2 -> counter 2
...
User turn 10 -> counter 10 -> triggered! Counter resets to zero
```

After triggering, the system creates an independent "review agent" in a background thread **after the response has already been returned to the user**:

```python
# In the background thread
review_agent = AIAgent(
    model=self.model,
    max_iterations=8,       # Only 8 turns; a quick review
    quiet_mode=True,        # Completely silent; no user-visible output
)
review_agent._memory_store = self._memory_store    # Shares the same memory store
review_agent._memory_nudge_interval = 0            # Review agent does not trigger nudges itself

review_agent.run_conversation(
    user_message=MEMORY_REVIEW_PROMPT,              # Review prompt
    conversation_history=messages_snapshot,          # Snapshot of the current conversation
)
```

The review prompt looks like this:

```text
Review the conversation above and consider saving to memory if appropriate.

Focus on:
1. Has the user revealed things about themselves -- their persona, desires,
   preferences, or personal details worth remembering?
2. Has the user expressed expectations about how you should behave, their
   work style, or ways they want you to operate?

If something stands out, save it using the memory tool.
If nothing is worth saving, just say 'Nothing to save.' and stop.
```

Key design decisions:

- **Runs after the response** -- does not compete with the user's main task for model attention
- **Independent agent** -- stdout/stderr are redirected to /dev/null; completely invisible to the user
- **Shared memory store** -- memory written by the review agent is persisted to disk immediately
- **Limited to 8 turns** -- the review is a quick scan, not a deep analysis

#### Mechanism B: Pre-compression emergency flush

When a conversation is about to be compressed (`s05`) or a session is about to be reset, the system performs an "emergency memory save":

```python
self._memory_flush_min_turns = 6   # Only trigger flush after at least 6 user turns
```

A flush works differently from a nudge -- it is not a background review but a **message injected directly into the current conversation**:

```python
flush_content = (
    "[System: The session is being compressed. "
    "Save anything worth remembering -- prioritize user preferences, "
    "corrections, and recurring patterns over task-specific details.]"
)
```

After seeing this message, the model calls the memory tool directly within the current context to save information. Once saving is complete, the system removes all flush-related messages from the history (leaving no trace).

#### Division of labor between the two mechanisms

| | Periodic nudge | Pre-compression flush |
|---|---|---|
| When triggered | Every N user turns | Before compression / session reset |
| How it runs | Background thread, independent agent | Current conversation, injected message |
| User awareness | Completely invisible | Completely invisible (messages removed after) |
| Default threshold | 10 turns | 6 turns |
| Purpose | Routine accumulation | Last chance to prevent loss |
| Config key | `memory.nudge_interval` | `memory.flush_min_turns` |

## Boundaries between memory, session, SOUL.md, and HERMES.md

| | memory | session | SOUL.md | HERMES.md |
|---|---|---|---|---|
| What it is | Curated knowledge across sessions | Complete record of one conversation | Persona definition | Project rules |
| Who writes it | Agent | System (automatic) | User | Developer |
| How often it changes | Frequently | Every conversation | Rarely | Fixed per project |
| Size | Small (limited) | Large (full history) | Small | Medium |

## Common beginner mistakes

### 1. Storing code structure in memory

"This project has src/ and tests/" -- should not be stored; the system can re-read the filesystem.

### 2. Storing current task progress in memory

"I am currently modifying the auth module" -- this is a task / plan, not memory.

### 3. Treating memory as absolute truth

Memory can go stale. Use it for direction, not as a substitute for current observation. If memory conflicts with current code, trust the ground truth in front of you.

### 4. Not setting a character limit

If memory grows without bound, the system prompt keeps expanding and eats up the context window.

### 5. Expecting mid-session memory changes to take effect immediately

Under the frozen snapshot model, changes take effect in the next session. This is by design, not a bug.

## Teaching boundaries

The most important thing in this chapter is not how automatic or sophisticated memory can eventually become, but establishing clear storage boundaries first:

- What is worth keeping across sessions
- What is merely current task state and should not go into memory
- What each of memory, session, SOUL.md, and HERMES.md is responsible for

Deliberately deferred: the full plugin architecture for external memory providers, vector database integration, automatic memory consolidation and deduplication strategies.

If the reader can get the agent to "remember user preferences from a previous session when starting a new one," this chapter has achieved its goal.

## After finishing this chapter, you should be able to answer

- Why should memory not store "everything"?
- Why are MEMORY.md and USER.md kept separate?
- What kind of information is appropriate for cross-session storage? What is not?
- Why do mid-session memory changes not immediately affect the system prompt?
- What are the boundaries between memory, session, SOUL.md, and HERMES.md?

---

**One line to remember: Memory stores information that "may still be valuable in the future but cannot easily be re-derived from the current codebase." Hermes Agent uses frozen snapshots to protect the prompt cache -- writes are immediate but take effect on a delay.**
