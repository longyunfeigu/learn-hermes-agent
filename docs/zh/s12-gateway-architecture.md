# s12: Gateway Architecture (网关架构)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > [ s12 ] > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *CLI 是你和 agent 一对一聊天。Gateway 是让同一个 agent 同时接待十几个平台上的用户。核心循环一行没变，变的只是消息从哪来、回复往哪送。*

![多平台消息路由网关](../../illustrations/s12-gateway/01-framework-routing.png)

## 这一章要解决什么问题

到 `s11`，你已经有了一个功能完整的单 agent 系统。但它只有一个入口：CLI——你在终端里输入一句话，agent 回复一句话。

现在你想让这个 agent 也能在企业微信里用。怎么办？

## 从最笨的实现开始

先不考虑架构，写一个最直接的"微信机器人"：

```python
# 最笨的版本：直接连微信，收到消息就调 agent

import aiohttp, asyncio

async def main():
    # 1. 连上微信
    ws = await aiohttp.ClientSession().ws_connect("wss://openws.work.weixin.qq.com")
    await ws.send_json({
        "cmd": "aibot_subscribe",
        "body": {"bot_id": "xxx", "secret": "yyy"},
    })

    # 2. 死循环：收消息 → 调 agent → 回消息
    while True:
        msg = await ws.receive_json()
        if msg["cmd"] != "aibot_msg_callback":
            continue

        body = msg["body"]
        user_text = body["text"]["content"]
        chat_id = body["chatid"]

        # 3. 调 s01 的核心循环（和 CLI 用的同一个函数）
        agent = AIAgent(model="anthropic/claude-sonnet-4")
        response = agent.run_conversation(user_text)

        # 4. 把回复发回微信
        await ws.send_json({
            "cmd": "aibot_send_msg",
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {"content": response},
            },
        })
```

40 行代码，能跑。但它有三个致命问题。

## 问题一：没有记忆——每条消息都是全新对话

上面的代码每次调 `run_conversation` 只传了当前这一条消息。agent 不知道之前聊了什么。

你在微信里说"帮我翻译 hello"，agent 回复"你好"。然后你说"再翻译 world"，agent 不知道你之前在翻译——因为它没有历史。

**解决：需要把每个用户的聊天记录存起来，下次调循环时传进去。**

但这里有个关键问题：怎么知道"哪些消息属于同一段对话"？

如果张三和李四同时在微信上跟 agent 聊天，他们的消息不能混在一起。张三问的"帮我写代码"和李四问的"今天天气怎么样"是两段完全独立的对话。

需要一个**标识符**来区分不同的对话。Hermes Agent 叫它 **session key**——用平台 + 聊天 ID + 用户 ID 拼出一个唯一字符串：

```python
# 私聊：平台 + 聊天类型 + 用户ID
"agent:main:wecom:dm:zhangsan"

# 群聊：平台 + 聊天类型 + 群ID + 用户ID（群内按人隔离）
"agent:main:wecom:group:grp_001:zhangsan"
"agent:main:wecom:group:grp_001:lisi"
```

张三和李四在同一个群里，但 session key 不同，所以各自有独立的对话历史。

加上会话管理后，代码变成：

```python
sessions = {}  # session_key → 消息历史列表

while True:
    msg = await ws.receive_json()
    body = msg["body"]

    # 生成 session key
    user_id = body["from"]["userid"]
    chat_id = body["chatid"]
    chat_type = "dm" if body["chattype"] == "single" else "group"

    if chat_type == "dm":
        session_key = f"agent:main:wecom:dm:{chat_id}"
    else:
        session_key = f"agent:main:wecom:group:{chat_id}:{user_id}"

    # 取出这个用户的历史，没有就创建空列表
    history = sessions.setdefault(session_key, [])

    # 加入当前消息
    history.append({"role": "user", "content": body["text"]["content"]})

    # 创建 agent，带着完整历史调循环
    agent = AIAgent(model="...", conversation_history=history)
    response = agent.run_conversation(body["text"]["content"])

    # agent 内部已经把回复追加到 history 里了

    # 发回微信
    await ws.send_json(...)
```

现在 agent 有记忆了。但还有两个问题。

## 问题二：只能接微信——加个 Telegram 要改多少代码？

产品说："能不能也接个 Telegram？"

你看了下 Telegram 的 API——它不是 WebSocket，是 HTTP 长轮询。消息格式完全不一样。用户 ID 叫 `from.id`（不是 `from.userid`），聊天 ID 叫 `chat.id`（不是 `chatid`）。

如果你直接在 while 循环里加 if-else：

```python
# 千万别这样写
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
        ...  # 又一套完全不同的格式
```

每加一个平台，这个循环就膨胀一圈。17 个平台就是 17 个分支。而且"怎么连接""怎么收消息""怎么发回复"的逻辑全搅在一起。

**解决：让每个平台自己负责"翻译"，翻译完交给一个统一的格式。**

这就是**平台适配器**的由来。每个适配器做两件事：

1. **收到平台消息 → 翻译成统一格式**（入站）
2. **拿到回复文本 → 翻译成平台格式发出去**（出站）

统一格式在 Hermes Agent 里叫 `MessageEvent`：

```python
@dataclass
class MessageEvent:
    message_id: str        # "msg_001"
    text: str              # "帮我查一下天气"
    source: SessionSource  # 从哪来的（平台、聊天ID、用户ID）
    message_type: str      # "text", "photo", "voice", ...
```

```python
@dataclass
class SessionSource:
    platform: str    # "wecom", "telegram", "discord", ...
    chat_id: str     # 聊天标识
    chat_type: str   # "dm" 或 "group"
    user_id: str     # 发消息的人
```

不管微信还是 Telegram，翻译完都是同一个 `MessageEvent`。下游代码不需要知道消息来自哪个平台。

微信适配器的翻译逻辑：

```python
class WeComAdapter:
    """企业微信适配器：连微信、收消息、翻译、发回复。"""

    async def connect(self):
        """连接到企业微信 WebSocket。"""
        self._ws = await session.ws_connect("wss://openws.work.weixin.qq.com")
        await self._ws.send_json({
            "cmd": "aibot_subscribe",
            "body": {"bot_id": self._bot_id, "secret": self._secret},
        })
        # 启动后台监听
        asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """一直读微信消息，翻译成 MessageEvent，交给回调处理。"""
        while True:
            raw = await self._ws.receive_json()
            if raw["cmd"] == "aibot_msg_callback":
                event = self._translate(raw["body"])
                await self._on_message(event)  # 这个回调是外面注册进来的

    def _translate(self, body: dict) -> MessageEvent:
        """微信格式 → 统一格式。这是适配器最核心的工作。"""
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
        """统一的回复文本 → 微信格式发出去。"""
        await self._ws.send_json({
            "cmd": "aibot_send_msg",
            "body": {
                "chatid": chat_id,
                "msgtype": "markdown",
                "markdown": {"content": content[:4000]},
            },
        })
```

如果要加 Telegram，写一个 `TelegramAdapter`，翻译逻辑不同，但输出的 `MessageEvent` 格式完全一样。**下游代码一行都不用改。**

现在的结构变成：

```text
WeComAdapter ──翻译──→ MessageEvent ──→ 找会话 → 调循环 → 回复
TelegramAdapter ─翻译─→ MessageEvent ──→  同上
DiscordAdapter ──翻译─→ MessageEvent ──→  同上
```

中间那段"找会话 → 调循环 → 回复"的逻辑对所有平台都是一样的。Hermes Agent 把它封装成一个函数，给了它一个名字：**`_handle_message`**。

每个适配器启动时，把这个函数注册为自己的回调。收到消息翻译完就调它，不需要知道它里面做了什么。

```python
# 启动时
wecom_adapter._on_message = handle_message   # 注册回调
telegram_adapter._on_message = handle_message  # 同一个函数

# 运行时
# 微信来消息 → WeComAdapter._listen_loop → _translate → handle_message(event)
# Telegram来消息 → TelegramAdapter._poll_loop → _translate → handle_message(event)
```

那谁来管"启动所有适配器"和"提供这个 `handle_message`"呢？

## 自然推出 GatewayRunner

你现在有多个适配器，需要有人做三件事：

1. **启动时**：遍历配置，把启用的适配器都连上
2. **运行时**：收到 `MessageEvent` 后，找会话、调循环、返回回复
3. **关闭时**：优雅地断开所有连接

把这三件事装进一个类，就是 `GatewayRunner`：

```python
class GatewayRunner:
    def __init__(self, config):
        self.adapters = {}       # platform → adapter
        self.session_store = {}  # session_key → 消息历史

    async def start(self):
        """启动所有配置了的平台适配器。"""
        for platform, platform_config in config.platforms.items():
            if not platform_config.enabled:
                continue

            # 创建适配器
            if platform == "wecom":
                adapter = WeComAdapter(platform_config)
            elif platform == "telegram":
                adapter = TelegramAdapter(platform_config)
            # ...

            # 把 handle_message 注册为回调
            adapter._on_message = self._handle_message

            # 连接
            await adapter.connect()
            self.adapters[platform] = adapter

    async def _handle_message(self, event: MessageEvent) -> str:
        """
        所有平台的消息最终都到这里。
        这个函数不知道消息来自微信还是 Telegram——它只看 MessageEvent。
        """
        # 1. 生成 session key
        src = event.source
        if src.chat_type == "dm":
            session_key = f"agent:main:{src.platform}:dm:{src.chat_id}"
        else:
            session_key = f"agent:main:{src.platform}:group:{src.chat_id}:{src.user_id}"

        # 2. 取出或创建 agent（按 session key 缓存复用）
        if session_key not in self.agents:
            self.agents[session_key] = AIAgent(model="...", session_id=session_key)
        agent = self.agents[session_key]

        # 3. 每次都从数据库重新加载最新的历史
        #    为什么不用 agent 内部的历史？因为历史可能被其他操作修改过
        #    （比如用户执行了 /undo 删掉了最后一轮，或者触发了上下文压缩）
        history = self.session_store.load_transcript(session_key)

        # 4. 调核心循环，把最新历史传进去
        response = agent.run_conversation(event.text, conversation_history=history)

        return response

    async def stop(self):
        for adapter in self.adapters.values():
            await adapter.disconnect()
```

注意两个设计决策：

**agent 实例按 session key 缓存复用，不是每条消息都创建新的。** 张三发 10 条消息，用的是同一个 agent 实例。但微信的张三和 Telegram 的 Bob 是不同的 session key，所以是不同的 agent 实例。

**history 每次都从数据库重新拉取，不靠 agent 内部记忆。** 这是因为历史可能被外部修改——用户执行了 `/undo`（删掉最后一轮）、`/compress`（压缩上下文）、或者会话过期被自动重置。如果 agent 只用自己内部缓存的历史，这些修改就丢了。

**`GatewayRunner` 不是一个需要背诵的抽象概念。它就是你自己会写出来的东西**——当你有多个适配器需要统一管理时，自然会把"启动""路由""关闭"的逻辑收拢到一个地方。

现在回头看整个结构：

```text
GatewayRunner
  │
  ├─ 启动时：创建适配器，注册回调，连接平台
  │
  ├─ agents 缓存池（按 session key → agent 实例）
  │
  ├─ WeComAdapter（微信）
  │    └─ 收到微信消息 → _translate → 调 GatewayRunner._handle_message
  │
  ├─ TelegramAdapter（Telegram）
  │    └─ 收到 Telegram 消息 → _translate → 调 GatewayRunner._handle_message
  │
  └─ _handle_message（所有消息的汇聚点）
       └─ 找 session → 取出/创建 agent → 从数据库加载历史
         → agent.run_conversation(消息, history) → 返回回复
```

**`agent.run_conversation()` 不知道消息从哪来。** 不管微信还是 Telegram，调用方式完全一样。这就是 `s00` 说的"Gateway 场景和 CLI 场景的区别只在入口和出口，核心循环完全一样"。

## 问题三：张三在 agent 思考时又发了一条消息怎么办？

张三发了"帮我写个排序算法"，agent 开始思考。10 秒后张三又发了"用 Python 写"。

如果你为第二条消息也创建一个 agent 实例，两个实例同时运行、同时读写张三的会话历史，回复就乱了。

但你也不能丢掉第二条消息——用户确实想补充说明。

Hermes Agent 的做法是：**一个 session 同一时间只有一个 agent 在跑。新消息暂存起来，等当前 agent 完成后再处理。**

```python
# 适配器基类的核心逻辑（简化版）

active_sessions = {}   # session_key → 中断信号
pending_messages = {}  # session_key → 暂存的下一条消息

async def handle_message(self, event):
    session_key = build_session_key(event.source)

    if session_key in active_sessions:
        # 这个 session 已经有 agent 在跑了
        # 把新消息暂存起来（只保留最后一条，前面的会被覆盖）
        pending_messages[session_key] = event
        # 给正在运行的 agent 发一个中断信号
        active_sessions[session_key].set()
        return

    # 没有活跃 agent → 标记为活跃，开始处理
    active_sessions[session_key] = asyncio.Event()
    await self._process_message_background(event, session_key)
```

处理完一条消息后，检查有没有暂存的：

```python
# _process_message_background 的尾部
if session_key in pending_messages:
    next_event = pending_messages.pop(session_key)
    del active_sessions[session_key]
    # 立刻处理下一条（不是再排队，而是直接递归调用）
    await self._process_message_background(next_event, session_key)
else:
    del active_sessions[session_key]
```

### 中断信号具体做了什么？

"发中断信号"不是一句模糊的说法。`agent.interrupt()` 做了一件很具体的事：**设置 `_interrupt_requested = True` 标志位。**

agent 的核心循环（`s01` 讲的那个 while 循环）在很多地方都会检查这个标志位：

```python
# 1. 正在等待 LLM 回复流 → 立刻停止读取
with client.responses.stream(**api_kwargs) as stream:
    for event in stream:
        if self._interrupt_requested:
            break  # 不再等 LLM 的后续 token 了

# 2. 正在依次执行多个工具调用 → 跳过剩余的
for i, tool_call in enumerate(tool_calls):
    execute(tool_call)
    if self._interrupt_requested and i < len(tool_calls):
        # 跳过还没执行的工具，填一个"被跳过"的占位结果
        for skipped in tool_calls[i:]:
            messages.append({
                "role": "tool",
                "content": "[Tool execution skipped — user sent a new message]",
                "tool_call_id": skipped.id,
            })
        break

# 3. 主循环的每一轮开始时也会检查
while iteration < max_iterations:
    if self._interrupt_requested:
        break  # 结束循环，返回当前已有的结果
```

所以中断不是"强制杀进程"，而是**在下一个检查点优雅退出**——停止等流、跳过剩余工具、退出循环。

### 中断后的内容会丢吗？对话还连贯吗？

**不丢，照样连贯。**

agent 被中断后正常返回 `result["messages"]`，里面包含中断点之前产生的全部内容：已生成的部分回复、已执行的工具调用和结果、被跳过的工具调用 + 占位 tool 消息（占位是为了满足 OpenAI API "每个 tool_call 必须有 tool 回应"的硬性要求）。Gateway 把这些全部 `append_to_transcript` 进数据库。

下一轮处理新消息时，`conversation_history` 从数据库重新加载，新 agent 看到的是完整脉络：

```text
user:      "帮我写个排序算法"
assistant: "好的，我推荐快速排序，先..."                   ← 中断时已生成的部分
tool_call: search_algorithm("sorting")                    ← 已执行
tool:      "[搜索结果...]"
tool_call: write_file("sort.py", ...)                     ← 被中断跳过
tool:      "[Tool execution skipped — user sent a new message]"
user:      "用 Python 写"                                  ← 新消息
```

agent 看得到自己被打断的痕迹，知道前一轮做到哪里、还差什么没做，能合理衔接——而不是表现得像"忘了之前在干嘛"。

### 具体场景走一遍

```text
张三发"帮我写个排序算法"
  → active_sessions 里没有张三 → 标记活跃，启动后台任务
  → agent 开始调 LLM...

张三发"用 Python 写"（agent 正在等 LLM 的流式回复）
  → active_sessions 里有张三 → 暂存这条消息
  → 调 agent.interrupt("用 Python 写")
  → agent._interrupt_requested = True
  → agent 在下一个 stream event 检查到标志 → break 退出流
  → agent 结束当前循环，返回已有的部分回复
  → 部分回复发给张三
  → 检查 pending_messages → 有"用 Python 写"
  → 从数据库加载最新历史（包含消息1和部分回复）→ 处理消息2

李四发"今天天气怎么样"（和张三同时）
  → 不同的 session key → 完全独立的后台任务，和张三并行
```

注意一个细节：`pending_messages` 只保留**最后一条**（直接赋值覆盖，不是 append 到列表）。如果张三连发三条"用 Python""要快排""加注释"，只有"加注释"会被处理。这是有意的设计——在消息平台上，用户连续快速发的多条消息通常是在补充同一个意思，处理最后一条就够了。

## 用微信走一遍完整流程

现在把所有概念串起来。你在企业微信里给 Hermes Agent 机器人发了一条私聊消息：**"帮我查一下今天的天气"**。

### 1. 微信服务器推消息给适配器

企业微信通过 WebSocket 推来一个 JSON：

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

### 2. 适配器翻译成 MessageEvent

`WeComAdapter._translate()` 把微信的 JSON 变成统一格式：

```python
MessageEvent(
    message_id="msg_001",
    text="帮我查一下今天的天气",
    source=SessionSource(platform="wecom", chat_id="zhangsan",
                         chat_type="dm", user_id="zhangsan"),
    message_type="text",
)
```

微信特有的 `cmd`、`headers`、`req_id` 都不见了——`MessageEvent` 只保留所有平台都有的公共信息。

### 3. 排队检查

适配器检查 `active_sessions`：`zhangsan` 没有正在处理的消息。标记为活跃，继续。

### 4. GatewayRunner 接手

`_handle_message(event)` 被调用：

```python
# 生成 session key
session_key = "agent:main:wecom:dm:zhangsan"

# 取出缓存的 agent（如果是张三第一次发消息，就创建新的）
agent = agents.get(session_key) or AIAgent(model=model, ...)

# 从数据库加载最新的历史（不靠 agent 内部记忆）
history = session_store.load_transcript(session_key)

# 调核心循环，把历史传进去（和 CLI 调的同一个方法）
response = agent.run_conversation(user_message, conversation_history=history)
# → "今天北京天气晴朗，最高温度 28°C..."
```

### 5. 回复送回微信

`GatewayRunner` 返回回复文本，`WeComAdapter.send()` 把它包成微信格式发出去：

```json
{
    "cmd": "aibot_send_msg",
    "body": {
        "chatid": "zhangsan",
        "msgtype": "markdown",
        "markdown": {"content": "今天北京天气晴朗，最高温度 28°C..."}
    }
}
```

用户在企业微信客户端看到 agent 的回复。

### 如果你同时也接了 Telegram

一个 Telegram 用户发了条消息。`TelegramAdapter` 收到后翻译成 `MessageEvent`（`platform="telegram"`），调同一个 `_handle_message`。区别只是 session key 变成了 `agent:main:telegram:dm:12345`。

**核心循环的代码一行都没变。**

## Hermes Agent 在这里的独特设计

上面的实现是教学简化版。真实的 Hermes Agent 还处理了几个不容忽视的现实问题：

### 1. 微信的消息分片

企业微信客户端会在 4000 字符处自动截断长消息。用户发了一段 6000 字的文本，微信会拆成两条消息。

如果 agent 分别回复这两条"半截消息"，结果就是驴唇不对马嘴。

适配器用**时间窗口**解决：收到第一条后等 0.6 秒，如果第二条也来了且第一条接近 4000 字，就继续等到 2 秒。超时后把所有片段拼起来当作一条完整消息处理。

### 2. 会话自动过期

CLI 场景下，关掉终端就是结束对话。但 Gateway 是长驻服务——一个用户三个月前聊的上下文还在。

Hermes Agent 支持两种自动重置：

- **空闲超时**：超过 24 小时没有新消息 → 下次来消息时自动开新会话
- **每日重置**：每天凌晨 4 点清空所有会话（记忆不丢，只是对话历史重新开始）

### 3. 崩溃恢复

Gateway 如果崩溃重启，之前正在处理中的请求可能处于半完成状态。

启动时不去恢复这些半完成的状态——而是把最近 120 秒内活跃的会话标记为"挂起"，下次收到消息时自动重置。**从干净状态重新开始比恢复脏状态安全得多。**

### 4. 两种微信接入模式

企业微信提供了两种机器人接入方式，Hermes Agent 各写了一个适配器：

| | WebSocket Bot（`WeComAdapter`） | HTTP 回调（`WecomCallbackAdapter`） |
|---|---|---|
| 连接方式 | 持久 WebSocket，实时双向 | HTTP 服务器，接收加密 XML 回调 |
| 媒体 | 图片、视频、语音、文件都支持 | 仅文本 |
| 多应用 | 单个 bot | 可以接多个自建应用 |
| 适用场景 | AI Bot 快速接入 | 企业自建应用，需要细粒度控制 |

两种模式对外表现不同，但都输出同一个 `MessageEvent`，对 `GatewayRunner` 来说完全透明。

## 它如何接到主循环里

和前面所有章节一样，Gateway 是在核心循环**之外**组装的。核心循环不知道 Gateway 的存在。

```text
CLI 启动方式：
  用户输入 → 创建 AIAgent → agent.run_conversation(用户输入)

Gateway 启动方式：
  1. load_config()         → 读哪些平台要启用，token 是什么
  2. GatewayRunner(config) → 创建 runner
  3. runner.start()        → 启动所有适配器，注册回调
  4. 等消息到来            → 适配器翻译 → _handle_message
                             → 创建 AIAgent → agent.run_conversation(消息文本)
```

两条路径最终都调到 `agent.run_conversation()`。AIAgent 只接收参数：模型、消息历史。它不关心调用者是谁。

## 初学者最容易犯的错

### 1. 把平台差异写进核心循环

"微信的 markdown 和 Telegram 不一样，在循环里 if 一下？"——不要。格式转换是适配器 `send()` 的事，核心循环只输出通用文本。

### 2. 每条消息都创建新 agent

用户连发三条。如果三条各创建一个 agent 实例，它们同时读写同一段历史，回复会互相打架。同一个 session key 的消息必须串行。

### 3. session key 维度不够

如果 key 只有 `platform:chat_id`，同一个群里所有人共享对话。通常需要加 `user_id` 做群内隔离——除非你确实想让群成员共享上下文。

### 4. 忽略消息去重

网络不稳定时同一条消息可能推两次。所有适配器都需要按 `message_id` 去重。

## 教学边界

这一章讲透三件事：

1. **为什么需要适配器** — 从"最笨的实现"推导出来，不是凭空定义的
2. **GatewayRunner 做什么** — 启动适配器、路由消息、调循环，就这三件事
3. **会话怎么隔离** — session key 的生成规则，为什么同一个群里不同用户的 key 不一样

先不管的：

- 每个平台适配器的具体实现 → 模式是一样的，看懂微信的就够
- 定时任务怎么把结果投递到不同平台 → `s15`
- 终端后端抽象（Docker / SSH） → `s14`
- Gateway 层面的 hook → 类似 `s08`

如果读者能做到"从一个只接微信的 while 循环，理解为什么需要适配器、为什么需要统一消息格式、为什么需要一个集中的路由器"，这一章就达标了。

## 学完这章后，你应该能回答

- 如果只接一个平台，需要 GatewayRunner 吗？从什么时候开始需要它？
- `MessageEvent` 解决了什么问题？如果没有它，加一个新平台要改哪些代码？
- 同一个微信群里的张三和李四，session key 一样吗？为什么？
- 张三在 agent 思考时又发了一条消息，会发生什么？
- `agent.run_conversation()` 知道消息来自微信还是 CLI 吗？

---

**一句话记住：Gateway 从一个问题开始——"怎么让同一个 agent 接微信"。然后你会发现需要会话隔离（session key），需要格式统一（MessageEvent），需要一个地方管理多个平台（GatewayRunner）。这些不是架构师凭空设计的，而是从具体问题中自然长出来的。**
