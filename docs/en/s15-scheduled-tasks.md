# s15: Scheduled Tasks

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > [ s15 ] > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The agents from s01-s14 are purely reactive -- they only act when a user sends a message. This chapter teaches the agent to "remember what to do in the future" and take action when the time comes.*

![Scheduled Task Lifecycle](../../illustrations/en/s15-scheduled-tasks/01-flowchart-task-lifecycle.png)

## What problem does this chapter solve

Up through s14, the agent works like this: user says something -> agent acts -> replies. If the user says nothing, the agent sits idle.

But in real-world scenarios, users say things like:

> "**In 30 minutes**, check if that deployment succeeded."

> "**Every 2 hours**, check the server disk usage and let me know if it exceeds 80%."

> "**Every weekday at 9 AM**, summarize yesterday's git log for me."

Three requests, one common thread: **the user wants the agent to proactively do something at a future time.**

Without a scheduled task system, the agent can only say "Sure, please remind me when the time comes" -- how is that any different from an alarm clock?

## Scenario walkthrough: the full lifecycle of a scheduled task

A user tells the agent on Telegram: "Check the deployment status for me in 30 minutes."

```text
1. The agent understands the intent and calls cron_tool:
   create_job(schedule="30m", prompt="Check deployment status, run kubectl get pods")

2. cron_tool parses "30m":
   - Current time: 14:00
   - next_fire = 14:30
   - one_shot = true (delete after one execution)

3. JobStore writes this job to jobs.json

4. The agent replies: "Got it, I'll check the deployment status in 30 minutes."

5. The background JobScheduler scans jobs.json every 30 seconds...
   - 14:00:30 -- not time yet, skip
   - 14:01:00 -- not time yet, skip
   - ...
   - 14:30:00 -- time's up!

6. JobScheduler constructs a MessageEvent:
   text = "Check deployment status, run kubectl get pods"
   source.platform = "cron"
   source.chat_id = the original Telegram user's chat_id

7. This MessageEvent is fed into GatewayRunner._handle_message()
   -> follows the exact same path as a real user message

8. The agent runs kubectl get pods, gets the result, and replies on Telegram

9. Because one_shot=true, JobStore automatically deletes this job
```

Key insight: **A scheduled task is not a new execution path. It is simply a mechanism that "pretends the user said something" at a future time.** From GatewayRunner onward, all logic is fully reused.

## Suggested reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- cron_tool plugs in via self-registration
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) -- when a job fires, it goes through the Gateway's `_handle_message`
- [`s14-terminal-backends.md`](./s14-terminal-backends.md) -- commands triggered by jobs reuse the same backend

## Key terms

### What is a CronJob

A complete description of a scheduled task. It includes: when to fire, what message to send to the agent when it fires, and which session it belongs to.

```python
@dataclass
class CronJob:
    job_id: str           # Unique identifier
    schedule: str         # Original schedule expression: "30m" / "every 2h" / "0 9 * * 1-5"
    prompt: str           # Message to send to the agent when the job fires
    session_key: str      # Which session this belongs to
    created_at: str       # Creation time
    next_fire: float      # Unix timestamp of the next fire time
    one_shot: bool        # True = delete after one execution, False = recurring
```

### Three schedule formats

| Format | Example | Meaning | one_shot |
|--------|---------|---------|----------|
| Delay | `30m` | Execute once in 30 minutes | True |
| Interval | `every 2h` | Execute every 2 hours, recurring | False |
| Cron | `0 9 * * 1-5` | Every weekday at 9 AM | False |

Why not use only cron expressions? Because users say "remind me in 30 minutes" far more often than "set up a cron for me." The delay format makes the most common scenario the simplest.

### What is a JobStore

The persistence layer for scheduled tasks. Responsible for CRUD operations and writing to disk.

Why use `jobs.json` instead of SQLite?

- The number of tasks is small -- a single user typically has no more than 20 active tasks
- Human-readable -- you can open and inspect it directly when debugging
- No need for full-text search or concurrent writes

SQLite is designed for massive volumes of session messages. Using it to store 20 jobs is overkill.

### What is a JobScheduler

A background thread that wakes up every 30 seconds, scans all jobs, and fires any that are due.

Why a thread instead of asyncio? Because the scheduler needs to run in both CLI mode (synchronous) and Gateway mode (asynchronous). A thread is the lowest common denominator for both modes.

## Minimal mental model

```text
User (or the agent itself)
    |
    |  cron_tool: create_job(schedule="every 2h", prompt="Check disk")
    v
JobStore
    |  Writes to jobs.json
    |
    |  +-------------- Background ----------------+
    |  |  JobScheduler (thread, scans every 30s)   |
    |  |                                           |
    |  |  for job in jobs:                         |
    |  |      if now >= job.next_fire:              |
    |  |          fire(job)                        |
    |  +-------------------------------------------+
    |
    |  fire(job):
    v
Construct MessageEvent(text=job.prompt, platform="cron")
    |
    |  Feed into GatewayRunner._handle_message()
    v
Follows the exact same path as a real user message
    |
    |  Agent executes and replies
    v
Result sent back to the original platform (Telegram / Discord / CLI)
```

## Key data structures

### jobs.json

```json
[
  {
    "job_id": "a1b2c3",
    "schedule": "every 2h",
    "prompt": "Run df -h. Alert if any partition exceeds 80%.",
    "session_key": "main:telegram:alice",
    "created_at": "2025-01-15T14:00:00",
    "next_fire": 1736953200.0,
    "one_shot": false
  },
  {
    "job_id": "d4e5f6",
    "schedule": "0 9 * * 1-5",
    "prompt": "Summarize yesterday's git log, main branch only",
    "session_key": "main:telegram:alice",
    "created_at": "2025-01-15T14:05:00",
    "next_fire": 1737007200.0,
    "one_shot": false
  }
]
```

## Starting with the simplest implementation

Add a `time.sleep` poll inside the agent loop:

```python
# Simplest approach: poll in the main loop
while True:
    user_input = input("You: ")
    if user_input:
        handle_message(user_input)

    # Check scheduled tasks
    for job in jobs:
        if time.time() >= job.next_fire:
            handle_message(job.prompt)  # Pretend the user said this
            update_next_fire(job)
```

This works, but has two problems.

### Problem 1: Blocking

`input()` blocks. If the user doesn't type anything, the scheduled tasks never get checked.

You might think: "Use `select` or `threading` to make `input` non-blocking." Sure, but that leads to Problem 2.

### Problem 2: What about Gateway mode

Gateway mode is asynchronous -- there is no `input()`. You need a scheduling mechanism that is independent of the entry mode.

**Solution: Put the scheduler in its own background thread.** Both CLI and Gateway start the same thread, and when a job is due, the thread constructs a MessageEvent and feeds it into the processing pipeline.

## Minimal implementation

### Schedule expression parsing

Parsing logic for the three formats:

```python
def parse_schedule(expr: str) -> tuple[float, bool]:
    """
    Parse a schedule expression. Returns (next_fire_timestamp, one_shot).

    Supports:
      "30m"           -> 30 minutes from now, one-shot
      "2h"            -> 2 hours from now, one-shot
      "every 30m"     -> every 30 minutes, recurring
      "every 2h"      -> every 2 hours, recurring
      "0 9 * * 1-5"   -> cron expression, recurring
    """
    expr = expr.strip()
    now = time.time()

    # Format 1: "every Xm" / "every Xh" -> recurring interval
    if expr.startswith("every "):
        seconds = _parse_duration(expr[6:])
        return now + seconds, False

    # Format 2: "Xm" / "Xh" -> one-shot delay
    try:
        seconds = _parse_duration(expr)
        return now + seconds, True
    except ValueError:
        pass

    # Format 3: cron expression
    next_ts = _next_cron_fire(expr)
    return next_ts, False
```

`_parse_duration` is straightforward -- grab the unit from the end of the string, the number from the front:

```python
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

def _parse_duration(s: str) -> float:
    s = s.strip()
    unit = s[-1].lower()
    if unit not in _UNITS:
        raise ValueError(f"unknown unit: {unit}")
    return float(s[:-1]) * _UNITS[unit]
```

### Cron expression parsing

Five-field cron doesn't need a third-party library -- the standard format is sufficient:

```text
minute hour day month weekday
0      9    *   *     1-5     <- weekdays at 9 AM
```

Core idea: starting from "now," scan forward minute by minute until you find a time that matches all five fields.

```python
def _next_cron_fire(expr: str) -> float:
    """Starting from the current time, find the next time matching the cron expression."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs 5 fields, got {len(fields)}: {expr}")

    matchers = [_parse_cron_field(f, r) for f, r in
                zip(fields, [(0,59), (0,23), (1,31), (1,12), (0,6)])]

    # Start from the next minute, search up to 366 days
    t = datetime.now().replace(second=0, microsecond=0)
    t += timedelta(minutes=1)

    for _ in range(366 * 24 * 60):
        if (matchers[0](t.minute) and matchers[1](t.hour)
                and matchers[2](t.day) and matchers[3](t.month)
                and matchers[4](t.weekday())):
            # Python weekday(): 0=Mon, cron: 0=Sun -> conversion needed
            return t.timestamp()
        t += timedelta(minutes=1)

    raise ValueError(f"no match in 366 days for: {expr}")
```

`_parse_cron_field` handles four syntaxes: `*`, `*/5`, `1-5`, `1,3,5`, and returns an `int -> bool` predicate. This is the most complex part of cron parsing, but it's not the focus of this chapter -- see the source code for details.

### JobStore

```python
class JobStore:
    """Task persistence: CRUD + write to disk."""

    def __init__(self, path: str = "jobs.json"):
        self._path = Path(path)
        self._jobs: dict[str, CronJob] = {}
        self._lock = threading.Lock()
        self._load()

    def add(self, job: CronJob):
        with self._lock:
            self._jobs[job.job_id] = job
            self._save()

    def remove(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._save()
                return True
            return False

    def list_all(self) -> list[CronJob]:
        with self._lock:
            return list(self._jobs.values())

    def get_due(self) -> list[CronJob]:
        """Return all jobs that are due."""
        now = time.time()
        with self._lock:
            return [j for j in self._jobs.values() if now >= j.next_fire]

    def advance(self, job: CronJob):
        """Update next_fire (recurring tasks) or delete (one-shot tasks)."""
        with self._lock:
            if job.one_shot:
                self._jobs.pop(job.job_id, None)
            else:
                next_ts, _ = parse_schedule(job.schedule)
                job.next_fire = next_ts
            self._save()

    def _save(self):
        data = [vars(j) for j in self._jobs.values()]
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load(self):
        if not self._path.exists():
            return
        for item in json.loads(self._path.read_text()):
            job = CronJob(**item)
            self._jobs[job.job_id] = job
```

Why the lock? Because JobStore is accessed by two threads: the main thread (cron_tool writes) and the background thread (JobScheduler reads). No lock -> race condition.

### JobScheduler

```python
class JobScheduler:
    """Background thread that periodically checks for due tasks and fires them."""

    def __init__(self, store: JobStore, fire_callback):
        self._store = store
        self._fire = fire_callback   # def fire(job: CronJob) -> None
        self._interval = 30          # seconds
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for job in self._store.get_due():
                try:
                    self._fire(job)
                except Exception as e:
                    print(f"  [scheduler] job {job.job_id} failed: {e}")
                self._store.advance(job)
            time.sleep(self._interval)
```

`daemon=True` is important: the background thread terminates automatically when the main process exits, preventing hangs.

### cron_tool: the agent's interface

```python
def handle_cron_tool(args: dict, *, store: JobStore, session_key: str, **kw):
    action = args.get("action", "list")

    if action == "create":
        schedule = args["schedule"]
        prompt = args["prompt"]
        next_fire, one_shot = parse_schedule(schedule)
        job = CronJob(
            job_id=uuid.uuid4().hex[:8],
            schedule=schedule,
            prompt=prompt,
            session_key=session_key,
            created_at=datetime.now().isoformat(),
            next_fire=next_fire,
            one_shot=one_shot,
        )
        store.add(job)
        fire_time = datetime.fromtimestamp(next_fire).strftime("%Y-%m-%d %H:%M")
        return f"Job {job.job_id} created. Next fire: {fire_time}"

    elif action == "list":
        jobs = store.list_all()
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            fire_time = datetime.fromtimestamp(j.next_fire).strftime("%m-%d %H:%M")
            kind = "once" if j.one_shot else "recurring"
            lines.append(f"  {j.job_id}  {j.schedule:15s}  {kind:9s}  "
                         f"next: {fire_time}  {j.prompt[:40]}")
        return "Jobs:\n" + "\n".join(lines)

    elif action == "delete":
        job_id = args["job_id"]
        if store.remove(job_id):
            return f"Job {job_id} deleted."
        return f"Job {job_id} not found."

    return f"Unknown action: {action}"
```

The tool definition registered with the model:

```python
CRON_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cron",
        "description": "Create, list, or delete scheduled tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "delete"],
                },
                "schedule": {
                    "type": "string",
                    "description": 'Schedule expression: "30m", "every 2h", or "0 9 * * 1-5"',
                },
                "prompt": {
                    "type": "string",
                    "description": "What the agent should do when the job fires.",
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID to delete (for action=delete).",
                },
            },
            "required": ["action"],
        },
    },
}
```

## Scenario 2: How a recurring task's result gets back to the user

A user says on Telegram: "Check the disk for me every 2 hours."

```text
1. The agent calls cron_tool: create_job(schedule="every 2h", prompt="Run df -h, alert if over 80%")
2. JobStore writes to jobs.json, next_fire = 2 hours from now

   === 2 hours later ===

3. JobScheduler finds the job is due
4. Constructs a MessageEvent:
     text = "Run df -h, alert if over 80%"
     source.platform = "cron"
     source.chat_id = "main:telegram:alice"   <- the original user's session_key

5. Fed into GatewayRunner._handle_message()
6. The agent runs df -h (via the terminal backend from s14)
7. Finds /data partition at 85% -> the agent replies with an alert
8. GatewayRunner sends the reply back to Telegram
9. JobStore updates next_fire = 2 more hours from now

   === Another 2 hours later ===

10. Steps 3-9 repeat
```

Note step 4: **JobScheduler does not execute commands directly -- it constructs a message and feeds it into the Gateway.** This means the job's execution benefits from all the agent's capabilities -- tool calls, error recovery, permission checks, context compression -- all reused, without writing a single extra line.

## Scenario 3: How jobs fire in CLI mode

Gateway mode has `_handle_message` to receive MessageEvents. CLI mode does not.

Solution: In CLI mode, JobScheduler's `fire_callback` directly calls `run_conversation()`:

```python
# Gateway mode
def fire_gateway(job):
    event = MessageEvent(
        text=job.prompt,
        source=SessionSource(platform="cron", chat_id=..., ...),
    )
    asyncio.run_coroutine_threadsafe(
        gateway._handle_message(event), loop
    )

# CLI mode
def fire_cli(job):
    result = run_conversation(job.prompt, conn, session_id, cached_prompt)
    print(f"\n[cron] {job.job_id}: {result['final_response']}\n")
```

Two modes, the same JobScheduler, different `fire_callback` implementations.

## How it plugs into the main loop

```text
At startup
  |
  +-- CLI mode
  |     JobStore("jobs.json")
  |     JobScheduler(store, fire_callback=fire_cli)
  |     scheduler.start()         <- background thread starts
  |     while True:
  |         input() -> run_conversation()   <- main thread handles user input
  |
  +-- Gateway mode
        JobStore("jobs.json")
        JobScheduler(store, fire_callback=fire_gateway)
        scheduler.start()         <- background thread starts
        GatewayRunner.start()     <- asyncio event loop

At shutdown
  scheduler.stop()
```

When registering the tool, you need to pass `store` and `session_key`:

```python
# When registering the cron tool, bind store via closure
def make_cron_handler(store, session_key):
    def handler(args, **kw):
        return handle_cron_tool(args, store=store, session_key=session_key, **kw)
    return handler

tool_registry.register("cron", make_cron_handler(store, current_session_key))
```

## Hermes Agent's unique design

### Tasks as messages

Most scheduled task systems call a function directly when a job is due. Hermes Agent does not -- **when a job fires, it constructs a MessageEvent, disguised as a user message, and feeds it into the Gateway.**

This brings three benefits:

1. **Full agent capabilities for free.** Tool calls, error recovery, permission checks, sub-agent delegation -- all automatically in effect.
2. **Execution history persisted automatically.** Conversations triggered by tasks are stored in SQLite, searchable just like user-initiated conversations.
3. **Replies automatically routed.** Results are sent back to the user via the original platform (Telegram / Discord), with no extra wiring needed.

### Design trade-offs of the three schedule formats

Why not use only cron expressions?

Users say "remind me in 30 minutes" far more often than "set up a cron." If you force cron format:
- What the user said: "in 30 minutes"
- What the agent has to compute: current time is 14:00, so that's `30 14 15 1 *` (2025-01-15 14:30)
- Plus you have to handle day rollovers, month rollovers, and time zones

With the delay format, it's a one-liner: `parse_schedule("30m")` -> `(now + 1800, True)`.

Keep simple scenarios simple; use cron for complex ones.

## Common beginner mistakes

### 1. Checking scheduled tasks in the main thread

```python
while True:
    user_input = input()     # <- blocks
    check_cron_jobs()        # <- never reached
```

`input()` blocks the main thread, so scheduled tasks never fire.

**Fix: Put the scheduler in its own thread.**

### 2. Forgetting to lock

JobStore is accessed by two threads: the main thread (cron_tool writes) and the background thread (JobScheduler reads). No lock -> dictionary changes size during iteration -> `RuntimeError`.

**Fix: Every JobStore method uses `with self._lock`.**

### 3. Not deleting one-shot tasks

A `one_shot=True` job fires but is not removed from the store. 30 seconds later the scheduler finds it again and fires it a second time.

**Fix: In `advance()`, one-shot jobs are popped, not updated with a new next_fire.**

### 4. Getting the weekday wrong in cron expressions

Python's `datetime.weekday()` returns 0=Monday ... 6=Sunday. Standard cron uses 0=Sunday.

```text
cron's 5 = Friday
Python's 5 = Saturday
```

A one-digit difference causes the task to fire on the wrong day.

**Fix: Convert during parsing with `(python_weekday + 1) % 7`, or handle the mapping when matching cron fields.**

### 5. Not handling jobs.json corruption

The process crashes while writing `jobs.json`, leaving a half-written file. On the next startup, `json.loads` throws an error.

**Fix: Write to a temporary file first, then rename (atomic operation). On read, catch `json.JSONDecodeError` and fall back to an empty list.**

## Scope of this chapter

This chapter covers three things:

1. **Why scheduled tasks are needed** -- derived from the pain point that "the agent can only react passively"
2. **Three schedule formats** -- parsing delay, interval, and cron expressions
3. **Tasks as messages** -- when a job fires, it is disguised as a MessageEvent and fed into the Gateway

Not covered:

- Distributed scheduling (how to prevent multiple Gateway instances from firing the same job) -> production optimization
- Task dependency chains (job B fires only after job A completes) -> too close to a workflow engine
- Time zone handling -> this tutorial uses local time; production environments need UTC + user time zone
- Task execution timeouts and retry strategies -> already covered by s06's error recovery

## How this chapter relates to others

- **s02** registered cron_tool -> self-registration, just like any other tool
- **s03**'s SQLite -> conversations triggered by scheduled tasks are also stored in sessions
- **s06**'s error recovery -> if the agent loop triggered by a job errors out, the same retry logic applies
- **s12**'s Gateway -> when a job fires it goes through `_handle_message`, same path as platform messages
- **s14**'s terminal backend -> commands in jobs reuse the same backend

**s15 is the final chapter of Phase 3.** At this point, Hermes Agent can:
- Receive messages from a dozen messaging platforms (s12-s13)
- Run commands in different execution environments (s14)
- Proactively take action at a future time (s15)

Phase 4 moves into advanced capabilities: MCP, browser automation, voice & vision.

## After finishing this chapter, you should be able to answer

- Why does a scheduled task construct a MessageEvent when it fires, instead of directly executing a command?
- When a user says "remind me in 30 minutes," why not parse it into a cron expression?
- Why is JobScheduler a thread rather than an asyncio task?
- What is the difference between how `advance()` handles one-shot tasks versus recurring tasks?
- How does the job firing path differ between CLI mode and Gateway mode?

---

**One sentence to remember: A scheduled task is not a new execution path -- it is simply a mechanism that "pretends the user said something" at a future time. From the Gateway onward, all logic is fully reused.**
