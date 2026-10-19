# s22: Hook System & BOOT.md

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > [ s22 ] > s23 > s24 > s25 > s26 > s27`

> *By s21, the agent's core capabilities and self-evolution mechanisms are all in place. But if you want the agent to "run a self-check every time it starts" or "add an audit layer before every tool call" -- you don't need to modify core code. You just need to attach a hook.*

![Lifecycle Hook System](../../illustrations/en/s22-hook-system/01-framework-lifecycle-hooks.png)

## What Problem Does This Chapter Solve

Three scenarios.

**Scenario 1: Startup self-check.** You want the agent to automatically check whether any cron jobs failed overnight and whether disk space is sufficient every time it starts. No code changes required -- just write a `BOOT.md`:

```markdown
# Startup Checklist
1. Check if any cron jobs failed overnight
2. Check disk usage, alert if any partition > 80%
3. If there are errors in deploy.log, summarize them
```

The agent automatically executes this checklist on startup, like an on-call engineer running a patrol check.

**Scenario 2: Tool auditing.** You want to log an entry every time the `terminal` tool is called -- who executed what command and when. No changes to the terminal tool's code -- just attach a `pre_tool_call` hook:

```python
def audit_tool(tool_name, args, **kw):
    if tool_name == "terminal":
        log(f"[audit] {datetime.now()} terminal: {args.get('command')}")
```

**Scenario 3: Session summary.** After every conversation ends, automatically generate a summary and save it to a log file. No changes to the core loop -- just attach an `on_session_end` hook.

What all three scenarios have in common: **inserting custom logic at specific points in the core loop, without modifying core code.**

## Suggested Reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- `pre_tool_call` / `post_tool_call` hooks fire before and after tool calls
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) -- Gateway hooks fire at key points in message routing
- [`s20-background-review.md`](./s20-background-review.md) -- Background review can be thought of as a built-in "post-session" hook

## Key Concepts

### What Are Lifecycle Hooks

The agent has several key moments from startup to shutdown:

```text
gateway:startup  ->  session:start  ->  agent:start
                                          |
                                     (tool call loop)
                                     pre_tool_call -> execute -> post_tool_call
                                          |
                                     agent:end  ->  session:end
```

A hook is a callback function you attach to one of these moments. When that moment arrives, the system automatically calls your function.

### What Is BOOT.md

A Markdown file placed at `~/.hermes/BOOT.md`. When the Gateway starts, it automatically sends its content as a prompt to a one-shot agent for execution.

It's not a shell script -- it's a set of instructions for the agent. You can write things like "check the logs" or "send a message to Discord," and the agent will use its own tools to carry them out.

### Two Hook Systems

Hermes Agent has two independent hook systems, designed for different scenarios:

| | Gateway hooks | Plugin hooks |
|---|---|---|
| Scope | Gateway mode only | Available in both CLI and Gateway |
| Registration | Files in the `~/.hermes/hooks/` directory | `register_hook()` in code |
| Invocation | `emit(event_type, context)` | `invoke_hook(hook_name, **kwargs)` |
| Execution model | Asynchronous (supports async) | Synchronous |
| Use case | Platform-level events (connections, message routing) | Agent-level events (tool calls, API requests) |

For teaching purposes, we'll explain each separately first, then discuss why there are two.

## Minimal Mental Model

```text
~/.hermes/BOOT.md
    |  "Check cron and disk on startup"
    |
    v
Gateway starts -> emit("gateway:startup")
    |
    |  boot-md hook: read BOOT.md -> launch one-shot agent -> execute instructions
    |
    v
User sends message -> emit("session:start") / emit("agent:start")
    |
    |  -> plugin hooks: invoke_hook("pre_llm_call") -> inject context
    |  -> model call
    |  -> plugin hooks: invoke_hook("pre_tool_call") -> audit log
    |  -> tool execution
    |  -> plugin hooks: invoke_hook("post_tool_call")
    |
    v
Agent finishes -> emit("agent:end")
    |
    |  -> plugin hooks: invoke_hook("on_session_end") -> session summary
    |
    v
Session ends -> emit("session:end")
```

## Part 1: Gateway Hooks

### Event Types

| Event | When It Fires | context Contains |
|------|---------|-------------|
| `gateway:startup` | Gateway process starts | `platforms` (list of connected platforms) |
| `session:start` | New session created | `platform`, `user_id`, `session_key` |
| `session:end` | Session ends | `platform`, `user_id`, `session_key` |
| `session:reset` | User executes `/new` | `platform`, `user_id`, `session_key` |
| `agent:start` | Agent begins processing a message | `platform`, `user_id`, `message` |
| `agent:end` | Agent finishes processing | `platform`, `user_id`, `message`, `response` |
| `command:*` | Any slash command | `platform`, `user_id`, `command`, `args` |

`command:*` is a wildcard -- register once to listen for all commands.

### Hook File Structure

```text
~/.hermes/hooks/
└── my-audit-hook/
    ├── HOOK.yaml       <- Declares name, description, which events to listen for
    └── handler.py      <- The actual code that runs
```

**HOOK.yaml:**

```yaml
name: my-audit-hook
description: Log all agent activity
events:
  - agent:start
  - agent:end
```

**handler.py:**

```python
async def handle(event_type: str, context: dict):
    if event_type == "agent:start":
        print(f"[audit] agent started for {context.get('user_id')}")
    elif event_type == "agent:end":
        print(f"[audit] agent done, response: {context.get('response', '')[:50]}")
```

The handler can be either `def` or `async def` -- the system auto-detects using `asyncio.iscoroutine()`.

### HookRegistry

```python
class HookRegistry:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def register(self, event_type: str, handler: Callable):
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event_type: str, context: dict | None = None):
        handlers = list(self._handlers.get(event_type, []))
        # Wildcard matching: command:* matches all command:xxx
        if ":" in event_type:
            base = event_type.split(":")[0]
            handlers.extend(self._handlers.get(f"{base}:*", []))
        for fn in handlers:
            try:
                result = fn(event_type, context or {})
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[hooks] Error in handler for '{event_type}': {e}")
```

Key design: **hook exceptions never propagate.** The `try/except` ensures a faulty hook can't crash the entire Gateway.

### Auto-Discovery

```python
def discover_and_load(self, hooks_dir: Path):
    """Scan hooks directory, load HOOK.yaml + handler.py."""
    if not hooks_dir.exists():
        return
    for hook_dir in sorted(hooks_dir.iterdir()):
        manifest = hook_dir / "HOOK.yaml"
        handler_file = hook_dir / "handler.py"
        if not manifest.exists() or not handler_file.exists():
            continue
        meta = yaml.safe_load(manifest.read_text())
        # Dynamically import handler.py
        spec = importlib.util.spec_from_file_location(meta["name"], handler_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handle_fn = getattr(module, "handle")
        for event in meta.get("events", []):
            self.register(event, handle_fn)
```

## Part 2: BOOT.md

BOOT.md is a built-in Gateway hook, bound to the `gateway:startup` event.

### How It Works

```python
async def handle_boot_md(event_type: str, context: dict):
    boot_path = HERMES_HOME / "BOOT.md"
    if not boot_path.exists():
        return

    content = boot_path.read_text()

    def _run():
        # Create a one-shot agent to execute BOOT.md instructions
        conn = init_db(DB_PATH)
        session_id = create_session(conn)
        prompt = build_system_prompt(os.getcwd())
        result = run_conversation(
            user_message=content,
            conn=conn,
            session_id=session_id,
            cached_prompt=prompt,
            max_iterations_override=20,
        )
        conn.close()
        return result

    # Run in a background thread so it doesn't block Gateway startup
    thread = threading.Thread(target=_run, daemon=True, name="boot-md")
    thread.start()
```

**Scenario: Startup Self-Check Flow**

```text
1. Gateway starts
2. HookRegistry discovers the built-in boot-md hook
3. emit("gateway:startup") -> handle_boot_md is called
4. Reads ~/.hermes/BOOT.md:
     "1. Check if any cron jobs failed
      2. Check disk usage"
5. Background thread launches a one-shot agent
6. Agent calls terminal tool to run df -h, finds /data at 85%
7. Agent calls terminal tool to check cron logs, finds last night's backup failed
8. Agent sends results to user via Gateway callback (if a home channel is configured)
9. Gateway continues running normally, unaffected by the boot process
```

**Why not use a shell script?** Because BOOT.md instructions are executed by the agent, which has access to all its tools -- terminal, browser, MCP tools. `df -h` is just the simplest example; you could also write "log into the monitoring dashboard and check for alerts."

## Part 3: Plugin Hooks

### Hook Types

| Hook | When It Fires | What It Can Do |
|------|---------|---------|
| `pre_tool_call` | **Before** tool execution | Audit logging, blocking dangerous operations |
| `post_tool_call` | **After** tool execution | Recording results, tracking elapsed time |
| `pre_llm_call` | Before a conversation turn begins | Injecting additional context |
| `post_llm_call` | After a conversation turn completes | Recording results |
| `on_session_start` | First turn of a new session | Initializing resources |
| `on_session_end` | After each conversation turn ends | Cleanup, summarization |

### Registration

```python
class PluginHookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}

    def register_hook(self, hook_name: str, callback: Callable):
        self._hooks.setdefault(hook_name, []).append(callback)

    def invoke_hook(self, hook_name: str, **kwargs) -> list:
        results = []
        for cb in self._hooks.get(hook_name, []):
            try:
                ret = cb(**kwargs)
                if ret is not None:
                    results.append(ret)
            except Exception as e:
                print(f"  [hook] {hook_name} error: {e}")
        return results
```

### Scenario: Tool Audit Hook

```python
# Registration
hooks = PluginHookRegistry()

audit_log = []

def audit_tool_call(tool_name, args, **kw):
    audit_log.append({
        "time": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
    })

hooks.register_hook("pre_tool_call", audit_tool_call)

# Triggered during tool dispatch
hooks.invoke_hook("pre_tool_call", tool_name="terminal",
                  args={"command": "rm -rf /tmp/build"})

# audit_log now has one entry
```

### Integration with run_conversation

```python
# Before tool call
hooks.invoke_hook("pre_tool_call", tool_name=tool_name, args=tool_args)
output = registry.dispatch(tool_name, tool_args)
# After tool call
hooks.invoke_hook("post_tool_call", tool_name=tool_name,
                  args=tool_args, result=output)
```

## Why Two Hook Systems

| Dimension | Gateway Hooks | Plugin Hooks |
|------|--------------|-------------|
| Granularity | Coarse (session-level, platform-level) | Fine (tool call-level, API call-level) |
| Deployment | File directory, no coding required | Code registration, requires Python |
| Use case | Operations: monitoring, alerting, auditing | Development: debugging, customization, extension |
| Hot reload | Scanned at startup, no hot updates | Code registration, executed at startup |

Could the two be merged into one? Technically yes, but it would make simple scenarios more complex. Operations staff only need to write a HOOK.yaml and a few lines of Python -- they don't need to understand the plugin registration chain.

## What Changed (s21 -> s22)

| Component | s21 | s22 |
|------|-----|-----|
| Extension method | Code changes only | Hook directory + code registration |
| Startup behavior | Fixed | Customizable via BOOT.md |
| Tool auditing | None | pre/post_tool_call |
| Session lifecycle | No hooks | on_session_start/end |
| Error isolation | None | All hook exceptions are non-propagating |

## Common Beginner Mistakes

### 1. Blocking the Main Loop with Slow Hook Operations

```python
# Wrong: making an external API call in pre_tool_call
def slow_audit(tool_name, args, **kw):
    requests.post("https://audit.example.com", json={...})  # 2 seconds
```

The agent waits an extra 2 seconds for every tool call.

**Fix: Put slow operations into a queue or thread. The hook itself should only perform fast operations (writing to a local file, enqueuing).**

### 2. handler.py Missing the handle Function

```python
# Wrong: handler.py
def on_event(event_type, context):  # Wrong function name
    ...
```

The system uses `getattr(module, "handle")` to find the entry function. If the name isn't `handle`, it won't be found.

**Fix: The function must be named `handle`.**

### 3. Assuming Hooks Can Modify Tool Arguments

```python
# Wrong: trying to modify args in pre_tool_call
def modify_args(tool_name, args, **kw):
    args["command"] = "echo safe"  # Won't take effect
```

The `args` the hook receives are passed by value, not by reference. Modifying them doesn't affect actual execution.

**Fix: To block execution, return `{"action": "block"}` so the system prevents the call.**

### 4. Writing Interactive Operations in BOOT.md

```markdown
# Wrong: requires user input
1. Ask the user which project to check
```

BOOT.md runs at Gateway startup when no user is present. Interactive operations will hang.

**Fix: BOOT.md should only contain automated instructions that don't require user participation.**

## Teaching Boundaries

This chapter covers four things:

1. **Gateway hooks** -- Event types, HOOK.yaml + handler.py, HookRegistry
2. **BOOT.md** -- Built-in gateway hook, startup self-check
3. **Plugin hooks** -- pre/post_tool_call, on_session_start/end
4. **Why two systems** -- Different granularity, different deployment methods, different target users

Not covered:

- `pre_api_request` / `post_api_request` -> similar to pre_tool_call, same pattern
- Plugin discovery and loading mechanism (pip entry-points) -> package management details
- Hook hot reloading -> production optimization
- Context injection via `pre_llm_call` -> advanced usage

## How This Chapter Relates to Others

- **s02**'s tool dispatch -> `pre_tool_call` / `post_tool_call` fire before and after dispatch
- **s12**'s Gateway -> Gateway hooks fire at key points in GatewayRunner
- **s15**'s scheduled tasks -> BOOT.md can check cron job status
- **s20**'s background review -> review is essentially a built-in `on_session_end` hook
- **s24**'s plugin architecture -> plugin hooks are the foundation of the plugin ecosystem

## After This Chapter, You Should Be Able to Answer

- To write a hook that logs every terminal tool execution, what files do you need?
- Why is BOOT.md executed by the agent instead of by a shell?
- Why aren't Gateway hooks and Plugin hooks merged into a single system?
- What happens if a hook throws an exception? Does the agent crash?
- Can a `pre_tool_call` hook prevent tool execution? How?

---

**One-liner: Hooks let you insert custom logic at key moments in the agent's lifecycle -- without changing core code, without affecting other features, and with non-propagating exceptions. BOOT.md is the simplest hook: a Markdown file that the agent automatically executes on startup.**
