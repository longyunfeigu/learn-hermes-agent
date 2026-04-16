# s13: Platform Adapters (平台适配器)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > [ s13 ] > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *s12 告诉你为什么需要适配器。这一章告诉你怎么写一个。*

![平台适配器模式](../../illustrations/s13-platform-adapters/01-framework-adapter-pattern.png)

## 这一章要解决什么问题

s12 用企业微信做了一个例子，演示了适配器的三个核心职责：连接平台、翻译消息、发送回复。但那只是一个适配器。

当你真的要给这个系统接第二个、第三个平台时，你会发现一系列新问题：

- 每个平台的连接方式不同。企业微信是 WebSocket，微信个人号是 HTTP 长轮询，协议完全不一样。
- 用户发了一段 5000 字的文本，平台客户端自动拆成两条推过来。分别处理两条"半截消息"，agent 的回复就乱了。
- 用户发了图片或语音。你需要下载、解密、缓存、让 agent 用，回复时还要加密上传回去。
- WebSocket 断了要重连，HTTP 超时了要重试，同一条消息可能推两次。

这些问题不是某个平台独有的——**每个**适配器都会遇到。你需要一个基类把共性抽出来，让每个适配器只处理自己平台特有的部分。

## 建议联读

- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) — 适配器的由来和 GatewayRunner 的路由逻辑
- [`data-structures.md`](./data-structures.md) — `MessageEvent`、`SessionSource` 的完整字段定义
- [`glossary.md`](./glossary.md) — 适配器、session key 等术语

## 先解释几个名词

### 什么是 BasePlatformAdapter

所有平台适配器的抽象基类。它定义了一个适配器**必须做什么**（连接、发消息）和**可以做什么**（发图片、发语音），但不关心**怎么做**——具体实现由子类决定。

### 什么是消息分片合并（Text Batching）

平台客户端在发送长文本时会自动截断（企业微信 4000 字符、微信 1500 字符）。一条用户消息变成两条甚至三条推给你。适配器需要把它们合并回一条再交给 GatewayRunner。

### 什么是消息去重（Deduplication）

网络不稳定时，同一条消息可能被平台推送两次。适配器用 `message_id` 记录已处理的消息，重复的直接丢弃。

### 什么是媒体缓存

平台提供的媒体 URL 通常是临时的，而且可能需要解密。适配器收到图片/语音时立刻下载、解密、存到本地缓存目录，把本地路径交给 agent。

## 最小心智模型

一个适配器的完整生命周期：

```text
                   connect()
                      │
                      v
         ┌─────────────────────────┐
         │   平台消息监听循环         │
         │                         │
         │  平台 JSON/XML           │
         │      │                  │
         │      v                  │
         │  _translate()           │
         │      │                  │
         │      v                  │
         │  消息去重 → 分片合并      │
         │      │                  │
         │      v                  │
         │  handle_message(event)  │──→ GatewayRunner
         │                         │
         │  send(chat_id, text)  ←─│─── GatewayRunner
         │      │                  │
         │      v                  │
         │  格式转换 → 平台 API     │
         └─────────────────────────┘
                      │
                      v
                 disconnect()
```

关键洞察：**左侧的"平台 JSON → _translate() → MessageEvent"和右侧的"通用文本 → 格式转换 → 平台 API"是每个适配器唯一要写的部分。** 中间的去重、合并、路由全是共用的。

## 关键数据结构

### BasePlatformAdapter

```python
class BasePlatformAdapter(ABC):

    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self._on_message = None   # GatewayRunner 启动时注入
        self._running = False

    # --- 三个必须实现的方法 ---

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self): ...

    @abstractmethod
    async def send(self, chat_id: str, content: str) -> bool: ...

    # --- 两个可选的媒体方法（默认返回 False = 不支持）---

    async def send_image(self, chat_id: str, image_path: str) -> bool:
        return False

    async def send_voice(self, chat_id: str, audio_path: str) -> bool:
        return False

    # --- 不需要覆盖 ---

    async def handle_message(self, event: MessageEvent):
        if self._on_message:
            await self._on_message(event)
```

三个必须实现的方法是**所有平台都有的**——不管什么平台，你总要连上去、断开、发消息。两个可选方法默认返回 `False`，支持的平台覆盖即可。

### MessageDeduplicator

```python
class MessageDeduplicator:
    """按 message_id 去重，FIFO 淘汰旧记录。"""

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
    """缓冲文本片段，安静期过后合并成一条 MessageEvent。"""

    async def enqueue(self, session_key, text, event, split_threshold=3900):
        self._buffers[session_key].append(text)
        # 接近截断阈值 → 等更久（后面几乎肯定还有续片）
        delay = 2.0 if len(text) >= split_threshold else 0.6
        # 取消上次的定时器，重新计时
        self._restart_flush_timer(session_key, delay)

    async def _flush(self, session_key):
        merged_text = "".join(self._buffers.pop(session_key))
        event.text = merged_text
        await self._callback(event)
```

## 最小实现：从零写一个企业微信适配器

用企业微信（WeCom）WebSocket Bot 演示完整生命周期。

### 第一步：连接

企业微信 Bot 通过持久 WebSocket 收发消息。连接时需要订阅（`aibot_subscribe`），之后保持心跳。

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

        # 订阅：告诉企业微信"我是这个 bot，开始给我推消息"
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

### 第二步：收消息并翻译

企业微信推来的消息长这样：

```json
{
    "cmd": "aibot_msg_callback",
    "body": {
        "msgid": "msg_001",
        "msgtype": "text",
        "from": {"userid": "zhangsan"},
        "chatid": "zhangsan",
        "chattype": "single",
        "text": {"content": "帮我查一下今天的天气"}
    }
}
```

监听循环不断读 WebSocket 消息，过滤出 `aibot_msg_callback`，翻译成 `MessageEvent`：

```python
    async def _listen_loop(self):
        while self._running:
            try:
                raw = await self._ws.receive_json()
                if raw.get("cmd") != "aibot_msg_callback":
                    continue

                body = raw["body"]
                msg_id = body.get("msgid", "")

                # 去重
                if self._dedup.is_duplicate(msg_id):
                    continue

                event = self._translate(body)
                await self.handle_message(event)

            except Exception as exc:
                if self._running:
                    print(f"  [wecom] listen error: {exc}")
                    break  # 让外层重连逻辑接管

    def _translate(self, body: dict) -> MessageEvent:
        """企业微信 JSON → 统一格式。这是适配器最核心的工作。"""
        # 提取文本：text 类型直接取，mixed 类型要拼接所有片段
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

### 第三步：发回复

```python
    async def send(self, chat_id: str, content: str) -> bool:
        # 企业微信消息长度限制 4000 字符
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

### 第四步：心跳和断线重连

企业微信要求每 30 秒发一次心跳，否则服务器会断开连接。

```python
    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(30)
            try:
                await self._ws.send_json({"cmd": "ping"})
            except Exception:
                break  # 连接断了，让重连逻辑处理
```

断线后用指数退避重连：

```python
    async def run_with_reconnect(self):
        """带自动重连的主循环。"""
        backoff = [2, 5, 10, 30, 60]
        attempt = 0

        while self._running:
            try:
                await self.connect()
                attempt = 0  # 连上了，重置计数

                # 等监听循环结束（意味着断线了）
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

### 第五步：断开

```python
    async def disconnect(self):
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
```

**整个适配器大约 100 行核心代码。** 做的事情就是心智模型图里画的那几步：连上去、收消息、翻译、发回复、心跳保活、断线重连。

## 消息分片合并：所有适配器都会遇到的坑

企业微信客户端在 4000 字符处自动截断长文本。用户觉得自己发了"一条消息"，但平台推给你的是两条。

如果你分别处理，第一条还没处理完，第二条就到了——触发 s12 讲的中断机制，agent 看到的是半截话。

**解决：时间窗口合并。**

但有一个根本问题：**你无法确定两条快速到达的消息是"一条被拆的"还是"两条独立的"。** TextBatcher 不试图区分——它用两个启发式规则来决定等多久：

**规则一：看长度。** 如果收到的文本长度接近平台截断点（企微 ≥ 3900 字符），这条消息大概率是被截断的——后面几乎肯定还有续片。等久一点（2 秒）。如果长度远小于截断点，大概率是完整的。等短一点（0.6 秒）。

**规则二：看间隔。** 正常人不可能在 0.6 秒内连续发出两条独立的消息。如果 0.6 秒内又来了一条，要么是平台拆的，要么是用户在补充同一个意思——不管哪种情况，合并都不会出错。

用三个场景走一遍：

```text
场景 1：长文本被截断（最常见）

用户发了 6000 字 → 企业微信拆成两条推过来

t=0.000s  收到第一条（3998 字符）
          → 3998 >= 3900（接近截断点）→ 等 2.0 秒
t=0.050s  收到第二条（2002 字符）
          → 2002 < 3900 → 重启定时器，改为 0.6 秒
t=0.650s  0.6 秒内没有新消息 → 合并成 6000 字交给 agent ✓

场景 2：用户发了一条短消息（最简单）

t=0.000s  收到"你好"（2 字符）
          → 2 远小于 3900 → 等 0.6 秒
t=0.600s  没有新消息 → 直接交给 agent ✓

场景 3：用户快速连发两条无关消息（罕见）

t=0.000s  收到"帮我查天气"（5 字符）→ 等 0.6 秒
t=0.300s  收到"另外提醒我开会"（7 字符）→ 重启 0.6 秒
t=0.900s  没有新消息 → 合并成"帮我查天气另外提醒我开会"交给 agent
          → 合并了，但 agent 照样能理解，比拆开处理好 ✓
```

**这个设计会误判吗？** 会。场景 3 就是误判——两条独立的消息被合并了。但 0.6 秒内连发两条无关消息在实际使用中极其罕见，而且合并后 agent 照样能理解。反过来，如果不合并，场景 1 的半截话问题是致命的。

关键参数：

| 参数 | 值 | 原因 |
|------|-----|------|
| 默认安静期 | 0.6 秒 | 正常人打不出这么快的两条独立消息 |
| 接近截断阈值时 | 2.0 秒 | 文本长度 ≥ 3900 字符 → 大概率被截断，等续片 |
| 截断阈值 | 3900（企微）/ 1400（微信） | 比平台实际限制（4000/1500）略低，留安全余量 |

### TextBatcher 的实现机制

"定时器"不是一个 timer 对象，而是一个 **sleep 然后刷新的异步任务**。"重置定时器"就是 **cancel 旧任务、创建新任务**。

TextBatcher 内部只有三个字典：

```python
_buffers = {}   # session_key → ["片段1", "片段2", ...]  缓冲区
_events  = {}   # session_key → 最新的 MessageEvent       保留元数据
_tasks   = {}   # session_key → 一个正在 sleep 的异步任务  "定时器"
```

每次收到消息时（`enqueue`）做四步：

```python
# 1. 文本存入缓冲区
_buffers[key].append(text)

# 2. 如果有旧任务正在 sleep → cancel 它
#    被 cancel 的任务不会执行后续的"取出缓冲区 → 拼接 → 交出去"
if old_task and not old_task.done():
    old_task.cancel()

# 3. 根据文本长度决定等多久
delay = 2.0 if len(text) >= 3900 else 0.6

# 4. 创建新任务：sleep(delay) 然后刷新
_tasks[key] = create_task(_flush_after(key, delay))
```

`_flush_after` 做的事：

```python
async def _flush_after(key, delay):
    await asyncio.sleep(delay)   # 在这里等
    # ↑ 如果被 cancel，sleep 抛 CancelledError，下面不会执行

    chunks = _buffers.pop(key)           # 取出所有片段
    event.text = "".join(chunks)         # 拼成一条
    await callback(event)                # 交给 GatewayRunner
```

**为什么收到新消息时必须 cancel 旧任务？** 因为旧任务不知道缓冲区里又多了新文本。如果让它继续执行，它会在倒计时结束后取出缓冲区——但那时缓冲区已经被新任务接管了，就会出现两个任务抢同一个缓冲区的混乱。cancel 旧任务，让新任务全权负责"等安静了再把全部片段一起交出去"。

完整流程图：

```text
收到一条消息(text)
       │
       v
  存入缓冲区
       │
       v
  有旧任务在 sleep？
       │          │
       是          否
       │          │
       v          │
  cancel(旧任务)  │
  旧任务不会刷新  │
       │          │
       ├──────────┘
       v
  len(text) >= 3900？
       │          │
       是          否
       │          │
       v          v
  delay=2.0s   delay=0.6s
       │          │
       ├──────────┘
       v
  创建新任务: sleep(delay)
       │
       │  sleep 期间又来了新消息？
       │          │
       是          否（sleep 跑完）
       │          │
       v          v
  回到顶部      取出所有片段，拼接
 （旧任务被      交给 GatewayRunner
   cancel）
```

一句话：**每收到一条消息就重新倒计时，倒计时跑完了才交出去。**

这套逻辑在企业微信、微信、Telegram、Discord 的适配器里几乎一模一样。区别只是截断阈值不同。

## 媒体处理：下载、解密、缓存

文本消息只有"翻译"和"发送"两步。媒体消息多了"下载解密"和"加密上传"。

### 入站：平台 → 下载 → 解密 → 本地缓存

企业微信的图片消息包含 `url` 和 `aeskey`。url 下载的是加密后的文件，需要用 aeskey 解密：

```python
async def _download_and_decrypt(self, media: dict) -> str | None:
    """下载并解密企业微信媒体文件，返回本地缓存路径。"""
    url = media.get("url")
    aeskey_b64 = media.get("aeskey")
    if not url:
        return None

    # 1. 下载加密文件
    async with aiohttp.ClientSession() as session:
        resp = await session.get(url)
        encrypted = await resp.read()

    # 2. 解密（AES-256-CBC，key 即 IV）
    if aeskey_b64:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key = base64.b64decode(aeskey_b64)  # 32 bytes
        cipher = Cipher(algorithms.AES(key), modes.CBC(key))
        decryptor = cipher.decryptor()
        raw = decryptor.update(encrypted) + decryptor.finalize()
        # PKCS#7 去填充
        pad_len = raw[-1]
        data = raw[:-pad_len]
    else:
        data = encrypted

    # 3. 缓存到本地
    cache_dir = HERMES_HOME / "cache" / "images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:12]}.jpg"
    path = cache_dir / filename
    path.write_bytes(data)
    return str(path)
```

### 为什么要在适配器里立刻下载

企业微信的媒体 URL 是临时的。如果你把 URL 存进 MessageEvent 但不立刻下载，等 agent 处理到要分析图片时 URL 可能已经过期了。

**规则：收到媒体消息时立刻下载到本地，MessageEvent 里存本地路径。**

### 出站：agent → 加密 → 分块上传 → 发消息

企业微信的媒体上传是三步走：

```text
1. aibot_upload_media_init   → 告诉服务器"我要上传一个 X 大小的文件"
2. 分块发送（每块 512KB）     → 大文件拆成多块逐个传
3. aibot_upload_media_finish → 上传完成，拿到 media_id
4. aibot_send_msg            → 用 media_id 发送消息
```

不同平台的媒体上传差异很大：

| | 企业微信 | 微信个人号 |
|---|---|---|
| 加密 | AES-256-CBC | AES-128-ECB |
| 密钥 | 32 字节 | 16 字节 |
| 上传 | 分块 512KB | CDN 直传 |
| 图片限制 | 10 MB | — |
| 语音格式 | 仅 AMR | 仅 Silk |

但对 GatewayRunner 来说，这些差异被 `send_image()` 方法封装了。它只管调，不管里面的加密和上传协议。

## 微信个人号适配器：同一套模式，不同的协议

企业微信用 WebSocket，微信个人号用 HTTP 长轮询。但适配器的结构完全一样。

| | 企业微信（WeComAdapter） | 微信个人号（WeixinAdapter） |
|---|---|---|
| 连接方式 | 持久 WebSocket | HTTP 长轮询（35 秒超时） |
| 消息截断 | 4000 字符 | 1500 字符 |
| 心跳 | 30 秒一次 ping | 不需要（每次轮询即心跳） |
| 重连 | 指数退避 | 每次轮询自动重连 |
| 去重 | message_id | message_id |
| 媒体加密 | AES-256-CBC | AES-128-ECB |
| 发送需要 | chatid | context_token（必须回传） |
| 分块发送间隔 | 无 | 0.35 秒（微信限速） |

微信个人号有一个独特设计：**每条入站消息附带一个 `context_token`，出站回复时必须带上这个 token。** 这意味着适配器需要为每个用户缓存最新的 context_token：

```python
# 收到消息时
context_token = message["context_token"]
self._context_tokens[user_id] = context_token

# 发回复时
await self._http.post(f"{self._base_url}/ilink/bot/sendmessage", json={
    "to_user_id": chat_id,
    "context_token": self._context_tokens.get(chat_id, ""),
    "item_list": [{"type": 1, "text_item": {"text": content}}],
})
```

但这些差异只影响适配器内部实现。翻译出来的 `MessageEvent` 格式完全一样。GatewayRunner 和核心循环不知道消息来自企业微信还是个人微信。

## 如何接到主循环里

和 s12 一样——适配器和核心循环之间隔着 GatewayRunner。

```text
WeComAdapter
  └─ _listen_loop → _translate → 去重 → 合并 → handle_message
                                                       │
                                                       v
                                              GatewayRunner._handle_message
                                                       │
                                                       v
                                              build_session_key → run_conversation → send
                                                                       │
                                                                       │  和 CLI 调的是同一个函数
                                                                       v
                                                                 agent 核心循环（s01-s11）
```

适配器不知道核心循环的存在。核心循环不知道适配器的存在。

## 初学者最容易犯的错

### 1. 忘了消息合并

用户发了一段长文本，平台拆成两条推过来。你处理第一条时 agent 已经开始回复了，第二条到了又中断。结果用户看到两段不相关的回复。

**修：所有文本消息先过 TextBatcher（0.6 秒安静期），再交给 GatewayRunner。**

### 2. 媒体 URL 过期后才去下载

企业微信的媒体 URL 是临时的。如果你把 URL 存进 MessageEvent 但不立刻下载，等 agent 要用的时候已经过期了。

**修：在适配器里收到媒体消息时立刻下载到本地缓存。**

### 3. 回复时不考虑平台差异

企业微信支持 Markdown，但微信个人号不支持。你直接把 Markdown 发过去，用户看到的是一堆 `*` 和 `#`。

**修：每个适配器的 `send()` 方法自己负责格式转换。核心循环只输出通用文本。**

### 4. 微信回复时忘了 context_token

微信个人号的每条回复都必须带上最新收到的 `context_token`，否则消息发不出去。

**修：适配器维护 `user_id → context_token` 的映射，每收到消息就更新。**

## 教学边界

这一章只讲三件事：

1. **BasePlatformAdapter 的接口** — 三个必须实现的方法，两个可选的媒体方法
2. **写一个新适配器的完整流程** — 连接、翻译、发回复、心跳、重连
3. **三个共性机制** — 消息分片合并、消息去重、媒体下载缓存

不讲的：

- 每个平台 API 的完整文档 → 各家开发者文档
- AES 加解密的密码学原理 → 只需要知道"下载后要解密"
- 语音通道和视频通话 → 超出文本对话的范畴
- 平台特有的交互组件（键盘、按钮、卡片） → 增强体验，不影响核心流程

## 这一章和后续章节的关系

- **s12** 定义了 GatewayRunner 和 MessageEvent → 本章用它们
- **s14** 讲终端后端抽象 → 和适配器是同一种"把差异封装起来"的思路，只是对象不同（平台 vs 执行环境）
- **s15** 讲定时任务 → 定时任务的结果需要通过适配器投递到指定平台

## 学完这章后，你应该能回答

- `BasePlatformAdapter` 有几个方法？哪些是必须实现的？
- 如果要接一个新平台，第一步做什么？
- 用户发了 5000 字的文本到企业微信，适配器收到几条消息？最终传给 GatewayRunner 几条？
- 为什么媒体文件要在适配器里立刻下载，而不是把 URL 传给 agent？
- 微信个人号的 `context_token` 是什么？忘了它会怎样？
- 企业微信断线后，适配器怎么恢复？

---

**一句话记住：适配器做翻译——入站把平台消息变成 MessageEvent，出站把通用文本变成平台格式。共性的坑（分片、去重、媒体缓存）每个适配器都一样。**
