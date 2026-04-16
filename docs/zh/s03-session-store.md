# s03: Session Store (会话持久化)

`s00 > s01 > s02 > [ s03 ] > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *程序一退出，对话全丢。Gateway 两个平台的消息同时到，文件锁打架。*  
> 这一章用 SQLite 解决这两个问题。

## 这一章要解决什么问题

到了 `s02`，agent 已经有了完整的工具注册和分发系统。

但有一个致命缺陷：`messages` 只在内存里。进程退出，一切归零。

即使是 CLI 单人用也不能忍——退出后对话全丢，`--continue` 继续上次对话都做不到。Gateway 模式下问题更大——多个平台的消息同时到达，这些并发的对话需要：

1. 读到之前的对话历史（不然每次都从零开始）
2. 并发写入同一个数据库时不产生写锁冲突（不同 session 的数据虽然不交叉，但写的是同一个数据库文件，SQLite 整库只有一把写锁）
3. 事后能搜索历史会话

用文件系统（每个 session 一个 JSON 文件）能解决第 1 点，第 2 点因为文件天然隔离反而没问题，但丢掉了事务保证；第 3 点要遍历所有文件。

所以 Hermes Agent 选了 SQLite。不是因为"SQLite 比文件高级"，而是因为它同时解决了上面三个问题。

## 先解释几个名词

### 什么是 session

`session` 是一次完整的对话。

它有开始时间、结束时间、唯一 ID。对话里的所有 messages 都属于这个 session。

在 CLI 模式下，从你启动到退出是一个 session。  
在 Gateway 模式下，同一个聊天窗口里的连续对话是一个 session。

### 什么是 WAL 模式

WAL 是 SQLite 的一种日志模式（Write-Ahead Logging）。开启方法就一行：

```python
conn.execute("PRAGMA journal_mode=WAL")
```

**先看问题：为什么需要 WAL？**

SQLite 默认模式下，有人在写数据库时，其他人连读都不行：

```text
Telegram 适配器正在写消息 → 整个数据库被锁住
                              ↓
Discord 适配器想读历史消息 → ❌ 等着，读都不行
```

CLI 单人用无所谓，但 Gateway 模式下多个平台同时收发消息，这就卡住了。

![SQLite 默认模式 vs WAL 模式](../../illustrations/s03-session-store/01-comparison-wal.png)

**WAL 模式怎么解决的？**

开了 WAL 之后，写操作先写到一个临时的日志文件里，不动主数据库。读操作继续读主数据库文件，不受影响：

```text
Telegram 适配器正在写消息 → 写到 WAL 日志文件里（不动主数据库）
                              ↓
Discord 适配器想读历史消息 → ✅ 照读，读的是主数据库
```

日志会在合适的时机自动合并回主数据库。

但注意：**写和写之间还是要排队的。** 两个适配器同时想写，一个要等另一个写完。

```text
默认模式：
  写 ──阻塞──> 读 ❌
  写 ──阻塞──> 写 ❌

WAL 模式：
  写 ──不阻塞──> 读 ✅    ← 这是关键改进
  写 ──仍阻塞──> 写 ❌    ← 这个没变
```

### 什么是 FTS5

FTS5 是 SQLite 的全文搜索扩展（Full-Text Search 5）。

它让你能在大量历史消息中快速搜索关键词。不需要遍历所有行做 `LIKE '%keyword%'`。

### 什么是 parent_session_id

当对话太长触发上下文压缩时（`s05`），系统会创建一个新 session。新 session 通过 `parent_session_id` 指向旧 session。

这形成一条链：

```text
session_001 (完整历史, 500 条消息)
     ^
     | parent_session_id
session_002 (压缩摘要 + 新消息)
     ^
     | parent_session_id
session_003 (又压缩了一次)
```

旧历史不删除，只是归档。

### 什么是 source

每个 session 有一个 `source` 字段，标记消息来自哪个入口：`cli`、`telegram`、`discord`、`slack`、`weixin` 等。

这让你能按平台过滤会话："只看 Telegram 的对话"。

## 最小心智模型

![会话持久化生命周期](../../illustrations/s03-session-store/02-flowchart-session-lifecycle.png)

```text
agent 启动
  |
  v
新 session? ──是──> 建一条 session 记录
  |
  否（继续旧 session）
  |
  v
从 SQLite 读出历史 messages
  |
  v
传给 AIAgent.run_conversation()
  |
  v
每一轮对话结束后，新 messages 写入 SQLite
  |
  v
agent 退出
  |
  v
下次启动时，从 SQLite 读回来，对话还在
```

## 关键数据结构

### 1. Session 记录

最小教学版：

```python
session = {
    "id": "...",
    "source": "cli",
    "started_at": 1710000000.0,
}
```

完整系统还会存：model、system_prompt、parent_session_id、token 统计、费用估算。但最小版本只需要上面三个字段就能工作。

### 2. Message 记录

最小教学版：

```python
message = {
    "session_id": "...",
    "role": "user" | "assistant" | "tool",
    "content": "...",
    "timestamp": 1710000000.0,
}
```

完整系统还会存：tool_calls（JSON 序列化）、tool_call_id、tool_name、token_count。

### 3. FTS 索引

不是一个你直接操作的数据结构，而是 SQLite 自动维护的搜索索引。每次插入 message 时，SQLite trigger 自动更新 FTS 索引。

## 最小实现

### 第一步：建表

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

这就是最小版本。两张表，WAL 模式，能用。

### 第二步：创建 session

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

### 第三步：写入 messages

```python
def add_messages(conn, session_id, messages):
    for msg in messages:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, msg["role"], msg.get("content", ""), time.time()),
        )
    conn.commit()
```

### 第四步：读出历史

```python
def get_session_messages(conn, session_id):
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]
```

### 第五步：接到循环里

```python
# 启动时
session_id = create_session(conn, source="cli")

# 每轮对话后
new_messages = result["messages"][len(old_messages):]  # 只存新增的
add_messages(conn, session_id, new_messages)

# 下次启动时
history = get_session_messages(conn, session_id)
result = agent.run_conversation(user_message, conversation_history=history)
```

## Hermes Agent 在这里的独特设计

### 写锁冲突处理

SQLite 的 WAL 模式下，写和写仍然需要串行。默认的 busy handler 用确定性等待，高并发时会导致队列效应（所有人等同样长的时间）。

Hermes Agent 的做法：把 SQLite 超时设短（1 秒），然后在应用层做随机退避重试。随机间隔自然打散了竞争的写入者。

### system_prompt 缓存

Gateway 每条消息创建新的 AIAgent 实例。如果每次都重新组装 system prompt，中间可能因为 MEMORY.md 被改了导致 prompt 变化，Anthropic 的 prompt cache 就失效了。

所以 Hermes Agent 把第一次组装好的 system prompt 存到 session 表里。后续实例直接读缓存，保证 prompt 不变。

### schema 版本管理

数据库 schema 会随版本演进。Hermes Agent 维护一个 `schema_version` 表，启动时检查版本号。如果需要迁移，自动执行 ALTER TABLE。

## 初学者最容易犯的错

### 1. 不开 WAL 模式

默认模式下，一个写操作会阻塞所有读操作。Gateway 场景下 agent 在写消息时，另一个平台的读取请求会挂住。

### 2. 存整个 messages 列表而不是增量

每轮对话后把完整的 messages 列表全量写入，而不是只写新增的。对话越长，写入越慢。

### 3. 把 session_id 写死

每次启动都用同一个 session_id，所有对话混在一起。session_id 应该每次新对话生成一个。

### 4. 不处理 tool_calls 的序列化

`tool_calls` 是一个嵌套结构，不能直接存到 TEXT 字段。需要 JSON 序列化。

### 5. 在 Gateway 里不分 chat_id

不同平台的不同聊天窗口应该是不同的 session。如果所有消息都混到一个 session 里，agent 会把 A 用户的对话当成 B 用户的上下文。

## 到目前为止的完整循环

把 s01 的循环 + s02 的工具系统 + s03 的 session 持久化拼在一起，完整流程是这样的：

```text
程序启动
  │
  ├─ 新对话？─── 是 ──→ create_session() → 拿到 session_id
  │                      messages = []
  │
  └─ 继续旧对话？─ 是 ─→ 从 SQLite 读出历史 messages
                          messages = get_session_messages(session_id)
  │
  v
用户输入一条消息
  │
  v
messages.append({"role": "user", "content": 用户输入})
  │
  v
┌─────────────── 循环开始（最多 90 轮）──────────────┐
│                                                      │
│  拼装 api_messages = [system_prompt] + messages       │
│                          │                           │
│                          v                           │
│                    调用模型 API                       │
│                          │                           │
│                          v                           │
│              messages.append(assistant 回复)          │
│                          │                           │
│               有 tool_calls？                        │
│              /            \                          │
│            否              是                        │
│            │               │                         │
│            v               v                         │
│         循环结束     registry.dispatch(工具名, 参数)  │
│                           │                          │
│                           v                          │
│              messages.append(tool 结果)               │
│                           │                          │
│                           v                          │
│                        下一轮                        │
│                                                      │
└──────────────────────────────────────────────────────┘
  │
  v
把本轮新增的 messages 写入 SQLite
  │
  v
等待用户下一条输入（回到上面）
  │
  ...
  │
  v
程序退出 → 下次启动可以从 SQLite 读回来继续
```

用代码表示：

```python
# ── 启动 ──
conn = sqlite3.connect("state.db")
conn.execute("PRAGMA journal_mode=WAL")

if continue_session:
    messages = get_session_messages(conn, session_id)
else:
    session_id = create_session(conn, source="cli")
    messages = []

# ── 对话主循环 ──
while True:
    user_input = input("> ")
    if user_input == "exit":
        break

    messages.append({"role": "user", "content": user_input})
    old_len = len(messages)

    # s01 的核心循环
    for i in range(90):
        api_messages = [{"role": "system", "content": system_prompt}] + messages

        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4",
            messages=api_messages,
            tools=registry.get_definitions(),  # s02: 从注册表拿工具 schema
        )

        assistant_msg = response.choices[0].message
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [...] or None,
        })

        if not assistant_msg.tool_calls:
            break  # 模型说完了，退出内循环

        # s02: 注册表分发执行（自动处理同步/异步）
        for tc in assistant_msg.tool_calls:
            result = registry.dispatch(tc.function.name, tc.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # s03: 只把新增的 messages 写入 SQLite
    add_messages(conn, session_id, messages[old_len:])

    # 打印最后一条 assistant 回复
    print(messages[-1]["content"])
```

三层各管各的事：

| 层 | 职责 | 不管什么 |
|---|---|---|
| **s01 循环** | messages → API → tool_calls → 下一轮 | 不管工具怎么找到的，不管消息存哪 |
| **s02 工具** | 按名字查表、分发执行、同步/异步桥接 | 不管循环逻辑，不管持久化 |
| **s03 存储** | 写入 SQLite、读出历史、WAL 并发安全 | 不管循环怎么跑，不管工具怎么执行 |

## 教学边界

这一章讲的是：

**把 messages 从内存搬到 SQLite，让对话跨重启存活，让多平台并发安全。**

它还不是后面的上下文压缩（`s05`，会用到 parent_session_id）、记忆系统（`s07`，跨 session 的精选信息）、Gateway 会话路由（`s12`，按 chat_id 分配 session）。

刻意停住的东西：

- FTS5 的高级搜索语法
- token 统计和费用估算字段
- schema 迁移的具体 ALTER TABLE 逻辑
- Gateway 怎么根据 chat_id 找到正确的 session → `s12`

如果读者能做到"agent 退出后重启，对话还在"，这一章就达标了。

## 一句话记住

**Hermes Agent 用 SQLite + WAL 而不是文件系统，因为它从一开始就考虑了多平台并发场景——这不是优化，是 Gateway 模式的基本需求。**
