# s07: Memory System (记忆系统)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > [ s07 ] > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *不是所有信息都该进入 memory；只有跨会话仍然有价值的信息，才值得留下。*

## 这一章在解决什么问题

如果一个 agent 每次新会话都完全从零开始，它就会不断忘记这些事情：

- 用户偏好什么代码风格
- 用户多次纠正过的错误做法
- 某些不容易从代码直接看出来的项目约定
- 某些外部资源在哪里找

这会让系统显得"每次都像第一次合作"。

所以需要 memory。

## 但先立一个边界：memory 不是什么都存

这是这一章最容易讲歪的地方。

memory 不是"把一切有用信息都记下来"。如果你这样做，很快就会出现两个问题：

1. memory 变成垃圾堆，越存越乱
2. agent 开始依赖过时记忆，而不是读取当前真实状态

所以这章必须先立一个原则：

**只有那些跨会话仍然有价值，而且不能轻易从当前项目状态直接推出来的信息，才适合进入 memory。**

![MEMORY.md vs USER.md 对比](../../illustrations/s07-memory-system/01-comparison-memory-types.png)

## 先解释几个名词

### 什么是 MEMORY.md

agent 的工作笔记本。注入 system prompt 时的标题是：

```text
MEMORY (your personal notes) [62% — 1,364/2,200 chars]
```

存的是 agent 自己在工作中学到的**关于环境和项目**的信息。跟用户是谁无关，跟"这个工作环境是什么样的"有关。

具体例子：

```text
§ 项目用 pytest，不是 unittest。跑测试用 pytest -x 快速失败
§ 这台机器是 macOS ARM，Homebrew 路径在 /opt/homebrew
§ auth 模块重写是因为合规要求，不是技术债
§ CI 配置在 .github/workflows/ci.yml，合并前必须过 lint
§ 不要用 asyncio.run()，这个项目有持久化事件循环，用 bridge_async()
```

一句话：**MEMORY.md 记的是"这个项目 / 这个环境是怎么回事"。**

### 什么是 USER.md

用户画像。注入 system prompt 时的标题是：

```text
USER PROFILE (who the user is) [48% — 660/1,375 chars]
```

存的是 agent 了解到的**关于用户本人**的信息。跟项目无关，跟"这个人是谁、喜欢什么、讨厌什么"有关。

具体例子：

```text
§ 名字是张三，后端工程师，写 Go 十年，Python 两年
§ 讨厌 mock 测试，上次 mock 和生产环境不一致导致线上事故
§ 回答要简洁，不要在末尾总结刚做了什么
§ 偏好 tabs 缩进，变量用 snake_case
§ 时区 UTC+8，一般工作时间 10:00-22:00
```

一句话：**USER.md 记的是"这个人是谁、怎么和他合作最顺"。**

### 为什么分两个文件

源码里，两个文件通过同一个 `memory` 工具操作，用 `target` 参数区分：

```python
# 存到 MEMORY.md
memory(action="add", target="memory", content="项目用 pytest 跑测试")

# 存到 USER.md
memory(action="add", target="user", content="用户偏好 tabs 缩进")
```

分开的核心原因是**生命周期不同**：

| | MEMORY.md | USER.md |
|---|---|---|
| 关于谁 | 项目和环境 | 用户本人 |
| 字符限制 | 2,200 | 1,375 |
| 换项目时 | 大概率要重新积累 | 直接复用 |
| 换用户时 | 大概率还有用 | 需要重新积累 |

举个例子：你从项目 A 切换到项目 B，USER.md 里"用户偏好 tabs 缩进"和"回答要简洁"依然成立。但 MEMORY.md 里"项目用 pytest"可能就不对了——新项目用的是 vitest。

Hermes Agent 的 Profile 系统（`s11`）让不同 profile 各自有独立的 `memories/` 目录，所以切换 profile 时两个文件都可以是独立的。

### 判断存哪里的简单规则

问自己一个问题：**"如果换了一个完全不同的项目，这条信息还有用吗？"**

- 有用 → USER.md（因为它描述的是用户，不是项目）
- 没用 → MEMORY.md（因为它描述的是当前环境）

边界案例："用户讨厌 mock 测试" → 存 USER.md。虽然它跟测试有关，但它描述的是**用户的偏好**，换了项目这条依然成立。

### 什么是"冻结快照"

Hermes Agent 在会话开始时把 MEMORY.md 和 USER.md 读进来，冻结成 system prompt 的一部分。

**会话中间对 memory 的修改会立刻写到磁盘，但不会改变当前会话的 system prompt。**

为什么？因为改了 system prompt 就会破坏 Anthropic 的 prompt cache。新的 memory 要到下次会话开始时才生效。

## 哪些该存，哪些不该存

这比"怎么实现"更重要。

### 该存的

| 类型 | 例子 |
|---|---|
| 用户偏好 | "偏好 tabs 缩进"、"回答要简洁" |
| 用户纠正 | "不要 mock 数据库，用真实测试库" |
| 项目约定 | "这个 auth 重写是因为合规要求，不是技术债" |
| 外部资源 | "bug 跟踪在 Linear 的 INGEST 项目里" |

### 不该存的

| 不该存的 | 为什么 |
|---|---|
| 文件结构、函数签名、目录布局 | 可以重新读代码得到 |
| 当前任务进度 | 这是 task / plan，不是 memory |
| 当前分支名、当前 PR 号 | 很快会过时 |
| 修 bug 的具体代码 | 代码和提交记录才是准确信息 |
| 密钥、密码 | 安全风险 |

这条边界一定要稳。否则 memory 会从"帮助系统长期变聪明"变成"帮助系统长期产生幻觉"。

## 最小心智模型

```text
会话 1：用户说"我讨厌 mock 测试"
   |
   v
agent 调用 memory 工具，写入 MEMORY.md
   |
   v
会话结束，MEMORY.md 已在磁盘上

────── 时间过去 ──────

会话 2 开始
   |
   v
读 MEMORY.md → 冻结为 system prompt 的一部分
   |
   v
agent 知道不要用 mock → 直接写真实测试
```

关键点：**写入是即时的（磁盘），生效是延迟的（下次会话）。** 这个设计是为了保护 prompt cache。

## 关键数据结构

### 1. Memory 条目

Hermes Agent 的 memory 不是结构化数据库。它就是 markdown 文件里的条目，用 `§` 分隔：

```text
§ User prefers tabs over spaces for indentation
§ Project uses pytest, not unittest. Run with `pytest -x` for fail-fast
§ Auth rewrite is driven by legal/compliance, not tech debt
```

每个条目就是一句话或一小段文字。简单、可读、agent 能直接读写。

### 2. 字符限制

MEMORY.md 默认最多 2200 字符。USER.md 默认最多 1375 字符。

为什么限制这么紧？因为 memory 会进入每次会话的 system prompt。如果 memory 无限增长，它会吃掉越来越多的上下文窗口。

agent 在空间不够时，要自己决定删掉哪条旧 memory 来腾空间。这迫使 agent 保持 memory 精炼。

### 3. 冻结快照

```python
snapshot = {
    "memory": "§ User prefers tabs...\n§ Project uses pytest...",
    "user": "§ Senior engineer, prefers concise answers...",
}
```

会话开始时生成，之后不再改变。tool 调用返回的是磁盘上的实时状态，但 system prompt 里用的是冻结快照。

## 最小实现

### 第一步：定义存储格式

```python
ENTRY_DELIMITER = "§"

def parse_entries(text):
    return [e.strip() for e in text.split(ENTRY_DELIMITER) if e.strip()]

def render_entries(entries):
    return "\n".join(f"{ENTRY_DELIMITER} {e}" for e in entries)
```

### 第二步：读写磁盘

```python
def load_memory(path):
    if not path.exists():
        return []
    return parse_entries(path.read_text())

def save_memory(path, entries):
    path.write_text(render_entries(entries))
```

### 第三步：提供 memory 工具

最小参数：`action`（add / replace / remove / read）+ `content`。

```python
def handle_memory(action, content=None, target="memory"):
    entries = load_memory(path_for(target))
    
    if action == "add":
        entries.append(content)
        # 如果超过字符限制，要求 agent 自己清理
        save_memory(path_for(target), entries)
        return f"Added. {len(entries)} entries, {char_count} chars."
    
    if action == "remove":
        # 用子串匹配找到要删的条目
        entries = [e for e in entries if content not in e]
        save_memory(path_for(target), entries)
        return f"Removed. {len(entries)} entries remaining."
    
    if action == "read":
        return render_entries(entries)
```

### 第四步：会话开始时冻结快照

```python
# 在 _build_system_prompt() 里
memory_block = memory_store.format_for_system_prompt("memory")
user_block = memory_store.format_for_system_prompt("user")
if memory_block:
    prompt_parts.append(memory_block)
if user_block:
    prompt_parts.append(user_block)
```

这一步和 `s04`（提示词组装）衔接。memory 是 system prompt 的来源之一。

## Hermes Agent 在这里的独特设计

### 1. 冻结快照 + 实时磁盘

大多数 agent 的 memory 改了就立刻生效。Hermes Agent 刻意分开了两层：

- 磁盘写入是即时的（durable）
- system prompt 注入是冻结的（stable）

这是为了 prompt cache。如果每次 memory 变了就更新 system prompt，Anthropic 的缓存前缀就失效了，每轮 API 调用都要重新传完整 prompt。

### 2. 文件锁

Gateway 场景下，多个会话可能同时写 MEMORY.md。Hermes Agent 用文件锁（`fcntl.flock`）保证原子性。

### 3. 外部记忆提供者

除了内置的 MEMORY.md / USER.md，Hermes Agent 还支持通过 plugin 接入外部记忆提供者（比如向量数据库）。

外部记忆的内容不进 system prompt（会破坏缓存），而是注入到 user message 里。这样 system prompt 保持稳定，外部记忆的动态内容走另一条路。

### 4. 记忆定期提醒（两套触发机制）

Hermes Agent 有两套独立的记忆触发机制，解决不同场景：

#### 机制 A：定期后台审查（nudge）

```python
self._memory_nudge_interval = 10   # 默认每 10 轮用户对话触发一次
self._turns_since_memory = 0       # 计数器
```

每次用户发消息，计数器 +1。当计数器达到 `nudge_interval` 时：

```text
用户第 1 轮 → 计数器 1
用户第 2 轮 → 计数器 2
...
用户第 10 轮 → 计数器 10 → 触发！计数器归零
```

触发后，系统在**响应已经返回给用户之后**，在后台线程里创建一个独立的"审查 agent"：

```python
# 后台线程里
review_agent = AIAgent(
    model=self.model,
    max_iterations=8,       # 只给 8 轮，快速审查
    quiet_mode=True,        # 完全静默，不产生用户可见输出
)
review_agent._memory_store = self._memory_store    # 共享同一个 memory 存储
review_agent._memory_nudge_interval = 0            # 审查 agent 自己不再触发 nudge

review_agent.run_conversation(
    user_message=MEMORY_REVIEW_PROMPT,              # 审查提示词
    conversation_history=messages_snapshot,          # 当前对话的快照
)
```

审查提示词长这样：

```text
Review the conversation above and consider saving to memory if appropriate.

Focus on:
1. Has the user revealed things about themselves — their persona, desires,
   preferences, or personal details worth remembering?
2. Has the user expressed expectations about how you should behave, their
   work style, or ways they want you to operate?

If something stands out, save it using the memory tool.
If nothing is worth saving, just say 'Nothing to save.' and stop.
```

关键设计：

- **响应后执行** — 不和用户的主任务竞争模型注意力
- **独立 agent** — stdout/stderr 都重定向到 /dev/null，用户完全无感
- **共享 memory store** — 审查 agent 写入的 memory 直接持久化到磁盘
- **只给 8 轮** — 审查是快速扫描，不是深度分析

#### 机制 B：压缩前紧急冲刷（flush）

当对话即将被压缩（`s05`）或会话即将重置时，系统会做一次"紧急记忆保存"：

```python
self._memory_flush_min_turns = 6   # 至少 6 轮用户对话后才触发 flush
```

flush 的做法不同于 nudge — 它不是后台审查，而是**直接在当前对话里注入一条消息**：

```python
flush_content = (
    "[System: The session is being compressed. "
    "Save anything worth remembering — prioritize user preferences, "
    "corrections, and recurring patterns over task-specific details.]"
)
```

模型看到这条消息后，会在当前上下文里直接调用 memory 工具保存。保存完毕后，系统把 flush 相关的消息全部从历史里删除（不留痕迹）。

#### 两套机制的分工

| | 定期 nudge | 压缩前 flush |
|---|---|---|
| 触发时机 | 每 N 轮用户对话 | 压缩 / 会话重置前 |
| 执行方式 | 后台线程，独立 agent | 当前对话，注入消息 |
| 用户感知 | 完全无感 | 完全无感（注入后删除） |
| 默认阈值 | 10 轮 | 6 轮 |
| 目的 | 日常积累 | 最后机会，防止丢失 |
| 配置项 | `memory.nudge_interval` | `memory.flush_min_turns` |

## memory、session、SOUL.md、HERMES.md 的边界

| | memory | session | SOUL.md | HERMES.md |
|---|---|---|---|---|
| 是什么 | 跨会话的精选知识 | 一次对话的完整记录 | 人设定义 | 项目规则 |
| 谁写 | agent | 系统自动 | 用户 | 开发者 |
| 变化频率 | 经常 | 每次对话 | 很少 | 按项目固定 |
| 大小 | 小（有限制） | 大（完整历史） | 小 | 中等 |

## 初学者最容易犯的错

### 1. 把代码结构也存进 memory

"这个项目有 src/ 和 tests/" — 不该存，系统可以重新读。

### 2. 把当前任务进度存进 memory

"我正在改认证模块" — 这是 task / plan，不是 memory。

### 3. 把 memory 当成绝对真相

memory 可能过时。用来提供方向，不用来替代当前观察。如果 memory 和当前代码冲突，优先相信眼前的真实状态。

### 4. 不设字符限制

memory 无限增长，system prompt 越来越大，上下文窗口被吃掉。

### 5. 会话中间改了 memory 就期望立刻生效

冻结快照模式下，改了要到下次会话才生效。这是设计，不是 bug。

## 教学边界

这章最重要的，不是 memory 以后还能多自动、多复杂，而是先把存储边界讲清楚：

- 什么值得跨会话留下
- 什么只是当前任务状态，不该进 memory
- memory 和 session / SOUL.md / HERMES.md 各自负责什么

刻意停住的：外部记忆提供者的完整 plugin 架构、向量数据库集成、memory 自动整合和去重策略。

如果读者能做到"agent 下次开新会话时还记得上次的用户偏好"，这一章就达标了。

## 学完这章后，你应该能回答

- 为什么 memory 不是"什么都记"？
- MEMORY.md 和 USER.md 为什么要分开？
- 什么样的信息适合跨会话保存？什么不适合？
- 为什么会话中间改了 memory 不会立刻影响 system prompt？
- memory 和 session / SOUL.md / HERMES.md 的边界各是什么？

---

**一句话记住：memory 保存的是"以后还可能有价值、但当前代码里不容易直接重新看出来"的信息。Hermes Agent 用冻结快照保护 prompt cache，写入即时但生效延迟。**
