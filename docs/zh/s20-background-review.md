# s20: Background Review (后台审视)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > [ s20 ] > s21 > s22 > s23 > s24`

> *用户很少主动说"帮我记住这个"。agent 需要自己注意到什么值得记、什么值得抽象成技能——然后在后台默默完成，不打断用户的工作。*

![后台审视流程](../../illustrations/s20-background-review/01-flowchart-background-review.png)

## 这一章要解决什么问题

s07 讲了记忆系统，s08 讲了技能系统。但它们都有一个前提：**agent 主动调用了 memory 或 skill_manage 工具。**

问题是：agent 在忙着帮用户解决问题的时候，很少会"突然想起来"去更新记忆。

**场景：错过的偏好。**

```text
Turn 1: 用户: 帮我看看这个 Python 项目
Turn 2: agent: [读文件、分析代码]
Turn 3: 用户: 对了，我不喜欢用分号结尾，也不喜欢用 type hints
Turn 4: agent: 好的。[继续分析代码]
Turn 5: 用户: 帮我重构 parser.py
Turn 6-10: agent: [重构文件，偶尔还是写了 type hints]
```

用户在 Turn 3 表达了偏好，但 agent 当时正忙着分析代码，没有想到去调 `memory_tool` 把这个偏好存下来。下次新对话开始，agent 完全不记得这件事。

**如果有后台审视：**

```text
Turn 10 完成后 → 后台线程启动
  审视 agent 读完完整对话历史
  发现 Turn 3 的偏好信息
  调 memory_tool 写入 USER.md:
    "用户不喜欢分号结尾和 type hints"
  静默完成，用户无感知

下次新对话 → system prompt 里已经有这条记忆
```

这就是 Background Review 解决的问题：**让 agent 在对话结束后"回过头看一遍"，捕获工作中遗漏的知识。**

## 建议联读

- [`s07-memory-system.md`](./s07-memory-system.md) — 记忆的读写机制，审视 agent 直接复用
- [`s08-skill-system.md`](./s08-skill-system.md) — 技能的创建/编辑，审视 agent 可以自动创建新 skill
- [`s10-subagent-delegation.md`](./s10-subagent-delegation.md) — 对比：子 agent 是同步的，审视是异步的

## 先解释几个名词

### 什么是后台审视

主 agent 完成一轮对话后，在后台启动一个**独立的 agent 实例**，把完整对话历史交给它，让它回答一个问题：

> "这次对话里有什么值得记住的？有什么可以抽象成技能的？"

如果有，审视 agent 直接调 memory/skill 工具更新。如果没有，它说"Nothing to save"然后退出。

### 什么是双计数器

后台审视有两个独立的触发计数器：

- **`_turns_since_memory`** — 每过 N 轮用户对话（默认 10），触发记忆审视
- **`_iters_since_skill`** — 每过 N 次工具调用迭代（默认 10），触发技能审视

为什么是两个不同的单位？

- **记忆**关注的是用户说了什么 → 用"用户发了几条消息"衡量
- **技能**关注的是 agent 做了什么 → 用"agent 调了几次工具"衡量

一个用户可能发了 10 条消息但 agent 只调了 2 次工具（纯聊天），也可能发了 1 条消息但 agent 调了 20 次工具（复杂任务）。两种情况需要不同的审视。

### 审视 agent 和子 agent 有什么区别

读者学过 s10 的 subagent，可能会问：这不就是又创建了一个 agent 吗？

| | s10 子 agent | s20 后台审视 |
|---|---|---|
| 目的 | 完成用户的子任务 | 自省，更新记忆/技能 |
| 时机 | 用户任务执行中 | 用户任务完成后 |
| 阻塞 | **同步**，阻塞父 agent | **异步**，daemon thread |
| 迭代预算 | 和父共享（用多了父就少了） | **独立预算**（max=8） |
| 结果去向 | 摘要返回给父 → 放进 messages | 直接写入 MEMORY.md / skills/ |
| 失败处理 | 报错给用户 | **静默吞掉**，best-effort |

关键区别：子 agent 是为用户工作的延伸，审视 agent 是 agent 自己的学习过程。

## 最小心智模型

```text
主 agent 对话循环
  │
  │  每轮结束后检查两个计数器：
  │    _turns_since_memory >= 10?
  │    _iters_since_skill >= 10?
  │
  │  如果任一触发：
  v
_spawn_background_review()
  │
  │  1. 复制 messages（snapshot）
  │  2. 选择审视 prompt（记忆/技能/混合）
  │  3. 创建新 AIAgent(max_iterations=8, nudge_interval=0)
  │  4. 启动 daemon thread
  │
  v
后台线程
  │  review_agent.run_conversation(
  │      prompt = "审视这段对话，有什么值得记住的？"
  │      history = messages_snapshot
  │  )
  │
  │  审视 agent 可以调用：
  │    - memory_tool → 写入 MEMORY.md / USER.md
  │    - skill_manage → 创建/编辑技能文件
  │
  │  完成后静默退出
  │  （主 agent 和用户完全不受影响）
  v
MEMORY.md / skills/ 被更新
  → 下次对话的 system prompt 自动包含新记忆/技能
```

## 关键数据结构

### 审视触发状态

```python
# 在 AIAgent.__init__ 里
self._turns_since_memory = 0     # 用户消息计数
self._iters_since_skill = 0     # 工具迭代计数
self._memory_nudge_interval = 10 # 触发阈值（可配）
self._skill_nudge_interval = 10  # 触发阈值（可配）
```

### 审视 prompt

```python
_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory "
    "if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves — their persona, "
    "desires, preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave?\n\n"
    "If something stands out, save it using the memory tool. "
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating "
    "a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that "
    "required trial and error, or changing course due to experiential "
    "findings along the way?\n\n"
    "If a relevant skill already exists, update it. Otherwise, create "
    "a new skill if the approach is reusable.\n"
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)
```

注意 prompt 最后一句："If nothing is worth saving, just say 'Nothing to save.' and stop." 这很重要——不然审视 agent 会在没什么可写的时候强行编造。

## 最小实现

### 第一步：双计数器

在 `run_conversation` 的主循环里维护两个计数器：

```python
def run_conversation(self, user_message, ...):
    # 用户消息到来 → 记忆计数器 +1
    self._turns_since_memory += 1

    for iteration in range(MAX_ITERATIONS):
        # ... 模型调用 ...

        if assistant_msg.tool_calls:
            # 工具调用 → 技能计数器 +1
            self._iters_since_skill += 1

            for tool_call in assistant_msg.tool_calls:
                # 用户手动调了 memory/skill → 重置计数器
                if tool_call.function.name in ("memory", "skill_manage"):
                    self._turns_since_memory = 0
                    self._iters_since_skill = 0
```

**为什么手动调用会重置计数器？** 如果用户刚主动说"帮我记住这个"，agent 调了 memory_tool，那接下来就不需要后台审视再审一遍了。重置计数器避免重复工作。

### 第二步：触发判断

对话结束后（`run_conversation` 返回前）检查是否触发：

```python
    # run_conversation 即将返回
    should_review_memory = (
        self._memory_nudge_interval > 0
        and self._turns_since_memory >= self._memory_nudge_interval
    )
    should_review_skills = (
        self._skill_nudge_interval > 0
        and self._iters_since_skill >= self._skill_nudge_interval
    )

    if should_review_memory or should_review_skills:
        self._turns_since_memory = 0
        self._iters_since_skill = 0
        self._spawn_background_review(
            messages_snapshot=list(messages),  # snapshot copy
            review_memory=should_review_memory,
            review_skills=should_review_skills,
        )

    return {"final_response": ..., "messages": messages}
```

### 第三步：后台线程执行

```python
def _spawn_background_review(self, messages_snapshot, review_memory, review_skills):
    # 选择 prompt
    if review_memory and review_skills:
        prompt = _COMBINED_REVIEW_PROMPT
    elif review_memory:
        prompt = _MEMORY_REVIEW_PROMPT
    else:
        prompt = _SKILL_REVIEW_PROMPT

    def _run_review():
        import contextlib

        # 审视 agent：独立实例，共享 MemoryStore
        review_agent = create_review_agent(
            parent=self,
            max_iterations=8,
        )

        # 静默执行：stdout/stderr → /dev/null
        with open(os.devnull, "w") as devnull, \
             contextlib.redirect_stdout(devnull), \
             contextlib.redirect_stderr(devnull):
            try:
                review_agent.run_conversation(
                    user_message=prompt,
                    history=messages_snapshot,
                )
            except Exception:
                pass  # best-effort: 审视失败不影响用户

    # daemon=True：主进程退出时线程自动结束
    thread = threading.Thread(target=_run_review, daemon=True,
                              name="bg-review")
    thread.start()
```

### 第四步：审视 agent 的创建（共享与隔离）

```python
def create_review_agent(parent, max_iterations=8):
    """Create an isolated agent instance for background review."""
    agent = AIAgent(
        model=parent.model,
        max_iterations=max_iterations,
    )

    # 共享：MemoryStore 是同一个 Python 对象
    # 审视 agent 写入的记忆立刻对主 agent 可见（下次对话时）
    agent._memory_store = parent._memory_store

    # 隔离：nudge_interval 设为 0
    # 防止审视 agent 自己也触发审视 → 无限递归
    agent._memory_nudge_interval = 0
    agent._skill_nudge_interval = 0

    return agent
```

**共享 MemoryStore 的关键：** 审视 agent 调 `memory_tool` 写入时，操作的是和主 agent 同一个 MemoryStore 对象。写入直接持久化到 MEMORY.md。下次主 agent 启动新对话时，`build_system_prompt()` 会重新读 MEMORY.md，新记忆自动出现在 system prompt 里。

## 场景走读：一次完整的后台审视

```text
=== Turn 1-10：用户和 agent 讨论 Python 项目 ===

Turn 3: 用户: "我不喜欢 type hints，也别用 f-string"
  → _turns_since_memory = 3
  → agent 忙着分析代码，没有调 memory_tool

Turn 7: agent 调了 terminal、read_file、write_file
  → _iters_since_skill = 7（三次工具调用）

Turn 10: 对话结束
  → _turns_since_memory = 10 → 触发！
  → _iters_since_skill = 7 → 不触发（未到 10）

=== 后台审视启动（只审视记忆）===

1. 主 agent 返回最终回复给用户
   （用户已经看到回复，不受审视影响）

2. _spawn_background_review(
       messages_snapshot = [Turn 1-10 的完整历史],
       review_memory = True,
       review_skills = False,
   )

3. daemon thread 启动，创建 review_agent：
     model = 和主 agent 一样
     max_iterations = 8（不会跑太久）
     _memory_nudge_interval = 0（防级联）

4. review_agent 收到：
     history = Turn 1-10 完整历史
     prompt = "Review the conversation... Has the user revealed
               things about themselves...?"

5. review_agent 分析后发现 Turn 3 有用户偏好
   → 调 memory_tool：
     save(category="user", content="不喜欢 type hints 和 f-string")

6. MEMORY.md 被更新

7. review_agent 说 "Saved user preference." 然后退出
   （这句话输出到 /dev/null，用户看不到）

8. daemon thread 结束

=== 下次新对话 ===

build_system_prompt() 读取 MEMORY.md
  → system prompt 里多了：
    "User Profile: 不喜欢 type hints 和 f-string"
  → agent 这次写代码不会再用 type hints
```

## 场景二：为什么需要级联防护

如果审视 agent 的 `_memory_nudge_interval` 不设为 0 会怎样？

```text
主 agent 完成 → 触发审视 agent A
审视 agent A 调了 memory_tool → _turns_since_memory++
  → A 自己又触发审视 agent B
    审视 agent B 调了 memory_tool → 又触发审视 agent C
      → C 触发 D → D 触发 E → ...
```

每个审视 agent 都在后台线程里创建新线程，无限递归直到内存耗尽。

**修：审视 agent 创建时 `nudge_interval=0`，永远不触发自己的审视。**

一行配置解决一个可以炸掉系统的问题。

## Hermes Agent 的独特设计

### 审视不是总结

大多数 agent 框架的"自省"是生成对话摘要。Hermes Agent 不做摘要——**它让审视 agent 直接操作工具。**

审视 agent 和主 agent 有一模一样的工具访问权。它不是"分析对话然后输出建议"，而是"分析对话然后直接写 MEMORY.md、直接创建 skill 文件"。

这是一个关键区别：摘要是被动的（人需要看摘要再行动），工具操作是主动的（agent 自己就把活干了）。

### best-effort 设计

整个后台审视系统可以失败，不影响用户体验：

- daemon thread：主进程退出时自动清理
- `try/except: pass`：任何异常静默吞掉
- stdout/stderr → devnull：不会在终端上打印奇怪的东西
- max_iterations=8：不会跑太久浪费 API 费用

这不是偷懒——这是有意的设计。审视是锦上添花，不是核心功能。如果审视失败了，唯一的后果是"这次没学到东西"，下次还会再试。

## 初学者最容易犯的错

### 1. 忘了防级联

审视 agent 不设 `nudge_interval=0`，导致无限递归。

**修：创建审视 agent 时立刻设 `_memory_nudge_interval = 0` 和 `_skill_nudge_interval = 0`。**

### 2. 传 messages 引用而不是 snapshot

```python
# 错：传引用，主 agent 后续修改会影响审视
self._spawn_background_review(messages_snapshot=messages)

# 对：传 snapshot（浅拷贝）
self._spawn_background_review(messages_snapshot=list(messages))
```

审视 agent 在后台线程里读 messages。如果传的是引用，主 agent 在下一轮对话中修改了 messages 列表，审视 agent 读到的就是被污染的数据。

### 3. 审视 prompt 写得太泛

```text
# 错：太泛，审视 agent 会把每句话都试图存起来
"总结这段对话的所有要点"

# 对：聚焦，只存"值得记住"的
"Has the user revealed things about themselves...
 If nothing is worth saving, just say 'Nothing to save.'"
```

审视 prompt 必须有明确的止步条件（"Nothing to save"），不然审视 agent 会强行创造不存在的"发现"。

### 4. 审视 agent 的迭代预算设太高

max_iterations=90 的审视 agent 可能花几分钟、烧几万 token 来"思考"。审视应该是快速扫描，不是深度分析。

**修：max_iterations=8 足够了。如果 8 轮还没完成审视，说明 prompt 有问题。**

### 5. 没有在手动操作后重置计数器

用户说"帮我记住我不喜欢 type hints"，agent 调了 memory_tool。但计数器没重置，10 轮后审视 agent 又把同样的偏好写了一遍。

**修：工具分发时检查，如果调了 memory 或 skill_manage，重置对应的计数器。**

## 教学边界

这一章讲五件事：

1. **为什么需要自动审视** — agent 工作时顾不上自省
2. **双计数器** — turns（记忆）vs iterations（技能），手动操作重置
3. **隔离与共享** — messages snapshot vs 共享 MemoryStore，和 s10 子 agent 对比
4. **审视 prompt 设计** — 聚焦"什么值得存"，必须有止步条件
5. **best-effort + 级联防护** — daemon thread、静默失败、nudge_interval=0

不讲的：

- 审视结果的 Gateway 回传（`background_review_callback`）→ 生产细节
- 文件锁实现 → MemoryStore 内部细节，s07 已覆盖
- 审视频率的自适应调整 → 高级优化
- 多轮审视的去重 → 生产优化

## 这一章和其他章节的关系

- **s07** 的记忆系统 → 审视 agent 调的就是同一个 `memory_tool`
- **s08** 的技能系统 → 审视 agent 可以创建新 skill，调的是 `skill_manage`
- **s10** 的子 agent → 对比：同步 vs 异步、共享预算 vs 独立预算
- **s21** 的技能创作闭环 → s20 是"发现值得存的东西"，s21 是"怎么把它变成高质量的 skill"

**s20 是阶段 5 的起点。** 从这里开始，Hermes Agent 不再只是一个执行工具的循环——它开始**从自己的经验中学习**。

## 学完这章后，你应该能回答

- 为什么记忆审视用"轮数"触发，技能审视用"工具迭代次数"触发？
- 审视 agent 和 s10 的子 agent 有什么本质区别？
- 为什么 MemoryStore 是共享的，但 messages 是 snapshot？
- 审视 agent 的 nudge_interval 设为 0 是防什么？
- 如果后台审视失败了，用户会受到什么影响？

---

**一句话记住：后台审视是 agent 的"事后反思"——对话结束后在后台线程里用独立 agent 实例回顾对话，自动更新记忆和技能。共享 MemoryStore 让变更即时生效，nudge_interval=0 防止无限递归。**
