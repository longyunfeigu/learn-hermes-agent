# s19: CLI & Web Interface

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > [ s19 ] > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The agent from s01-s17 has been running in a bare `input()`/`print()` terminal. For a real user-facing experience, you need streaming output, progress feedback, slash commands -- and a web panel so you can manage it without opening a terminal.*

![CLI and Web Dual Interface](../../illustrations/en/s19-cli-web/01-comparison-cli-web.png)

## What problem does this chapter solve

Three scenarios.

**Scenario 1: The silent wait.** You ask the agent to refactor a file. It calls 5 tools over 40 seconds. The entire time, the terminal shows nothing -- you think it's frozen, hit Ctrl+C, and it was just about to return the final result.

```text
You: Refactor parser.py for me
                            <- 40 seconds of silence
                            <- User hits Ctrl+C
(all 5 tool calls from the agent are lost)
```

**Scenario 2: The wall of text.** You ask a complex question. The model generates 2000 words. The bare CLI waits 30 seconds, then dumps all 2000 words on screen at once -- your eyes chase 3 screens of scrolling.

```text
You: Explain this system's architecture
                            <- 30 seconds of silence
Assistant: [2000 words appear all at once, scrolling 3 screens]
```

**Scenario 3: Wanting to change config without opening a terminal.** It's the weekend and you're on your phone. You want to see what scheduled tasks the agent ran yesterday or change an API key. But the agent only has a CLI entry point -- you'd need to SSH into the server.

This chapter solves all three problems:

1. **Interactive terminal** -- prompt_toolkit pins the input area at the bottom, output scrolls upward, tool calls show a spinner
2. **Streaming output** -- each token the model generates is rendered immediately, no waiting for the full reply
3. **Web management panel** -- FastAPI exposes a REST API; a React frontend handles configuration and session management

## Suggested reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- tool progress callbacks extend s02's tool call mechanism
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) -- the web panel is essentially another adapter
- [`s15-scheduled-tasks.md`](./s15-scheduled-tasks.md) -- the web panel can manage scheduled tasks

## Key terms

### What is patch_stdout

The core trick in prompt_toolkit. Normally, `print()` writes text at the cursor's current position -- if your input area is at the bottom, `print()` will disrupt it.

`patch_stdout()` intercepts all `print()` calls and redirects the output to a scrolling area above the input. **The input area never moves; output scrolls upward.**

```text
+----------------------------------+
|  [tool] terminal: ls -la    0.3s |  <- Output area (scrolls up)
|  [tool] read_file: src/...  0.1s |
|  Assistant: This directory has...|
|                                  |
+----------------------------------+
| You: _                           |  <- Input area (pinned at bottom)
+----------------------------------+
```

### What is stream_delta

In streaming mode, the model API doesn't wait until generation is complete before returning. Instead, it sends a delta (incremental text fragment) via callback for each token generated.

`stream_delta_callback` is a function the CLI registers on the agent -- every time a delta arrives, the CLI renders it to the screen immediately.

### What are slash commands

Text entered by the user that starts with `/` is not sent to the model; instead, the CLI handles it locally. For example:

- `/help` -- show help
- `/new` -- start a new session
- `/model` -- switch model
- `/tools` -- manage toolsets

Slash commands are defined through a central registry `COMMAND_REGISTRY`, with support for aliases and Tab completion.

## Minimal mental model

```text
User
  |
  +-- Terminal input
  |     |
  |     v
  |   HermesCLI
  |     +-- Slash command? -> process_command() handles locally
  |     +-- Regular message? -> run_conversation()
  |                          |
  |                          | stream_delta_callback(token)
  |                          v
  |                     _stream_delta()
  |                          | line buffer -> _cprint() -> patch_stdout -> screen
  |                          |
  |                     _on_tool_progress(event)
  |                          | spinner update / persistent line
  |
  +-- Browser
        |
        v
      FastAPI (/api/sessions, /api/config, /api/cron, ...)
        |
        +-- Reads and writes the same SQLite / config.yaml / jobs.json
```

The CLI and web panel are not two independent systems. They operate on the same data -- sessions in SQLite, configuration in config.yaml, and scheduled tasks in jobs.json.

## Part 1: Interactive terminal

### From bare CLI to TUI

The `run_cli()` from s01-s17 looks like this:

```python
while True:
    user_input = input("You: ")       # Blocks, cannot show progress simultaneously
    result = run_conversation(...)     # Waits for full completion before returning
    print(f"Assistant: {result}")      # Dumps everything at once
```

All three problems are visible in these three lines.

HermesCLI's approach:

```python
class HermesCLI:
    def __init__(self, model=None, toolsets=None, ...):
        self.streaming_enabled = config["display"].get("streaming", False)
        self._pending_input = queue.Queue()   # User input queue
        self._interrupt_queue = queue.Queue() # Interrupt queue during agent runs

    def run(self):
        with patch_stdout():   # <- all print output redirected above input area
            app = Application(
                layout=Layout(HSplit([
                    # Output area (auto-scrolling)
                    # spinner status line
                    # separator
                    # Input area (pinned at bottom)
                ])),
                key_bindings=self._build_key_bindings(),
            )
            app.run()
```

`patch_stdout()` is the key. With it, progress information `print()`-ed by the agent while it runs tools in the background appears above the input area, without disrupting the text you're typing.

### Input routing state machine

When the user presses Enter, the input isn't necessarily going to the model -- it might be answering a sudo password prompt, approving a dangerous command, or selecting an option.

```text
User presses Enter
    |
    +-- sudo_state active? -> Password goes to sudo queue
    +-- approval_state active? -> Choice goes to approval queue
    +-- clarify_state active? -> Answer goes to selection queue
    +-- Agent currently running?
    |     +-- Input is a slash command? -> Execute immediately
    |     +-- Regular text? -> Put in interrupt_queue (inserted in next turn)
    +-- Idle state -> Put in pending_input queue
```

Each modal state has its own queue. HermesCLI's `run()` loop pulls messages from `_pending_input` for processing; tools set the corresponding state and wait on the corresponding queue when they need interaction.

**Scenario: The agent is about to run `rm -rf /tmp/build`**

```text
1. The terminal tool detects a dangerous command (s09)
2. Sets _approval_state, displays the approval panel
3. The user sees the panel: "Allow rm -rf /tmp/build? [y/n]"
4. The user types y + Enter -> routed to the approval queue
5. The terminal tool receives the approval result and continues execution
6. _approval_state is cleared, input routing returns to normal
```

### Tool progress callbacks

Every time the agent calls a tool, the CLI receives two events:

```python
def _on_tool_progress(self, event_type, function_name, preview,
                      function_args, duration, is_error):
    if event_type == "tool.started":
        # Update spinner: show tool name and argument summary
        # "... terminal: pip install numpy"
        pass

    elif event_type == "tool.completed":
        # Print a persistent line to the scrolling area
        # "  [tool] terminal: pip install numpy    2.3s"
        pass
```

The spinner updates in real time -- if the agent calls 3 tools, you'll see the spinner change from `terminal` to `read_file` to `write_file`. Each completed tool becomes a persistent line in the scrolling area.

**Four display modes** (configured via `display.tool_progress`):

| Mode | Behavior |
|------|----------|
| `off` | Don't show tool progress |
| `new` | Show each tool only the first time (skip consecutive duplicates) |
| `all` | Show every call |
| `verbose` | Show + extra debug information |

## Part 2: Streaming output

### Callback registration

The core of streaming output is a callback chain:

```text
Model API (streaming mode)
    | token
    v
AIAgent._fire_stream_delta(text)
    |
    +-- stream_delta_callback -> HermesCLI._stream_delta(text)
    +-- _stream_callback -> (TTS and other consumers)
```

Registration happens when the agent is created:

```python
# At CLI startup
agent = AIAgent(
    stream_delta_callback=self._stream_delta if self.streaming_enabled else None,
)
```

If `streaming_enabled=False`, no callback is passed, and the agent waits for complete generation before returning the full text.

### Line buffering

Deltas returned by the model are text fragments of arbitrary length -- possibly half a character, a single word, or several lines. Rendering half a character directly would cause the terminal to flicker.

`_stream_delta` implements line buffering: it accumulates text until a complete line (encountering `\n`) before rendering.

```python
def _stream_delta(self, text):
    # None = turn boundary signal (tool call ended)
    if text is None:
        self._flush_stream()      # Flush the buffer
        self._reset_stream_state()
        return

    self._buffer += text
    while "\n" in self._buffer:
        line, self._buffer = self._buffer.split("\n", 1)
        self._cprint(line)  # Render above the input area via patch_stdout
```

### Turn boundaries

The agent may call multiple tools within a single conversation. Between tool calls, the agent sends `None` as a boundary signal:

```text
Model generates text -> delta("Let me check the file first")
Model calls a tool   -> delta(None)          <- turn boundary
Tool execution completes
Model continues      -> delta("The file contains...")
Model calls a tool   -> delta(None)          <- turn boundary
Tool execution completes
Model final reply    -> delta("Done with the changes,...")
```

When the CLI receives `None`: it closes the current output box, flushes the buffer, and prepares to display the next turn's tool progress.

## Part 3: Slash command system

### Central registry

All commands are defined in a single list:

```python
@dataclass
class CommandDef:
    name: str              # Canonical name: "background"
    description: str       # Help text
    category: str          # "Session" / "Configuration" / "Tools & Skills"
    aliases: tuple = ()    # Short names: ("bg",)
    args_hint: str = ""    # Argument placeholder: "<prompt>"
    cli_only: bool = False # Only available in CLI
    gateway_only: bool = False

COMMAND_REGISTRY = [
    CommandDef("new", "Start a new session", "Session", aliases=("reset",)),
    CommandDef("clear", "Clear screen and start new session", "Session", cli_only=True),
    CommandDef("history", "Show conversation history", "Session", cli_only=True),
    CommandDef("model", "Switch model or provider", "Configuration", args_hint="[name]"),
    CommandDef("tools", "Manage toolsets", "Tools & Skills", args_hint="[list|enable|disable]"),
    CommandDef("background", "Run prompt in background", "Session", aliases=("bg",), args_hint="<prompt>"),
    CommandDef("quit", "Exit", "Exit", cli_only=True, aliases=("exit",)),
    # ... 30+ commands
]
```

### Dispatch

```python
def process_command(self, command: str) -> bool:
    cmd_word = command.split()[0].lstrip("/").lower()
    resolved = resolve_command(cmd_word)  # Look up registry, resolve aliases

    if resolved.name == "quit":
        return False
    elif resolved.name == "help":
        self._show_help()
    elif resolved.name == "model":
        self._handle_model_command(command)
    elif resolved.name == "tools":
        self._handle_tools_command(command)
    # ...
    return True
```

**Why not use if-elif matching on raw strings?** Because commands have aliases. `/bg` and `/background` are the same command. The registry handles alias resolution centrally, and the dispatch logic only recognizes canonical names.

**Why `cli_only` and `gateway_only`?** Because `/clear` (clear screen) is meaningless on Telegram, and `/approve` (approval) isn't needed in the CLI (the CLI pops up an interactive panel directly).

## Part 4: Web management panel

### Not a chat interface

The web panel is not for chatting with the agent in a browser. It is the agent's **control console** -- for viewing session history, modifying configuration, and managing scheduled tasks.

Why no chat? Because the CLI's interactive experience (Tab completion, file path completion, sudo panel, inline diff) cannot be faithfully replicated in a browser. The web handles management; the CLI handles interaction.

### FastAPI backend

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Hermes Agent")

# CORS allows only localhost -- the web panel is for local use only
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Ephemeral token security

The browser and backend are on the same machine, but you still need to prevent JavaScript from other websites from secretly calling your API (CSRF).

```python
import secrets, hmac

_SESSION_TOKEN = secrets.token_urlsafe(32)  # Generated at startup

@app.middleware("http")
async def auth_middleware(request, call_next):
    if request.url.path.startswith("/api/") and path not in _PUBLIC_PATHS:
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {_SESSION_TOKEN}"
        if not hmac.compare_digest(auth.encode(), expected.encode()):
            return JSONResponse(status_code=401, detail="Unauthorized")
    return await call_next(request)
```

The token is generated at server startup and injected into the SPA's HTML via a template variable. It changes on every restart -- no persistence, no leak risk.

`hmac.compare_digest` prevents timing attacks: even if an attacker can precisely measure response times, they cannot guess the token byte by byte.

### Core API

```text
GET  /api/status                    <- Public: version, running state
GET  /api/sessions?limit=20         <- Session list (paginated)
GET  /api/sessions/search?q=...     <- Full-text search (FTS5)
GET  /api/config                    <- Read configuration
PUT  /api/config                    <- Write configuration
GET  /api/cron/jobs                 <- Scheduled task list
POST /api/cron/jobs                 <- Create a scheduled task
GET  /api/env                       <- Environment variable list
PUT  /api/env                       <- Set an environment variable
GET  /api/tools/toolsets            <- Toolset list
GET  /api/skills                    <- Skill list
```

**Scenario: Changing an API key from your phone on the weekend**

```text
1. Open http://your-server:8080 in the phone browser
2. The SPA loads, automatically carrying the injected session token
3. Tap the "Env" tab
4. Find OPENAI_API_KEY, tap "Edit"
5. PUT /api/env {"key": "OPENAI_API_KEY", "value": "sk-new-xxx"}
6. The backend writes to the .env file
7. The next time the agent starts, it automatically reads the new key
```

### How the web panel relates to other entry points

```text
               +-- CLI (prompt_toolkit)
               |     Interactive chat, streaming output, slash commands
               |
User ----------+-- Web panel (FastAPI + React)
               |     Config management, session browsing, scheduled tasks, logs
               |
               +-- Gateway adapters (Telegram / Discord / ...)
                     Multi-platform messaging
               
               All entry points share the same data:
               SQLite / config.yaml / jobs.json / skills/
```

The web panel is essentially another "adapter" -- except it doesn't go through the agent conversation loop; instead, it operates on the underlying data directly.

## What Changed (s17 -> s19)

| Component | s17 | s19 |
|-----------|-----|-----|
| CLI input | `input()` blocking | prompt_toolkit pinned input area |
| CLI output | `print()` all at once | `patch_stdout()` + streaming rendering |
| Tool progress | No feedback | Spinner + `_on_tool_progress` callback |
| Model output | Wait for full reply | `stream_delta_callback` renders token by token |
| Command system | None | `COMMAND_REGISTRY` + aliases + Tab completion |
| Modal interaction | None | sudo / approval / selection panels (queue-driven) |
| Web interface | None | FastAPI REST API + React SPA |
| Security | None | Ephemeral token + CORS localhost-only |

## Common beginner mistakes

### 1. Using print directly without patch_stdout

```python
# Wrong: print disrupts the input area
print("Tool execution complete")
```

Calling `print()` directly inside a prompt_toolkit Application writes output into the middle of the input area, breaking the layout.

**Fix: All output must go through `print()` inside a `patch_stdout()` context, or use prompt_toolkit's `print_formatted_text()`.**

### 2. Doing expensive work in the stream callback

```python
def _stream_delta(self, text):
    # Wrong: file I/O in the callback
    with open("log.txt", "a") as f:
        f.write(text)
    self._render(text)
```

`_stream_delta` is called on the model's I/O return thread. Expensive operations block subsequent token reception, causing streaming output to stutter.

**Fix: The callback should only render. Log writing should go to a queue for async processing.**

### 3. Forgetting CORS restrictions on the web API

```python
# Wrong: allow all origins
app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

Your API can read and write API keys and configuration. `allow_origins=["*"]` means any website's JavaScript can call your API -- visiting a malicious page could steal your keys.

**Fix: Allow only localhost. `allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"`**

### 4. String-comparing the token, enabling timing attacks

```python
# Wrong: ordinary string comparison
if auth_header == f"Bearer {token}":
```

Python's `==` returns False as soon as it finds the first mismatched character. An attacker can guess the token byte by byte by precisely measuring response times.

**Fix: `hmac.compare_digest()` for constant-time comparison.**

## Scope of this chapter

This chapter covers four things:

1. **prompt_toolkit TUI layout** -- pinned input area, scrolling output, modal panels
2. **Streaming output** -- stream_delta callback, line buffering, turn boundaries
3. **Slash command system** -- central registry, alias resolution, dispatch
4. **Web management panel** -- FastAPI + ephemeral token + REST API

Not covered:

- Skin engine / theme switching -> cosmetic, not a core mechanism
- React component implementation -> frontend development tutorial
- OAuth integration -> production wiring
- Voice mode UI -> covered in s18
- Rich library formatting details -> consult the documentation

## How this chapter relates to others

- **s01**'s `run_conversation()` -> HermesCLI wraps it, adding streaming and progress callbacks
- **s02**'s tool system -> tool progress callbacks extend dispatch
- **s09**'s permission system -> the approval panel connects to the CLI via the modal state machine
- **s11**'s configuration system -> the web panel reads and writes the same config.yaml
- **s12**'s Gateway -> the web panel and Gateway adapters share the same philosophy: different entry points, same data
- **s15**'s scheduled tasks -> the web panel provides a cron API to manage jobs.json

## After finishing this chapter, you should be able to answer

- Why is `patch_stdout()` foundational for the prompt_toolkit TUI? What happens without it?
- What does it mean when `_stream_delta` receives `None`? Why is this signal needed?
- Why dispatch slash commands through a registry instead of matching raw strings with if-elif?
- Why doesn't the web panel include chat functionality? What is its relationship to the CLI?
- Why must the ephemeral token be compared with `hmac.compare_digest`? What's wrong with plain `==`?

---

**One sentence to remember: The CLI uses prompt_toolkit to pin the input area and render output as a stream; the web panel uses FastAPI to expose management APIs. Both operate on the same data, with different roles -- the CLI for interaction, the web for management.**
