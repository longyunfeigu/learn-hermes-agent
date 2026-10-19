# s13: Platform Adapters

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > [ s13 ] > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *s12 explained why you need adapters. This chapter shows you how to write one.*

![Platform Adapter Pattern](../../illustrations/en/s13-platform-adapters/01-framework-adapter-pattern.png)

## What problem does this chapter solve

s12 used WeCom (Enterprise WeChat) as an example to demonstrate the three core responsibilities of an adapter: connect to the platform, translate messages, and send replies. But that was just one adapter.

When you actually go to connect a second or third platform, you'll encounter a series of new problems:

- Each platform has a different connection method. WeCom uses WebSocket while personal WeChat uses HTTP long polling -- completely different protocols.
- A user sends 5000 characters of text, and the platform client automatically splits it into two messages. If you process the two "half-messages" separately, the agent's replies will be incoherent.
- A user sends an image or voice message. You need to download it, decrypt it, cache it, let the agent use it, and when replying, encrypt and upload it back.
- WebSocket connections drop and need reconnecting. HTTP requests time out and need retrying. The same message might be pushed twice.

These problems aren't unique to any one platform -- **every** adapter encounters them. You need a base class to extract the commonalities so each adapter only handles its platform-specific parts.

## Suggested reading

- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) -- How adapters came to be and GatewayRunner's routing logic
- [`data-structures.md`](./data-structures.md) -- Full field definitions for `MessageEvent` and `SessionSource`
- [`glossary.md`](./glossary.md) -- Terminology for adapters, session keys, etc.

## Key terminology

### What is BasePlatformAdapter

The abstract base class for all platform adapters. It defines what an adapter **must do** (connect, send messages) and what it **can do** (send images, send voice), but doesn't care about **how** -- the specifics are left to subclasses.

### What is text batching

Platform clients automatically truncate long text when sending (WeCom at 4000 characters, personal WeChat at 1500 characters). A single user message becomes two or even three messages pushed to you. The adapter needs to merge them back into one before handing it to GatewayRunner.

### What is deduplication

During network instability, the same message may be pushed by the platform twice. The adapter uses `message_id` to track processed messages and discards duplicates.

### What is media caching

Media URLs provided by platforms are usually temporary and may require decryption. When the adapter receives an image or voice message, it immediately downloads, decrypts, and stores it in a local cache directory, passing the local path to the agent.

## Minimal mental model

The complete lifecycle of an adapter:

```text
                   connect()
                      |
                      v
         +-----------------------------+
         |   Platform message listener  |
         |                             |
         |  Platform JSON/XML          |
         |      |                      |
         |      v                      |
         |  _translate()               |
         |      |                      |
         |      v                      |
         |  Deduplication -> Batching  |
         |      |                      |
         |      v                      |
         |  handle_message(event)  ----+--> GatewayRunner
         |                             |
         |  send(chat_id, text)  <-----+--- GatewayRunner
         |      |                      |
         |      v                      |
         |  Format conversion ->       |
         |     Platform API            |
         +-----------------------------+
                      |
                      v
                 disconnect()
```

Key insight: **The left side's "platform JSON -> _translate() -> MessageEvent" and the right side's "generic text -> format conversion -> platform API" are the only parts each adapter needs to write.** The deduplication, batching, and routing in the middle are all shared.

## Key data structures

### BasePlatformAdapter

```python
class BasePlatformAdapter(ABC):

    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self._on_message = None   # Injected by GatewayRunner at startup
        self._running = False

    # --- Three methods that must be implemented ---

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def send(self, chat_id: str, content: str) -> bool: ...

    # --- Two optional media methods (default returns False = not supported) ---

    async def send_image(self, chat_id: str, image_path: str) -> bool:
        return False

    async def send_voice(self, chat_id: str, audio_path: str) -> bool:
        return False

    # --- No need to override ---

    async def handle_message(self, event: MessageEvent):
        if self._on_message:
            await self._on_message(event)
```

The three required methods are what **every platform has** -- regardless of the platform, you always need to connect, disconnect, and send messages. The two optional methods default to `False`; platforms that support them simply override.

### MessageDeduplicator

```python
class MessageDeduplicator:
    """Deduplicates by message_id with FIFO eviction of old records."""

    def __init__(self, max_size: int = 1000):
        self._seen: set[str] = set()
        self._order: list[str] = []
        self._max_size = max_size

    def is_duplicate(self, message_id: str) -> bool:
        if message_id in self._seen:
            return True
        self._seen.add(message_id)
        self._order.append(message_id)
        if len(self._order) > self._max_size:
            old_id = self._order.pop(0)
            self._seen.discard(old_id)
        return False
```

### TextBatcher

```python
class TextBatcher:
    """Buffers text fragments, merges them into a single MessageEvent after a quiet period."""

    async def enqueue(self, session_key, text, event, split_threshold=3900):
        self._buffers[session_key].append(text)
        # Close to the truncation threshold -> wait longer (a continuation is almost certain)
        delay = 2.0 if len(text) >= split_threshold else 0.6
        # Cancel the previous timer, restart the countdown
        self._restart_flush_timer(session_key, delay)

    async def _flush(self, session_key):
        merged_text = "".join(self._buffers.pop(session_key))
        event.text = merged_text
        await self._callback(event)
```

## Minimal implementation: building a WeCom adapter from scratch

Using the WeCom (Enterprise WeChat) WebSocket Bot to demonstrate the full lifecycle.

### Step 1: Connect

The WeCom Bot sends and receives messages over a persistent WebSocket. Connection requires subscribing (`aibot_subscribe`), then maintaining a heartbeat.

```python
class WeComAdapter(BasePlatformAdapter):
    def __init__(self, bot_id: str, secret: str):
        super().__init__("wecom")
        self._bot_id = bot_id
        self._secret = secret
        self._ws_url = "wss://openws.work.weixin.qq.com"
        self._ws = None
        self._dedup = MessageDeduplicator()

    async def connect(self) -> bool:
        session = aiohttp.ClientSession()
        self._ws = await session.ws_connect(self._ws_url)

        # Subscribe: tell WeCom "I'm this bot, start pushing messages to me"
        await self._ws.send_json({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": str(uuid.uuid4())},
            "body": {"bot_id": self._bot_id, "secret": self._secret},
        })

        self._running = True
        asyncio.create_task(self._listen_loop())
        asyncio.create_task(self._heartbeat_loop())
        return True
```

### Step 2: Receive messages and translate

A WeCom incoming message looks like this:

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

The listener loop continuously reads WebSocket messages, filters for `aibot_msg_callback`, and translates to `MessageEvent`:

```python
    async def _listen_loop(self):
        while self._running:
            try:
                raw = await self._ws.receive_json()
                if raw.get("cmd") != "aibot_msg_callback":
                    continue

                body = raw["body"]
                msg_id = body.get("msgid", "")

                # Deduplication
                if self._dedup.is_duplicate(msg_id):
                    continue

                event = self._translate(body)
                await self.handle_message(event)

            except Exception as exc:
                if self._running:
                    print(f"  [wecom] listen error: {exc}")
                    break  # Let the outer reconnection logic take over

    def _translate(self, body: dict) -> MessageEvent:
        """WeCom JSON -> unified format. This is the adapter's core job."""
        # Extract text: direct for text type, concatenate all fragments for mixed type
        if body.get("msgtype") == "mixed":
            parts = [
                item["text"]["content"]
                for item in body["mixed"]["msg_item"]
                if item.get("msgtype") == "text"
            ]
            text = "\n".join(parts)
        else:
            text = body.get("text", {}).get("content", "")

        user_id = body.get("from", {}).get("userid", "")
        chat_type = "dm" if body.get("chattype") == "single" else "group"

        return MessageEvent(
            message_id=body.get("msgid", ""),
            text=text,
            source=SessionSource(
                platform="wecom",
                chat_id=body["chatid"],
                chat_type=chat_type,
                user_id=user_id,
            ),
        )
```

### Step 3: Send replies

```python
    async def send(self, chat_id: str, content: str) -> bool:
        # WeCom message length limit: 4000 characters
        content = content[:4000]

        await self._ws.send_json({
            "cmd": "aibot_send_msg",
            "headers": {"req_id": str(uuid.uuid4())},
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        })
        return True
```

### Step 4: Heartbeat and reconnection

WeCom requires a heartbeat every 30 seconds, or the server disconnects.

```python
    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._ws.send_json({"cmd": "ping"})
            except Exception:
                break  # Connection lost, let reconnection logic handle it
```

Reconnection with exponential backoff:

```python
    async def run_with_reconnect(self):
        """Main loop with automatic reconnection."""
        backoff = [2, 5, 10, 30, 60]
        attempt = 0

        while self._running:
            try:
                await self.connect()
                attempt = 0  # Connected, reset counter

                # Wait for the listener loop to end (meaning disconnection)
                while self._running and not self._ws.closed:
                    await asyncio.sleep(1)

            except Exception as exc:
                print(f"  [wecom] connection error: {exc}")

            if not self._running:
                break

            delay = backoff[min(attempt, len(backoff) - 1)]
            print(f"  [wecom] reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            attempt += 1
```

### Step 5: Disconnect

```python
    async def disconnect(self):
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
```

**The entire adapter is about 100 lines of core code.** It does exactly what the mental model diagram shows: connect, receive messages, translate, send replies, heartbeat, reconnect on disconnect.

## Text batching: a pitfall every adapter encounters

The WeCom client automatically truncates long text at 4000 characters. The user thinks they sent "one message," but the platform pushes you two.

If you process them separately, the first one hasn't finished processing when the second arrives -- triggering the interrupt mechanism from s12. The agent sees a half-message.

**Solution: Time-window merging.**

But there's a fundamental challenge: **you can't definitively tell whether two quickly arriving messages are "one message split apart" or "two independent messages."** TextBatcher doesn't try to distinguish -- it uses two heuristics to decide how long to wait:

**Heuristic 1: Look at the length.** If the received text is close to the platform's truncation point (WeCom >= 3900 characters), it's very likely truncated -- a continuation is almost certainly coming. Wait longer (2 seconds). If the length is well below the truncation point, it's probably complete. Wait less (0.6 seconds).

**Heuristic 2: Look at the interval.** No human can send two independent messages within 0.6 seconds. If another message arrives within 0.6 seconds, it's either a platform split or the user continuing the same thought -- either way, merging won't cause problems.

Walking through three scenarios:

```text
Scenario 1: Long text was truncated (most common)

User sends 6000 chars -> WeCom splits into two messages

t=0.000s  Receive first fragment (3998 chars)
          -> 3998 >= 3900 (near truncation point) -> wait 2.0 seconds
t=0.050s  Receive second fragment (2002 chars)
          -> 2002 < 3900 -> restart timer at 0.6 seconds
t=0.650s  No new messages within 0.6s -> merge into 6000 chars, hand to agent

Scenario 2: User sent a short message (simplest)

t=0.000s  Receive "hello" (5 chars)
          -> 5 is well below 3900 -> wait 0.6 seconds
t=0.600s  No new messages -> hand directly to agent

Scenario 3: User rapidly sends two unrelated messages (rare)

t=0.000s  Receive "check the weather" (17 chars) -> wait 0.6 seconds
t=0.300s  Receive "also remind me about the meeting" (32 chars) -> restart 0.6 seconds
t=0.900s  No new messages -> merge into "check the weatheralso remind me about the meeting"
          -> Merged, but the agent can still understand it -- better than processing separately
```

**Can this design produce false positives?** Yes. Scenario 3 is a false positive -- two independent messages get merged. But sending two unrelated messages within 0.6 seconds is extremely rare in practice, and the merged result is still understandable by the agent. Conversely, if you don't merge, the half-message problem in Scenario 1 is fatal.

Key parameters:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Default quiet period | 0.6 seconds | Humans can't type two independent messages this fast |
| Near truncation threshold | 2.0 seconds | Text length >= 3900 chars -> likely truncated, wait for continuation |
| Truncation threshold | 3900 (WeCom) / 1400 (WeChat) | Slightly below actual platform limits (4000/1500) for safety margin |

### TextBatcher implementation mechanism

The "timer" is not a timer object but an **async task that sleeps then flushes**. "Resetting the timer" means **cancelling the old task and creating a new one**.

TextBatcher internally has just three dictionaries:

```python
_buffers = {}   # session_key -> ["fragment1", "fragment2", ...]  buffer
_events  = {}   # session_key -> latest MessageEvent              preserve metadata
_tasks   = {}   # session_key -> a sleeping async task            "timer"
```

Each time a message arrives (`enqueue`), four steps happen:

```python
# 1. Store text in the buffer
_buffers[key].append(text)

# 2. If an old task is sleeping -> cancel it
#    The cancelled task won't proceed to "take buffer -> merge -> hand off"
if old_task and not old_task.done():
    old_task.cancel()

# 3. Determine wait time based on text length
delay = 2.0 if len(text) >= 3900 else 0.6

# 4. Create new task: sleep(delay) then flush
_tasks[key] = create_task(_flush_after(key, delay))
```

What `_flush_after` does:

```python
async def _flush_after(key, delay):
    await asyncio.sleep(delay)   # Wait here
    # ^ If cancelled, sleep raises CancelledError; nothing below executes

    chunks = _buffers.pop(key)           # Take out all fragments
    event.text = "".join(chunks)         # Merge into one
    await callback(event)                # Hand to GatewayRunner
```

**Why must the old task be cancelled when a new message arrives?** Because the old task doesn't know there's new text in the buffer. If you let it continue, it would fire when its countdown ends and take the buffer -- but the buffer is now managed by the new task, creating a situation where two tasks fight over the same buffer. Cancelling the old task lets the new task take full responsibility for "waiting until quiet, then handing over all fragments together."

Complete flow diagram:

```text
Receive a message(text)
       |
       v
  Store in buffer
       |
       v
  Old task sleeping?
       |          |
      Yes         No
       |          |
       v          |
  cancel(old)     |
  Old task won't  |
  flush           |
       |          |
       +----------+
       v
  len(text) >= 3900?
       |          |
      Yes         No
       |          |
       v          v
  delay=2.0s   delay=0.6s
       |          |
       +----------+
       v
  Create new task: sleep(delay)
       |
       |  New message arrives during sleep?
       |          |
      Yes         No (sleep completes)
       |          |
       v          v
  Back to top   Take all fragments, merge
 (old task      Hand to GatewayRunner
  cancelled)
```

In one sentence: **Every incoming message restarts the countdown; only when the countdown finishes does the batch get handed off.**

This logic is virtually identical across the WeCom, personal WeChat, Telegram, and Discord adapters. The only difference is the truncation threshold.

## Media handling: download, decrypt, cache

Text messages only involve "translate" and "send." Media messages add "download and decrypt" on the way in and "encrypt and upload" on the way out.

### Inbound: platform -> download -> decrypt -> local cache

WeCom image messages include a `url` and `aeskey`. The URL downloads an encrypted file that needs to be decrypted with the aeskey:

```python
async def _download_and_decrypt(self, media: dict) -> str | None:
    """Download and decrypt a WeCom media file, return the local cache path."""
    url = media.get("url")
    aeskey_b64 = media.get("aeskey")
    if not url:
        return None

    # 1. Download encrypted file
    async with aiohttp.ClientSession() as session:
        resp = await session.get(url)
        encrypted = await resp.read()

    # 2. Decrypt (AES-256-CBC, key is also the IV)
    if aeskey_b64:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aeskey_b64)  # 32 bytes
        cipher = Cipher(algorithms.AES(key), modes.CBC(key))
        decryptor = cipher.decryptor()
        raw = decryptor.update(encrypted) + decryptor.finalize()
        # PKCS#7 unpadding
        pad_len = raw[-1]
        data = raw[:-pad_len]
    else:
        data = encrypted

    # 3. Cache locally
    cache_dir = HERMES_HOME / "cache" / "images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.jpg"
    path = cache_dir / filename
    path.write_bytes(data)
    return str(path)
```

### Why download immediately in the adapter

WeCom media URLs are temporary. If you store the URL in the MessageEvent but don't download immediately, by the time the agent gets around to analyzing the image, the URL may have expired.

**Rule: Download media files to local cache immediately upon receipt. Store the local path in the MessageEvent.**

### Outbound: agent -> encrypt -> chunked upload -> send message

WeCom media upload is a three-step process:

```text
1. aibot_upload_media_init   -> Tell server "I'm uploading a file of size X"
2. Send chunks (512KB each)  -> Large files split into chunks sent one by one
3. aibot_upload_media_finish -> Upload complete, receive media_id
4. aibot_send_msg            -> Send message using the media_id
```

Media upload varies significantly across platforms:

| | WeCom | Personal WeChat |
|---|---|---|
| Encryption | AES-256-CBC | AES-128-ECB |
| Key size | 32 bytes | 16 bytes |
| Upload | 512KB chunks | CDN direct upload |
| Image limit | 10 MB | -- |
| Voice format | AMR only | Silk only |

But to GatewayRunner, these differences are encapsulated behind the `send_image()` method. It just calls the method without caring about the encryption and upload protocols inside.

## Personal WeChat adapter: same pattern, different protocol

WeCom uses WebSocket; personal WeChat uses HTTP long polling. But the adapter structure is exactly the same.

| | WeCom (`WeComAdapter`) | Personal WeChat (`WeixinAdapter`) |
|---|---|---|
| Connection method | Persistent WebSocket | HTTP long polling (35-second timeout) |
| Message truncation | 4000 characters | 1500 characters |
| Heartbeat | Ping every 30 seconds | Not needed (each poll acts as heartbeat) |
| Reconnection | Exponential backoff | Each poll auto-reconnects |
| Deduplication | message_id | message_id |
| Media encryption | AES-256-CBC | AES-128-ECB |
| Sending requires | chatid | context_token (must be echoed back) |
| Chunk send interval | None | 0.35 seconds (WeChat rate limit) |

Personal WeChat has a unique design: **each inbound message carries a `context_token`, and outbound replies must include this token.** This means the adapter needs to cache the latest context_token for each user:

```python
# When receiving a message
context_token = message["context_token"]
self._context_tokens[user_id] = context_token

# When sending a reply
await self._http.post(f"{self._base_url}/ilink/bot/sendmessage", json={
    "to_user_id": chat_id,
    "context_token": self._context_tokens.get(chat_id, ""),
    "item_list": [{"type": 1, "text_item": {"text": content}}],
})
```

But these differences only affect the adapter's internal implementation. The translated `MessageEvent` format is exactly the same. GatewayRunner and the core loop don't know whether the message came from WeCom or personal WeChat.

## How it connects to the main loop

Same as s12 -- the adapter and the core loop are separated by GatewayRunner.

```text
WeComAdapter
  +-- _listen_loop -> _translate -> dedup -> batch -> handle_message
                                                       |
                                                       v
                                              GatewayRunner._handle_message
                                                       |
                                                       v
                                              build_session_key -> run_conversation -> send
                                                                       |
                                                                       |  Same function the CLI calls
                                                                       v
                                                                 Agent core loop (s01-s11)
```

The adapter doesn't know the core loop exists. The core loop doesn't know the adapter exists.

## Most common beginner mistakes

### 1. Forgetting text batching

A user sends a long text and the platform splits it into two messages. You start processing the first one and the agent is already replying when the second arrives, triggering an interrupt. The user sees two unrelated replies.

**Fix: Run all text messages through TextBatcher (0.6-second quiet period) before handing to GatewayRunner.**

### 2. Downloading media URLs after they expire

WeCom media URLs are temporary. If you store the URL in the MessageEvent without downloading immediately, it'll be expired by the time the agent needs it.

**Fix: Download to local cache immediately when the adapter receives a media message.**

### 3. Not accounting for platform differences when replying

WeCom supports Markdown, but personal WeChat doesn't. If you send Markdown directly, the user sees a mess of `*` and `#` characters.

**Fix: Each adapter's `send()` method is responsible for format conversion. The core loop only outputs generic text.**

### 4. Forgetting context_token for WeChat replies

Every reply to personal WeChat must include the latest `context_token` received, or the message won't send.

**Fix: The adapter maintains a `user_id -> context_token` mapping, updated with each incoming message.**

## Scope of this chapter

This chapter covers only three things:

1. **The BasePlatformAdapter interface** -- Three required methods, two optional media methods
2. **The complete flow for writing a new adapter** -- Connect, translate, send replies, heartbeat, reconnect
3. **Three shared mechanisms** -- Text batching, message deduplication, media download caching

Not covered:

- Complete API documentation for each platform -> see their respective developer docs
- Cryptographic principles behind AES encryption/decryption -> you only need to know "download then decrypt"
- Voice channels and video calls -> beyond the scope of text conversations
- Platform-specific interactive components (keyboards, buttons, cards) -> UX enhancements that don't affect the core flow

## How this chapter relates to later chapters

- **s12** defined GatewayRunner and MessageEvent -> this chapter uses them
- **s14** covers terminal backend abstraction -> same "encapsulate differences so the layer above doesn't care" approach, just applied to a different domain (platforms vs. execution environments)
- **s15** covers scheduled tasks -> scheduled task results need to be delivered to specific platforms through adapters

## After this chapter, you should be able to answer

- How many methods does `BasePlatformAdapter` have? Which ones must be implemented?
- If you need to connect a new platform, what's the first step?
- A user sends 5000 characters to WeCom. How many messages does the adapter receive? How many does it pass to GatewayRunner?
- Why should media files be downloaded immediately in the adapter rather than passing the URL to the agent?
- What is personal WeChat's `context_token`? What happens if you forget it?
- After WeCom disconnects, how does the adapter recover?

---

**In one sentence: Adapters do translation -- inbound, they convert platform messages into MessageEvents; outbound, they convert generic text into platform format. The common pitfalls (fragmentation, deduplication, media caching) are the same across every adapter.**
