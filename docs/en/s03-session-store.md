# s03: Session Store

`s00 > s01 > s02 > [ s03 ] > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Exit the program and the conversation is gone. Two platforms send messages at the same time in Gateway mode and file locks collide.*  
> This chapter solves both problems with SQLite.

## What Problem This Chapter Solves

By `s02` the agent already has a complete tool registration and dispatch system.

But there is a fatal flaw: `messages` live only in memory. When the process exits, everything resets to zero.

This is unacceptable even for single-user CLI -- exit and the conversation is gone; `--continue` to resume the last session is impossible. In Gateway mode the problem is worse -- messages from multiple platforms arrive concurrently, and those concurrent conversations need to:

1. Read the previous conversation history (otherwise every turn starts from scratch)
2. Write to the same database concurrently without write-lock conflicts (different sessions don't share data, but they write to the same database file, and SQLite has a single write lock for the entire database)
3. Support searching historical sessions after the fact

A file-system approach (one JSON file per session) solves point 1; point 2 is a non-issue since files are naturally isolated, though you lose transactional guarantees; point 3 requires scanning every file.

That is why Hermes Agent chose SQLite. Not because "SQLite is fancier than files," but because it solves all three problems at once.

## Key Terms

### What Is a Session

A `session` is one complete conversation.

It has a start time, an end time, and a unique ID. All messages in the conversation belong to this session.

In CLI mode, from the moment you launch to the moment you exit is one session.  
In Gateway mode, the continuous conversation within a single chat window is one session.

![SQLite Default vs WAL Mode](../../illustrations/en/s03-session-store/01-comparison-wal.png)

### What Is WAL Mode

WAL is a SQLite journaling mode (Write-Ahead Logging). Enabling it takes one line:

```python
conn.execute("PRAGMA journal_mode=WAL")
```

**First, the problem: why is WAL needed?**

Under SQLite's default mode, when someone is writing to the database, nobody else can even read:

```text
Telegram adapter is writing a message -> entire database is locked
                                           |
Discord adapter wants to read history  -> X  blocked -- can't even read
```

Fine for single-user CLI, but in Gateway mode with multiple platforms sending and receiving simultaneously, this causes stalls.

**How WAL solves it:**

With WAL enabled, writes go to a temporary journal file first without touching the main database. Reads continue to hit the main database file, unaffected:

```text
Telegram adapter is writing a message -> writes to the WAL journal (main database untouched)
                                           |
Discord adapter wants to read history  -> OK  reads from the main database
```

The journal is automatically merged back into the main database at the right time.

But note: **writes still queue behind each other.** If two adapters try to write at the same time, one has to wait for the other to finish.

```text
Default mode:
  write --blocks--> read  X
  write --blocks--> write X

WAL mode:
  write --does not block--> read  OK   <- the key improvement
  write --still blocks-->   write X    <- unchanged
```

### What Is FTS5

FTS5 is SQLite's full-text search extension (Full-Text Search 5).

It lets you quickly search for keywords across large volumes of historical messages -- no need to scan every row with `LIKE '%keyword%'`.

### What Is parent_session_id

When a conversation gets long enough to trigger context compression (`s05`), the system creates a new session. The new session points back to the old one through `parent_session_id`.

This forms a chain:

```text
session_001 (full history, 500 messages)
     ^
     | parent_session_id
session_002 (compressed summary + new messages)
     ^
     | parent_session_id
session_003 (compressed again)
```

Old history is not deleted -- just archived.

### What Is source

Every session has a `source` field indicating which entry point the message came from: `cli`, `telegram`, `discord`, `slack`, `weixin`, etc.

This lets you filter sessions by platform: "show only Telegram conversations."

![Session Persistence Lifecycle](../../illustrations/en/s03-session-store/02-flowchart-session-lifecycle.png)

## Minimal Mental Model

```text
agent starts up
  |
  v
New session? --yes--> create a session record
  |
  no (continuing an existing session)
  |
  v
Read historical messages from SQLite
  |
  v
Pass them to AIAgent.run_conversation()
  |
  v
After each conversation turn, write new messages to SQLite
  |
  v
agent exits
  |
  v
On next launch, read them back from SQLite -- the conversation is still there
```

## Key Data Structures

### 1. Session Record

Minimal teaching version:

```python
session = {
    "id": "...",
    "source": "cli",
    "started_at": 1710000000.0,
}
```

The full system also stores: model, system_prompt, parent_session_id, token statistics, and cost estimates. But the minimal version only needs the three fields above to work.

### 2. Message Record

Minimal teaching version:

```python
message = {
    "session_id": "...",
    "role": "user" | "assistant" | "tool",
    "content": "...",
    "timestamp": 1710000000.0,
}
```

The full system also stores: tool_calls (JSON-serialized), tool_call_id, tool_name, and token_count.

### 3. FTS Index

Not a data structure you manipulate directly. It is a search index maintained automatically by SQLite. Every time a message is inserted, a SQLite trigger updates the FTS index.

## Minimal Implementation

### Step 1: Create the Tables

```python
import sqlite3

conn = sqlite3.connect("state.db")
conn.execute("PRAGMA journal_mode=WAL")

conn.executescript("""
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    started_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    timestamp REAL NOT NULL
);
""")
```

That is the minimal version. Two tables, WAL mode, ready to go.

### Step 2: Create a Session

```python
import uuid, time

def create_session(conn, source="cli"):
    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
        (session_id, source, time.time()),
    )
    conn.commit()
    return session_id
```

### Step 3: Write Messages

```python
def add_messages(conn, session_id, messages):
    for msg in messages:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, msg["role"], msg.get("content", ""), time.time()),
        )
    conn.commit()
```

### Step 4: Read History

```python
def get_session_messages(conn, session_id):
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]
```

### Step 5: Plug It Into the Loop

```python
# At startup
session_id = create_session(conn, source="cli")

# After each conversation turn
new_messages = result["messages"][len(old_messages):]  # only store the new ones
add_messages(conn, session_id, new_messages)

# On next launch
history = get_session_messages(conn, session_id)
result = agent.run_conversation(user_message, conversation_history=history)
```

## Unique Designs in Hermes Agent

### Write-Lock Conflict Handling

Under SQLite WAL mode, writes still need to be serialized. The default busy handler uses deterministic waits, which under high concurrency cause a queuing effect (everyone waits the same amount of time).

Hermes Agent's approach: set the SQLite timeout short (1 second), then do randomized back-off retries at the application layer. The random intervals naturally spread out competing writers.

### system_prompt Caching

Gateway creates a new AIAgent instance for every message. If the system prompt were reassembled each time, a change to MEMORY.md in the interim could alter the prompt, invalidating Anthropic's prompt cache.

So Hermes Agent stores the initially assembled system prompt in the session table. Subsequent instances read from the cache directly, ensuring the prompt stays unchanged.

### Schema Version Management

The database schema evolves across versions. Hermes Agent maintains a `schema_version` table and checks the version number at startup. If a migration is needed, it automatically runs the appropriate ALTER TABLE statements.

## Most Common Beginner Mistakes

### 1. Not Enabling WAL Mode

Under the default mode, a single write operation blocks all reads. In Gateway scenarios, when the agent is writing a message, a read request from another platform will hang.

### 2. Storing the Entire Messages List Instead of the Delta

Writing the complete messages list in full after every turn, instead of just the new additions. The longer the conversation, the slower the writes.

### 3. Hard-Coding session_id

Using the same session_id every launch, mixing all conversations together. A new session_id should be generated for each new conversation.

### 4. Not Handling tool_calls Serialization

`tool_calls` is a nested structure that cannot be stored directly in a TEXT column. It needs JSON serialization.

### 5. Not Separating by chat_id in Gateway

Different chat windows on different platforms should be different sessions. If all messages are dumped into one session, the agent will treat User A's conversation as context for User B.

## The Complete Loop So Far

Combining the s01 loop + s02 tool system + s03 session persistence, the full flow looks like this:

```text
Program starts
  |
  +-- New conversation? -- yes --> create_session() -> get session_id
  |                                messages = []
  |
  +-- Continue old conversation? -- yes --> read historical messages from SQLite
                                            messages = get_session_messages(session_id)
  |
  v
User types a message
  |
  v
messages.append({"role": "user", "content": user_input})
  |
  v
+------------------ Loop starts (up to 90 iterations) -----------------+
|                                                                       |
|  Assemble api_messages = [system_prompt] + messages                   |
|                          |                                            |
|                          v                                            |
|                    Call model API                                     |
|                          |                                            |
|                          v                                            |
|              messages.append(assistant reply)                         |
|                          |                                            |
|               Has tool_calls?                                        |
|              /            \                                           |
|            no              yes                                        |
|            |               |                                          |
|            v               v                                          |
|         Loop ends    registry.dispatch(tool_name, args)               |
|                           |                                           |
|                           v                                           |
|              messages.append(tool result)                             |
|                           |                                           |
|                           v                                           |
|                        Next iteration                                 |
|                                                                       |
+-----------------------------------------------------------------------+
  |
  v
Write this turn's new messages to SQLite
  |
  v
Wait for the next user input (loop back up)
  |
  ...
  |
  v
Program exits -> next launch can read from SQLite and resume
```

In code:

```python
# -- Startup --
conn = sqlite3.connect("state.db")
conn.execute("PRAGMA journal_mode=WAL")

if continue_session:
    messages = get_session_messages(conn, session_id)
else:
    session_id = create_session(conn, source="cli")
    messages = []

# -- Main conversation loop --
while True:
    user_input = input("> ")
    if user_input == "exit":
        break

    messages.append({"role": "user", "content": user_input})
    old_len = len(messages)

    # s01 core loop
    for i in range(90):
        api_messages = [{"role": "system", "content": system_prompt}] + messages

        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4",
            messages=api_messages,
            tools=registry.get_definitions(),  # s02: get tool schemas from the registry
        )

        assistant_msg = response.choices[0].message
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [...] or None,
        })

        if not assistant_msg.tool_calls:
            break  # Model is done; exit inner loop

        # s02: registry dispatches execution (handles sync/async automatically)
        for tc in assistant_msg.tool_calls:
            result = registry.dispatch(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # s03: write only the new messages to SQLite
    add_messages(conn, session_id, messages[old_len:])

    # Print the last assistant reply
    print(messages[-1]["content"])
```

Each layer handles its own concern:

| Layer | Responsibility | Does Not Handle |
|---|---|---|
| **s01 loop** | messages -> API -> tool_calls -> next turn | How tools are found; where messages are stored |
| **s02 tools** | Look up by name, dispatch, sync/async bridge | Loop logic; persistence |
| **s03 store** | Write to SQLite, read history, WAL concurrency safety | How the loop runs; how tools execute |

## Teaching Boundary

What this chapter covers:

**Move messages from memory to SQLite so conversations survive restarts and multi-platform concurrency is safe.**

This is not yet context compression (`s05`, which uses parent_session_id), the memory system (`s07`, curated information spanning sessions), or Gateway session routing (`s12`, assigning sessions by chat_id).

Deliberately left out:

- Advanced FTS5 search syntax
- Token statistics and cost estimation fields
- Specific ALTER TABLE logic for schema migrations
- How Gateway maps chat_id to the right session -> `s12`

If you can make "agent exits and restarts with the conversation intact," you have completed this chapter.

## One Sentence to Remember

**Hermes Agent uses SQLite + WAL instead of the file system because it was designed for multi-platform concurrency from the start -- this is not an optimization; it is a fundamental requirement of Gateway mode.**
