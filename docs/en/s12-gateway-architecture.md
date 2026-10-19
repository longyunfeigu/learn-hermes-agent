# s12: Gateway Architecture

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > [ s12 ] > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *CLI is a one-on-one chat between you and the agent. The Gateway lets the same agent serve users across a dozen platforms simultaneously. The core loop hasn't changed a single line -- what changed is where messages come from and where replies go.*

![Multi-Platform Message Routing](../../illustrations/en/s12-gateway/01-framework-routing.png)

## What problem does this chapter solve

By `s11`, you already have a fully functional single agent system. But it only has one entry point: CLI -- you type a message in the terminal, the agent replies.

Now you want this agent to also work in WeCom (Enterprise WeChat). How do you do it?

## Starting with the simplest possible implementation

Setting architecture aside, let's write the most straightforward "WeChat bot":

```python
# The simplest version: connect to WeChat directly, call the agent on every message

import aiohttp, asyncio

async def main():
    # 1. Connect to WeChat
    ws = await aiohttp.ClientSession().ws_connect("wss://openws.work.weixin.qq.com")
    await ws.send_json({
        "cmd": "aibot_subscribe",
        "body": {"bot_id": "xxx", "secret": "yyy"},
    })

    # 2. Infinite loop: receive message -> call agent -> send reply
    while True:
        msg = await ws.receive_json()
        if msg["cmd"] != "aibot_msg_callback":
            continue

        body = msg["body"]
        user_text = body["text"]["content"]
        chat_id = body["chatid"]

        # 3. Call the core loop from s01 (same function the CLI uses)
        agent = AIAgent(model="anthropic/claude-sonnet-4")
        response = agent.run_conversation(user_text)

        # 4. Send the reply back to WeChat
        await ws.send_json({
            "cmd": "aibot_send_msg",
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {"content": response},
            },
        })
```

40 lines of code, and it works. But it has three fatal problems.

## Problem 1: No memory -- every message starts a fresh conversation

The code above only passes the current message to `run_conversation`. The agent has no idea what was said before.

You say "translate hello" in WeChat and the agent replies with the translation. Then you say "now translate world," and the agent doesn't know you were translating -- because it has no history.

**Solution: Store each user's chat history and pass it to the loop on subsequent calls.**

But here's a key question: how do you know "which messages belong to the same conversation"?

If Zhang San and Li Si are both chatting with the agent on WeChat simultaneously, their messages can't be mixed together. Zhang San's "help me write code" and Li Si's "what's the weather today" are two completely independent conversations.

You need an **identifier** to distinguish different conversations. Hermes Agent calls it a **session key** -- a unique string composed of platform + chat ID + user ID:

```python
# Private chat: platform + chat type + user ID
"agent:main:wecom:dm:zhangsan"

# Group chat: platform + chat type + group ID + user ID (per-user isolation within groups)
"agent:main:wecom:group:grp_001:zhangsan"
"agent:main:wecom:group:grp_001:lisi"
```

Zhang San and Li Si are in the same group, but their session keys differ, so each has independent conversation history.

With session management added, the code becomes:

```python
sessions = {}  # session_key -> message history list

while True:
    msg = await ws.receive_json()
    body = msg["body"]

    # Generate session key
    user_id = body["from"]["userid"]
    chat_id = body["chatid"]
    chat_type = "dm" if body["chattype"] == "single" else "group"

    if chat_type == "dm":
        session_key = f"agent:main:wecom:dm:{chat_id}"
    else:
        session_key = f"agent:main:wecom:group:{chat_id}:{user_id}"

    # Retrieve this user's history; create empty list if none exists
    history = sessions.setdefault(session_key, [])

    # Append the current message
    history.append({"role": "user", "content": body["text"]["content"]})

    # Create agent with full history
    agent = AIAgent(model="...", conversation_history=history)
    response = agent.run_conversation(body["text"]["content"])

    # The agent internally appends the reply to history

    # Send back to WeChat
    await ws.send_json(...)
```

Now the agent has memory. But two more problems remain.

## Problem 2: Only connects to WeChat -- how much code changes to add Telegram?

Product says: "Can we also connect to Telegram?"

You look at Telegram's API -- it's not WebSocket, it's HTTP long polling. The message format is completely different. The user ID is called `from.id` (not `from.userid`), the chat ID is called `chat.id` (not `chatid`).

If you add if-else branches directly in the while loop:

```python
# Don't do this
while True:
    if platform == "wecom":
        msg = await ws.receive_json()
        user_id = msg["body"]["from"]["userid"]
        text = msg["body"]["text"]["content"]
        chat_id = msg["body"]["chatid"]
    elif platform == "telegram":
        update = await telegram_get_updates()
        user_id = str(update["message"]["from"]["id"])
        text = update["message"]["text"]
        chat_id = str(update["message"]["chat"]["id"])
    elif platform == "discord":
        ...  # Yet another completely different format
```

Every new platform balloons the loop. 17 platforms means 17 branches. And the logic for "how to connect," "how to receive messages," and "how to send replies" is all tangled together.

**Solution: Let each platform handle its own "translation," then hand off to a unified format.**

This is where **platform adapters** come from. Each adapter does two things:

1. **Receive platform message -> translate to unified format** (inbound)
2. **Take reply text -> translate to platform format and send** (outbound)

The unified format in Hermes Agent is called `MessageEvent`:

```python
@dataclass
class MessageEvent:
    message_id: str        # "msg_001"
    text: str              # "Check the weather for me"
    source: SessionSource  # Where it came from (platform, chat ID, user ID)
    message_type: str      # "text", "photo", "voice", ...
```

```python
@dataclass
class SessionSource:
    platform: str    # "wecom", "telegram", "discord", ...
    chat_id: str     # Chat identifier
    chat_type: str   # "dm" or "group"
    user_id: str     # Who sent the message
```

Whether it's WeChat or Telegram, after translation it's the same `MessageEvent`. Downstream code doesn't need to know which platform the message came from.

The WeChat adapter's translation logic:

```python
class WeComAdapter:
    """WeCom adapter: connects to WeChat, receives messages, translates, sends replies."""

    async def connect(self):
        """Connect to the WeCom WebSocket."""
        self._ws = await session.ws_connect("wss://openws.work.weixin.qq.com")
        await self._ws.send_json({
            "cmd": "aibot_subscribe",
            "body": {"bot_id": self._bot_id, "secret": self._secret},
        })
        # Start background listener
        asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Continuously read WeChat messages, translate to MessageEvent, pass to callback."""
        while True:
            raw = await self._ws.receive_json()
            if raw["cmd"] == "aibot_msg_callback":
                event = self._translate(raw["body"])
                await self._on_message(event)  # This callback is registered from outside

    def _translate(self, body: dict) -> MessageEvent:
        """WeChat format -> unified format. This is the adapter's core job."""
        return MessageEvent(
            message_id=body["msgid"],
            text=body["text"]["content"],
            source=SessionSource(
                platform="wecom",
                chat_id=body["chatid"],
                chat_type="dm" if body["chattype"] == "single" else "group",
                user_id=body["from"]["userid"],
            ),
            message_type="text",
        )

    async def send(self, chat_id: str, content: str):
        """Unified reply text -> WeChat format, send out."""
        await self._ws.send_json({
            "cmd": "aibot_send_msg",
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {"content": content[:4000]},
            },
        })
```

If you want to add Telegram, write a `TelegramAdapter` with different translation logic but producing the exact same `MessageEvent` format. **Not a single line of downstream code needs to change.**

The structure now looks like:

```text
WeComAdapter ----translate----> MessageEvent ----> find session -> call loop -> reply
TelegramAdapter --translate---> MessageEvent ---->  same as above
DiscordAdapter ---translate---> MessageEvent ---->  same as above
```

The middle part -- "find session -> call loop -> reply" -- is identical for all platforms. Hermes Agent wraps it into a single function and gives it a name: **`_handle_message`**.

When each adapter starts, it registers this function as its callback. After translating a received message, it calls the function without needing to know what happens inside.

```python
# At startup
wecom_adapter._on_message = handle_message    # Register callback
telegram_adapter._on_message = handle_message  # Same function

# At runtime
# WeChat message arrives -> WeComAdapter._listen_loop -> _translate -> handle_message(event)
# Telegram message arrives -> TelegramAdapter._poll_loop -> _translate -> handle_message(event)
```

So who manages "starting all adapters" and "providing this `handle_message`"?

## Naturally arriving at GatewayRunner

You now have multiple adapters and need someone to do three things:

1. **At startup**: Iterate through configuration, connect all enabled adapters
2. **At runtime**: After receiving a `MessageEvent`, find the session, call the loop, return the reply
3. **At shutdown**: Gracefully disconnect all connections

Wrap these three responsibilities into a class, and you get `GatewayRunner`:

```python
class GatewayRunner:
    def __init__(self, config):
        self.adapters = {}       # platform -> adapter
        self.session_store = {}  # session_key -> message history

    async def start(self):
        """Start all configured platform adapters."""
        for platform, platform_config in config.platforms.items():
            if not platform_config.enabled:
                continue

            # Create adapter
            if platform == "wecom":
                adapter = WeComAdapter(platform_config)
            elif platform == "telegram":
                adapter = TelegramAdapter(platform_config)
            # ...

            # Register handle_message as callback
            adapter._on_message = self._handle_message

            # Connect
            await adapter.connect()
            self.adapters[platform] = adapter

    async def _handle_message(self, event: MessageEvent) -> str:
        """
        All platform messages ultimately arrive here.
        This function doesn't know whether the message came from WeChat or Telegram --
        it only sees the MessageEvent.
        """
        # 1. Generate session key
        src = event.source
        if src.chat_type == "dm":
            session_key = f"agent:main:{src.platform}:dm:{src.chat_id}"
        else:
            session_key = f"agent:main:{src.platform}:group:{src.chat_id}:{src.user_id}"

        # 2. Retrieve or create agent (cached by session key for reuse)
        if session_key not in self.agents:
            self.agents[session_key] = AIAgent(model="...", session_id=session_key)
        agent = self.agents[session_key]

        # 3. Reload the latest history from the database every time
        #    Why not use the agent's internal history? Because it may have been
        #    modified externally (e.g., user ran /undo to delete the last turn,
        #    or context compression was triggered)
        history = self.session_store.load_transcript(session_key)

        # 4. Call the core loop with the latest history
        response = agent.run_conversation(event.text, conversation_history=history)

        return response

    async def stop(self):
        for adapter in self.adapters.values():
            await adapter.disconnect()
```

Note two design decisions:

**Agent instances are cached by session key for reuse, not created anew for every message.** Zhang San sends 10 messages, all handled by the same agent instance. But Zhang San on WeChat and Bob on Telegram have different session keys, so they get different agent instances.

**History is reloaded from the database each time, not relied upon from the agent's internal memory.** This is because history can be modified externally -- the user ran `/undo` (deleting the last turn), `/compress` (compressing context), or the session expired and was auto-reset. If the agent only used its internally cached history, these modifications would be lost.

**`GatewayRunner` is not an abstract concept you need to memorize. It's something you would naturally write yourself** -- when you have multiple adapters that need unified management, you naturally consolidate the "start," "route," and "shutdown" logic into one place.

Now let's look at the full structure:

```text
GatewayRunner
  |
  +-- At startup: create adapters, register callbacks, connect to platforms
  |
  +-- Agent cache pool (session key -> agent instance)
  |
  +-- WeComAdapter (WeChat)
  |    +-- Receives WeChat message -> _translate -> calls GatewayRunner._handle_message
  |
  +-- TelegramAdapter (Telegram)
  |    +-- Receives Telegram message -> _translate -> calls GatewayRunner._handle_message
  |
  +-- _handle_message (convergence point for all messages)
       +-- Find session -> retrieve/create agent -> load history from database
         -> agent.run_conversation(message, history) -> return reply
```

**`agent.run_conversation()` has no idea where the message came from.** Whether it's WeChat or Telegram, the call is exactly the same. This is what `s00` meant by "the only difference between Gateway and CLI scenarios is the entry and exit points; the core loop is identical."

## Problem 3: What if Zhang San sends another message while the agent is thinking?

Zhang San sent "Write me a sorting algorithm" and the agent started thinking. 10 seconds later, Zhang San sends "Use Python."

If you create another agent instance for the second message, two instances running simultaneously and reading/writing Zhang San's session history will produce garbled replies.

But you also can't discard the second message -- the user genuinely wants to add a clarification.

Hermes Agent's approach: **Only one agent runs per session at a time. New messages are buffered and processed after the current agent finishes.**

```python
# Core logic in the adapter base class (simplified)

active_sessions = {}   # session_key -> interrupt signal
pending_messages = {}  # session_key -> buffered next message

async def handle_message(self, event):
    session_key = build_session_key(event.source)

    if session_key in active_sessions:
        # An agent is already running for this session
        # Buffer the new message (only keep the last one; earlier ones get overwritten)
        pending_messages[session_key] = event
        # Send an interrupt signal to the running agent
        active_sessions[session_key].set()
        return

    # No active agent -> mark as active, start processing
    active_sessions[session_key] = asyncio.Event()
    await self._process_message_background(event, session_key)
```

After finishing one message, check for buffered messages:

```python
# At the end of _process_message_background
if session_key in pending_messages:
    next_event = pending_messages.pop(session_key)
    del active_sessions[session_key]
    # Process the next message immediately (not re-queuing, but calling directly)
    await self._process_message_background(next_event, session_key)
else:
    del active_sessions[session_key]
```

### What does the interrupt signal actually do?

"Sending an interrupt signal" isn't a vague statement. `agent.interrupt()` does one very specific thing: **sets the `_interrupt_requested = True` flag.**

The agent's core loop (the while loop from `s01`) checks this flag at many points:

```python
# 1. Waiting for LLM response stream -> stop reading immediately
with client.responses.stream(**api_kwargs) as stream:
    for event in stream:
        if self._interrupt_requested:
            break  # Stop waiting for remaining tokens from the LLM

# 2. Executing multiple tool calls sequentially -> skip the rest
for i, tool_call in enumerate(tool_calls):
    execute(tool_call)
    if self._interrupt_requested and i < len(tool_calls):
        # Skip unexecuted tools, fill in a "skipped" placeholder result
        for skipped in tool_calls[i:]:
            messages.append({
                "role": "tool",
                "content": "[Tool execution skipped -- user sent a new message]",
                "tool_call_id": skipped.id,
            })
        break

# 3. Also checked at the start of each loop iteration
while iteration < max_iterations:
    if self._interrupt_requested:
        break  # Exit loop, return whatever results exist so far
```

So interruption isn't "force-killing a process" but rather **gracefully exiting at the next checkpoint** -- stop waiting on the stream, skip remaining tools, exit the loop.

### Is interrupted content lost? Does the conversation stay coherent?

**Nothing is lost, and coherence is maintained.**

After being interrupted, the agent returns `result["messages"]` as normal, containing everything produced up to the interruption point: partially generated reply, executed tool calls with results, and skipped tool calls with placeholder tool messages (placeholders satisfy the OpenAI API's hard requirement that "every tool_call must have a tool response"). The Gateway `append_to_transcript`s all of this into the database.

On the next round processing the new message, `conversation_history` is reloaded from the database. The new agent sees the full thread:

```text
user:      "Write me a sorting algorithm"
assistant: "Sure, I'd recommend quicksort. First..."            <-- partial content generated before interruption
tool_call: search_algorithm("sorting")                          <-- executed
tool:      "[search results...]"
tool_call: write_file("sort.py", ...)                           <-- interrupted, skipped
tool:      "[Tool execution skipped -- user sent a new message]"
user:      "Use Python"                                          <-- new message
```

The agent can see the traces of being interrupted -- it knows where the previous turn left off and what still needs doing -- so it can pick up coherently rather than acting like it "forgot what it was doing."

### Walking through a concrete scenario

```text
Zhang San sends "Write me a sorting algorithm"
  -> No entry for Zhang San in active_sessions -> mark active, start background task
  -> Agent starts calling the LLM...

Zhang San sends "Use Python" (agent is waiting for LLM streaming response)
  -> Zhang San found in active_sessions -> buffer this message
  -> Call agent.interrupt("Use Python")
  -> agent._interrupt_requested = True
  -> Agent checks flag at next stream event -> break out of stream
  -> Agent finishes current loop, returns partial reply
  -> Partial reply sent to Zhang San
  -> Check pending_messages -> found "Use Python"
  -> Load latest history from database (includes message 1 and partial reply) -> process message 2

Li Si sends "What's the weather today" (at the same time as Zhang San)
  -> Different session key -> completely independent background task, runs in parallel with Zhang San
```

Note one detail: `pending_messages` keeps only **the last message** (direct assignment, not appending to a list). If Zhang San fires off three messages in rapid succession -- "Use Python," "make it quicksort," "add comments" -- only "add comments" gets processed. This is intentional -- on messaging platforms, multiple messages sent in rapid succession by a user are usually elaborating on the same idea. Processing just the last one is sufficient.

## Walking through the complete flow with WeChat

Now let's string all the concepts together. You send a private message to the Hermes Agent bot in WeCom: **"Check today's weather for me."**

### 1. WeChat server pushes message to the adapter

WeCom pushes a JSON over WebSocket:

```json
{
    "cmd": "aibot_msg_callback",
    "body": {
        "msgid": "msg_001",
        "msgtype": "text",
        "from": {"userid": "zhangsan"},
        "chatid": "zhangsan",
        "chattype": "single",
        "text": {"content": "Check today's weather for me"}
    }
}
```

### 2. Adapter translates to MessageEvent

`WeComAdapter._translate()` converts WeChat's JSON into the unified format:

```python
MessageEvent(
    message_id="msg_001",
    text="Check today's weather for me",
    source=SessionSource(platform="wecom", chat_id="zhangsan",
                         chat_type="dm", user_id="zhangsan"),
    message_type="text",
)
```

WeChat-specific fields like `cmd`, `headers`, and `req_id` are gone -- `MessageEvent` retains only the information common across all platforms.

### 3. Queue check

The adapter checks `active_sessions`: no message currently being processed for `zhangsan`. Mark as active, proceed.

### 4. GatewayRunner takes over

`_handle_message(event)` is called:

```python
# Generate session key
session_key = "agent:main:wecom:dm:zhangsan"

# Retrieve cached agent (create new one if this is Zhang San's first message)
agent = agents.get(session_key) or AIAgent(model=model, ...)

# Load latest history from database (not relying on agent's internal memory)
history = session_store.load_transcript(session_key)

# Call core loop with history (same method the CLI calls)
response = agent.run_conversation(user_message, conversation_history=history)
# -> "Today in Beijing it's sunny, high of 28C..."
```

### 5. Reply sent back to WeChat

`GatewayRunner` returns the reply text, and `WeComAdapter.send()` wraps it in WeChat format:

```json
{
    "cmd": "aibot_send_msg",
    "body": {
        "chatid": "zhangsan",
        "msgtype": "markdown",
        "markdown": {"content": "Today in Beijing it's sunny, high of 28C..."}
    }
}
```

The user sees the agent's reply in the WeCom client.

### If you also connected Telegram

A Telegram user sends a message. `TelegramAdapter` receives it, translates it to a `MessageEvent` (`platform="telegram"`), and calls the same `_handle_message`. The only difference is the session key becomes `agent:main:telegram:dm:12345`.

**Not a single line of core loop code changed.**

## Hermes Agent's unique design choices

The above implementation is a simplified teaching version. The real Hermes Agent also handles several real-world issues that can't be ignored:

### 1. WeChat message fragmentation

The WeCom client automatically truncates long messages at 4000 characters. If a user sends 6000 characters of text, WeChat splits it into two messages.

If the agent responds to each "half-message" separately, the replies will be incoherent.

The adapter solves this with a **time window**: after receiving the first fragment, it waits 0.6 seconds. If a second fragment arrives and the first was close to 4000 characters, it continues waiting up to 2 seconds. After the timeout, all fragments are concatenated and treated as a single complete message.

### 2. Automatic session expiration

In the CLI scenario, closing the terminal ends the conversation. But the Gateway is a long-running service -- a user's context from three months ago is still there.

Hermes Agent supports two auto-reset modes:

- **Idle timeout**: No new messages for over 24 hours -> automatically starts a new session on the next message
- **Daily reset**: All sessions cleared at 4 AM daily (memory isn't lost; only conversation history restarts)

### 3. Crash recovery

If the Gateway crashes and restarts, in-flight requests may be in a half-completed state.

On startup, it doesn't attempt to recover these half-completed states. Instead, sessions that were active within the last 120 seconds are marked as "suspended" and auto-reset on the next incoming message. **Starting clean is far safer than recovering dirty state.**

### 4. Two WeChat integration modes

WeCom offers two bot integration methods, and Hermes Agent has an adapter for each:

| | WebSocket Bot (`WeComAdapter`) | HTTP Callback (`WecomCallbackAdapter`) |
|---|---|---|
| Connection method | Persistent WebSocket, real-time bidirectional | HTTP server, receives encrypted XML callbacks |
| Media | Images, video, voice, files all supported | Text only |
| Multi-app | Single bot | Can connect multiple custom apps |
| Use case | Quick AI Bot integration | Enterprise custom apps needing fine-grained control |

The two modes behave differently externally, but both output the same `MessageEvent`. They are completely transparent to `GatewayRunner`.

## How it connects to the main loop

As with all previous chapters, the Gateway is assembled *outside* the core loop. The core loop doesn't know the Gateway exists.

```text
CLI launch:
  User input -> create AIAgent -> agent.run_conversation(user input)

Gateway launch:
  1. load_config()         -> read which platforms to enable, their tokens
  2. GatewayRunner(config) -> create runner
  3. runner.start()        -> start all adapters, register callbacks
  4. Wait for messages     -> adapter translates -> _handle_message
                              -> create AIAgent -> agent.run_conversation(message text)
```

Both paths ultimately call `agent.run_conversation()`. AIAgent only receives parameters: model, message history. It doesn't care who the caller is.

## Most common beginner mistakes

### 1. Putting platform differences inside the core loop

"WeChat markdown is different from Telegram's -- just add an if in the loop?" -- Don't. Format conversion is the adapter's `send()` responsibility. The core loop only outputs generic text.

### 2. Creating a new agent for every message

The user sends three messages in a row. If each creates its own agent instance, they all read and write the same history simultaneously, producing conflicting replies. Messages for the same session key must be serialized.

### 3. Insufficient session key dimensions

If the key is only `platform:chat_id`, everyone in the same group shares a conversation. Usually you need to add `user_id` for per-user isolation within groups -- unless you intentionally want group members to share context.

### 4. Ignoring message deduplication

During network instability, the same message may be pushed twice. All adapters need to deduplicate by `message_id`.

## Scope of this chapter

This chapter thoroughly covers three things:

1. **Why adapters are needed** -- Derived from "the simplest possible implementation," not defined in a vacuum
2. **What GatewayRunner does** -- Start adapters, route messages, call the loop. That's it
3. **How sessions are isolated** -- Session key generation rules, why different users in the same group have different keys

Deferred topics:

- Specific implementation of each platform adapter -> the pattern is the same; understanding the WeChat one is enough
- How scheduled tasks deliver results to different platforms -> `s15`
- Terminal backend abstraction (Docker / SSH) -> `s14`
- Gateway-level hooks -> similar to `s08`

If the reader can go from "a while loop that only connects to WeChat" to understanding "why we need adapters, why we need a unified message format, and why we need a centralized router," this chapter has served its purpose.

## After this chapter, you should be able to answer

- If you only connect to one platform, do you need GatewayRunner? At what point do you start needing it?
- What problem does `MessageEvent` solve? Without it, what code needs to change when adding a new platform?
- Do Zhang San and Li Si in the same WeChat group have the same session key? Why or why not?
- What happens when Zhang San sends another message while the agent is thinking?
- Does `agent.run_conversation()` know whether the message came from WeChat or CLI?

---

**In one sentence: The Gateway started from one question -- "how do I get the same agent working in WeChat?" Then you discover you need session isolation (session key), format unification (MessageEvent), and a central place to manage multiple platforms (GatewayRunner). These aren't things an architect dreamed up in a vacuum -- they grew naturally from concrete problems.**
