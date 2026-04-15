# s10: Subagent Delegation (子 Agent 委派)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > [ s10 ] > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *一个大任务，不一定要塞进一个上下文里做完。把子任务交给独立上下文，做完只把结果带回来。*

## 这一章要解决什么问题

到了 `s09`，agent 已经有了工具、持久化、记忆、技能、权限。它真的能独立干活了。

但随着任务变复杂，一个问题开始暴露：

用户可能只说了一句：

> "帮我调研一下 Python 3.12 的新特性，然后更新 README。"

agent 为了完成这件事，可能要：

- 搜索了 10 篇文章
- 读了 5 个文件
- 写了 3 次文件
- 跑了 2 次测试

这些中间过程全部堆在同一个 `messages` 列表里，上下文迅速膨胀。后续如果用户再问一个完全无关的问题，模型要在一堆"搜索结果"和"文件内容"的噪声里找到有用信息。

更关键的是：如果两个子任务互不相关（比如"搜索新特性"和"检查测试覆盖率"），它们的中间过程互相污染，反而降低了模型的推理质量。

这就是子 agent 要解决的问题：

**把局部任务放进独立上下文里做，做完只把必要结果带回来。父 agent 的上下文保持干净。**

## 先解释几个名词

### 什么是父 agent

当前正在和用户对话、持有主 `messages` 的 agent 实例。

### 什么是子 agent（subagent）

父 agent 临时创建出来的、拥有独立 `messages` 的 agent 实例。它执行完子任务后返回结果，然后销毁。

子 agent 和父 agent 共享同一个代码路径（都是 `AIAgent.run_conversation()`），区别只在于：

- 子 agent 有自己的 `messages`（上下文隔离）
- 子 agent 的工具集是受限的（不能再委派、不能改记忆）
- 子 agent 消耗的是父 agent 的 iteration budget

### 什么是 iteration budget 共享

子 agent 不是"另外给 90 次 API 调用"。它从父 agent 的预算里扣：

```text
父 agent budget = 90
  iter 1-10: 父 agent 自己干活                (剩 80)
  iter 11:   父 agent 派子 agent 去搜索
             └─ 子 agent 用了 15 iter         (剩 65)
  iter 12+:  父 agent 继续，从 65 开始
```

这防止了子 agent 失控地消耗资源。

### 什么是委派深度限制

Hermes Agent 限制委派深度为 2 层：父 → 子。子 agent 不能再派子 agent。

为什么？因为递归委派很容易失控。一层委派已经足够覆盖绝大多数场景。

## 最小心智模型

```text
父 agent
  |
  | 1. 模型调用 delegate_task 工具
  |    传入 goal + context + toolsets
  v
子 agent（独立 messages、受限工具集）
  |
  | 2. 在自己的上下文里读文件 / 搜索 / 执行命令
  |    中间过程全部留在子 agent 的 messages 里
  v
子 agent 返回最终回复
  |
  | 3. 父 agent 收到的只是一条 tool_result
  |    包含子 agent 的最终回复文本
  v
父 agent 继续（上下文依然干净）
```

关键点只有一个：

**子 agent 的全部中间过程不会回到父 agent 的 messages 里。父 agent 只收到最终结果。**

## 关键数据结构

### 1. delegate_task 工具的 schema

```python
{
    "name": "delegate_task",
    "description": "Delegate a task to a subagent with isolated context",
    "parameters": {
        "goal": "str — 子任务的目标描述",
        "context": "str — 给子 agent 的上下文信息（可选）",
        "toolsets": "list — 子 agent 可用的工具集（可选）",
    },
}
```

模型通过调用这个工具来发起委派。

### 2. 子 agent 被禁用的工具

```python
DELEGATE_BLOCKED_TOOLS = [
    "delegate_task",    # 不能递归委派
    "clarify",          # 不能向用户提问（子 agent 没有用户交互通道）
    "memory",           # 不能修改记忆（防止子任务副作用）
    "send_message",     # 不能发消息给用户
    "execute_code",     # 安全限制
]
```

为什么要限制？

- `delegate_task`：防止递归
- `clarify`：子 agent 没有用户交互通道，不能停下来问用户
- `memory`：子任务是一次性的，不应该产生持久副作用
- `send_message`：子 agent 不应该绕过父 agent 直接和用户说话

### 3. 子 agent 的默认工具集

```python
DEFAULT_TOOLSETS = ["terminal", "file", "web"]
```

只给最基本的能力：跑命令、读写文件、搜索。够用，但不会越权。

### 4. 批量委派

Hermes Agent 支持同时派出最多 3 个子 agent 并行执行：

```python
# 单任务
delegate_task(goal="搜索 Python 3.12 新特性")

# 批量任务（最多 3 个并行）
delegate_task(tasks=[
    {"goal": "搜索 Python 3.12 新特性"},
    {"goal": "检查当前测试覆盖率"},
    {"goal": "读取 CHANGELOG 最近 10 条"},
])
```

批量模式用 `ThreadPoolExecutor` 并行执行，结果按输入顺序返回。

## 最小实现

### 第一步：注册 delegate_task 工具

```python
from tools.registry import registry

def handle_delegate(args, **kwargs):
    goal = args["goal"]
    context = args.get("context", "")
    toolsets = args.get("toolsets", ["terminal", "file", "web"])
    
    # 构建子 agent
    child = build_child_agent(goal, context, toolsets, kwargs)
    
    # 执行
    result = child.run_conversation(goal)
    
    return result["final_response"]

registry.register(
    name="delegate_task",
    toolset="agent",
    schema={...},
    handler=handle_delegate,
)
```

### 第二步：构建子 agent

```python
def build_child_agent(goal, context, toolsets, parent_kwargs):
    # 子 agent 的 system prompt：只包含任务目标和上下文
    child_system_prompt = f"""你是一个专注于单一任务的助手。

任务目标：{goal}

上下文：{context}

完成任务后直接返回结果，不要问用户问题。"""
    
    # 复用父 agent 的 API 配置
    child = AIAgent(
        base_url=parent_kwargs["base_url"],
        api_key=parent_kwargs["api_key"],
        model=parent_kwargs.get("delegation_model", parent_kwargs["model"]),
        system_prompt=child_system_prompt,
        enabled_toolsets=toolsets,
        disabled_tools=DELEGATE_BLOCKED_TOOLS,
        max_iterations=30,  # 子 agent 给更少的预算
        iteration_budget=parent_kwargs["iteration_budget"],  # 共享父 budget
    )
    
    return child
```

### 第三步：处理 budget 扣减

```python
# 子 agent 执行完毕后
result = child.run_conversation(goal)

# 子 agent 消耗的 iteration 数已经从 shared budget 里扣掉了
# 父 agent 继续时，budget 自动是扣减后的值
```

这就是最小版本。子 agent 的 `messages` 在函数返回后就被丢弃了——这正是设计目的。

## Hermes Agent 在这里的独特设计

### 1. 委派模型可以不同

子 agent 可以用更便宜的模型：

```yaml
# config.yaml
delegation:
  model: anthropic/claude-haiku
  provider: openrouter
```

父 agent 用 Claude Sonnet 做主推理，子 agent 用 Haiku 做搜索和文件读取。这能显著降低成本。

### 2. 进度回传

子 agent 执行时，父 agent 可以实时看到它在做什么：

```text
├─ 🔀 [1] web_search "Python 3.12 features"
├─ 🔀 [1] read_file "requirements.txt"
├─ 🔀 [1] web_search "Python 3.12 type hints"
```

这通过 `tool_progress_callback` 实现：子 agent 每执行一个工具，回调一次父 agent 的进度显示。

**核心机制：** 主 agent 不是在循环里"拉取"子 agent 进度，而是子 agent 每执行一个工具时，通过创建时注入的回调函数"推送"进度到父 agent 的显示层。这是经典的观察者模式 / 事件回调模式，不需要轮询。

用一个最简化的例子理解整个流程：

```python
# ① 定义"收到进度后做什么"
def on_progress(event_type, tool_name, preview, args):
    print(f"子 agent 正在用: {tool_name} — {preview}")

# ② 创建子 agent 时，把这个函数"注入"进去
child = AIAgent(
    tool_progress_callback=on_progress,   # ← 注入回调
)

# ③ 子 agent 内部每次执行工具前，自动调用这个回调
#    （这段代码在 AIAgent._handle_tool_calls 里，不需要你写）
#    伪代码：
for tool in tools_to_run:
    self.tool_progress_callback("tool.started", tool.name, tool.preview, tool.args)
    result = self.execute(tool)          # 实际执行工具
    self.tool_progress_callback("tool.completed", tool.name, ...)
```

整个过程就三步：**定义回调 → 注入子 agent → 子 agent 执行时自动触发**。父 agent 不需要轮询，子 agent 也不需要知道进度展示给谁看——它只管调用回调，具体是打印到终端还是发到 Telegram，由回调函数的实现决定。

**但为什么回调函数能在父 agent 的界面上显示东西？** 答案是闭包（closure）。回调函数在创建时就"捕获"了父 agent 的显示对象，之后无论谁调用它，操作的都是同一个对象：

```python
# 父 agent 侧：创建回调
def make_callback(parent_spinner):
    """spinner 被闭包捕获——函数记住了创建时的环境"""
    
    def callback(tool_name):
        # 虽然这个函数将来在子 agent 里被调用，
        # 但 parent_spinner 是创建时就"抓住"的父 agent 的对象
        parent_spinner.print_above(f"├─ 🔍 {tool_name}")
    
    return callback
```

时间线：

```text
1. 父 agent 创建 spinner（显示在父的终端上）
   spinner = KawaiiSpinner("⏳ 子 agent 工作中...")

2. 父 agent 创建回调，把自己的 spinner 包进去
   cb = make_callback(spinner)    # ← spinner 被闭包捕获

3. 父 agent 把回调注入子 agent
   child = AIAgent(tool_progress_callback=cb)

4. 子 agent 执行工具时调用 cb("web_search")
   → cb 内部执行 spinner.print_above("├─ 🔍 web_search")
   → spinner 是父 agent 的！所以打印在父 agent 的终端上
```

子 agent 调用的是一个函数，但这个函数操作的是父 agent 的对象。父子 agent 在同一个进程里，共享内存，所以闭包捕获的 `spinner` 就是父 agent 正在显示的那个 spinner，不需要任何跨进程通信。

### 3. 心跳机制

心跳机制解决的问题很具体：**Gateway 有一个"不活动超时"（默认 30 分钟），如果父 agent 长时间没有活动记录，Gateway 会认为它卡死了，直接杀掉。**

父 agent 正常工作时，每次调 API、执行工具都会更新自己的活动时间戳（`_last_activity_ts`）。但当它派出子 agent 后，**父 agent 自己停下来等结果**，不再调任何工具——从 Gateway 的视角看，父 agent"没有活动"了。

等子 agent 干完活（可能要好几分钟），Gateway 可能已经把父 agent 杀掉了。

解决方法就是心跳——一个后台线程，每 30 秒替父 agent 说一声"我还活着"：

```python
# 本质就是一个循环，每 30 秒更新一次父 agent 的活动时间戳
def _heartbeat_loop():
    while not stop_event.wait(30):            # 每 30 秒醒一次
        parent_agent._touch_activity("子 agent 还在干活")
        #           ↑ 这行会更新 _last_activity_ts = time.time()
        #             Gateway 看到时间戳在更新，就不会杀父 agent

# 启动后台线程
heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
heartbeat_thread.start()

# 子 agent 开始干活
result = child.run_conversation(goal)

# 子 agent 干完了，停掉心跳
stop_event.set()
```

就这么多。心跳 = **一个每 30 秒执行 `_last_activity_ts = time.time()` 的后台线程**，目的是骗过 Gateway 的不活动检测，让它知道"父 agent 没卡死，只是在等子 agent"。

### 4. 凭据隔离

子 agent 可以使用不同的 API 凭据：

```python
_resolve_delegation_credentials()  # 检查 delegation 配置
# 如果 delegation 配置了独立的 provider/api_key，用它
# 否则降级到父 agent 的凭据
```

这在企业场景下有用：主 agent 用高级 API key，子 agent 用限额 key。

## 它如何接到主循环里

委派逻辑**不在核心循环里**，而是作为一个普通工具注册在工具系统里。

```text
核心循环
  |
  | 模型决定调用 delegate_task
  v
dispatch("delegate_task", args)
  |
  v
delegate_task handler
  |
  | 创建子 AIAgent
  | 调用 child.run_conversation()
  | 子 agent 内部跑自己的循环
  | 返回最终结果
  v
tool_result 写回父 agent 的 messages
  |
  v
核心循环继续
```

从循环的角度看，`delegate_task` 和 `web_search` 没有区别——都是一个工具调用，只是执行时间更长、内部更复杂。

## 初学者最容易犯的错

### 1. 让子 agent 也能委派

递归委派 = 失控。Hermes Agent 限制深度为 2（MAX_DEPTH = 2），子 agent 不能再派子 agent。

### 2. 把子 agent 的完整 messages 带回父 agent

子 agent 的中间过程不应该回到父 agent。只带回最终回复文本就够了。否则就失去了上下文隔离的意义。

### 3. 给子 agent 单独的 budget

子 agent 应该共享父 agent 的 budget。如果每个子 agent 单独给 90 次，3 个并行就是 270 次，成本和时间都失控。

### 4. 让子 agent 修改记忆

子 agent 是一次性的。如果它能修改 MEMORY.md，两个并行子 agent 可能同时写同一个文件——产生冲突。记忆修改应该只由父 agent 做。

### 5. 不做进度回传

用户等了 30 秒，界面上什么反馈都没有，以为系统挂了。即使子 agent 在忙，也要让用户看到正在发生什么。

## 教学边界

这一章讲透三件事：

1. **上下文隔离** — 子 agent 有独立 messages，中间过程不回到父 agent
2. **工具限制** — 子 agent 不能委派、不能改记忆、不能问用户
3. **budget 共享** — 子 agent 消耗父 agent 的预算，不是另开一份

先不管的：

- 批量委派的线程池细节 → 生产优化
- 心跳机制的具体实现 → Gateway 章节（`s12`）
- 凭据路由的完整逻辑 → 配置章节（`s11`）

如果读者能做到"父 agent 调用 delegate_task，子 agent 在独立上下文里完成任务，最终只有结果文本回到父 agent"，这一章就达标了。

## 学完这章后，你应该能回答

- 为什么需要子 agent，而不是让父 agent 直接做所有事？
- 子 agent 的 messages 和父 agent 的 messages 是什么关系？
- 为什么子 agent 不能使用 delegate_task 和 memory 工具？
- iteration budget 共享是什么意思？
- 委派机制在系统架构的哪一层？它改了核心循环吗？

---

**一句话记住：Hermes Agent 的子 agent 就是一个拥有独立 messages 的临时 AIAgent 实例，它共享父 agent 的 API 配置和 iteration budget，完成任务后只返回结果文本，全部中间过程不会污染父 agent 的上下文。**
