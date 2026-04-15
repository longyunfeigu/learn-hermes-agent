# s01: The Agent Loop (智能体循环)

`s00 > [ s01 ] > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *没有循环，就没有 agent。*  
> 这一章教你做出一个最小的对话循环，同时理解 Hermes Agent 的循环为什么选择了"同步主体 + 异步桥接"这条路。

## 这一章要解决什么问题

语言模型本身只会"生成下一段内容"。它不会自己去执行命令、观察结果、再基于结果继续推理。

如果没有一层代码在中间反复做这件事，模型就只是一个"会说话的程序"，还不是一个"会干活的 agent"。

但 Hermes Agent 的循环不只是"一个 while True"。它从一开始就面对几个和简单教学 agent 不一样的现实问题：

1. **同一个循环要服务两种入口** — CLI 是用户在终端直接调用，Gateway 是多个平台的消息同时到达。所以循环本身不能依赖终端 I/O。
2. **Gateway 每条消息创建一个新的 agent 实例** — 不是一个全局 agent 一直活着，而是每次消息来了创建一个，传入历史消息，跑完就结束。
3. **工具可能是异步的** — 大部分工具（文件读写、终端命令）是同步的，但网络请求、浏览器操作等是异步的。循环本身选择同步，通过桥接处理异步工具。

这一章先只讲最小版本。上面这些复杂性会在后续章节逐步展开。

## 先解释几个名词

### run_conversation

Hermes Agent 对话循环的入口方法。

它接收一条用户消息和可选的历史消息列表，运行循环直到模型不再调用工具，返回最终回复和完整的消息历史。

关键点：它是一个普通的 `def`，不是 `async def`。这是一个刻意的设计选择。

### iteration 和 iteration budget

一次 API 调用算一个 iteration。Hermes Agent 默认最多 90 个 iteration。

**budget（预算）** 可以理解成"配额"或"信用额度"——这次对话总共允许调用多少次 API 的上限。为什么叫 "budget" 而不是 "max_iterations"？因为它是一个**可以被消耗、被分享的资源**，不只是一个静态计数器。

简单例子：

```text
budget = 90

用户："帮我重构这个文件"
  iter 1: 模型说"我先读文件" → 调用 read_file        (剩 89)
  iter 2: 模型说"再看看测试" → 调用 read_file        (剩 88)
  iter 3: 模型说"我来改"     → 调用 edit_file        (剩 87)
  iter 4: 模型说"完成了"     → stop                  (剩 86)
```

Gateway 场景下"共享 budget"的意思：

```text
父 agent budget = 90
  iter 1-10: 父 agent 自己干活                        (剩 80)
  iter 11:   父 agent 派一个子 agent 去搜索
             └─ 子 agent 用了 15 iter                 (剩 65)
  iter 12+:  父 agent 继续，从 65 开始
```

子 agent 不是"另外给 90"，而是从父 agent 的钱包里扣。所以叫 budget。

### finish_reason

模型返回的"我为什么停下来"。

- `stop`：说完了
- `tool_calls`：想调用工具
- `length`：输出被截断了

循环根据它决定下一步怎么走。

### messages 和 api_messages

Hermes Agent 内部维护了两份消息：

- `messages`：你内部保存的"完整账本"，什么都有，包含内部状态（如 reasoning 字段）
- `api_messages`：每次 API 调用前从 `messages` 临时清洗出来的副本，只留模型看得懂的字段

简单例子：

```python
# messages（内部完整版）
messages = [
    {"role": "user", "content": "今天天气怎么样"},
    {
        "role": "assistant",
        "content": "我查一下",
        "reasoning": "用户问天气,我应该调用工具",  # ← 内部字段
        "_internal_token_count": 42,                # ← 内部字段
    },
]

# 调 API 前,清洗一下 →
api_messages = [
    {"role": "system", "content": "你是 Hermes..."},   # ← 拼在最前面
    {"role": "user", "content": "今天天气怎么样"},
    {
        "role": "assistant",
        "content": "我查一下",
        # reasoning 和 _internal_token_count 被去掉了
    },
]

client.chat.completions.create(messages=api_messages, ...)
```

为什么要分两份？

- `messages` 要持久化、要给你调试看，信息越全越好
- `api_messages` 要发给 OpenAI 兼容 API，多余字段会报错或浪费 token

一句话：**messages 是底稿，api_messages 是每次寄出去的信件**。

这个区分在教学第一版里可以先忽略，但你要知道它存在。

## 最小心智模型

```text
user message
   |
   v
组装 system prompt（人设 + 记忆 + 项目配置 + 工具定义）
   |
   v
 model API（OpenAI 兼容格式）
   |
   +-- finish_reason: stop -----> 返回最终回复
   |
   +-- finish_reason: tool_calls --> 执行工具
                                       |
                                       v
                                  tool result
                                       |
                                       v
                                  写回 messages
                                       |
                                       v
                                  下一轮继续
```

真正关键的不是"有一个循环"。

真正关键的是两件事：

1. **工具结果必须写回消息历史** — 否则模型下一轮看不到执行结果。
2. **system prompt 在每次 API 调用时重新拼装到消息前面** — 它不是 messages 的一部分，而是每次调用时单独传入的。

## 关键数据结构

### Message

OpenAI 格式的消息。三种角色：

```python
# 用户消息
{"role": "user", "content": "帮我搜索 Python 3.12 的新特性"}

# 助手消息（带工具调用）
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_abc",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "Python 3.12 new features"}',
            },
        }
    ],
}

# 工具结果
{
    "role": "tool",
    "tool_call_id": "call_abc",
    "content": "Python 3.12 新增了...",
}
```

注意 `tool_call_id` — 它把结果和调用对应起来。模型一轮可能同时调多个工具，每个结果都要对上号。

### System Prompt

不在 messages 里。每次 API 调用时作为第一条 system 角色消息拼在最前面：

```python
api_messages = [{"role": "system", "content": system_prompt}] + messages
```

Hermes Agent 的 system prompt 由多个来源组装：人设文件（SOUL.md）、记忆（MEMORY.md）、项目配置（HERMES.md）、工具定义、技能清单。这些在 `s04` 详细展开。

## 最小实现

### 第一步：创建客户端

```python
from openai import OpenAI

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key="...")
```

所有模型提供商都通过这一个客户端接入。换模型只需要换 `base_url` 和 `api_key`。

### 第二步：构建循环

```python
def run_conversation(user_message, system_prompt, tools, max_iterations=90):
    messages = [{"role": "user", "content": user_message}]
    
    for i in range(max_iterations):
        # 拼装 API 消息：system prompt + 对话历史
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        
        # 调用模型
        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4",
            messages=api_messages,
            tools=tools,
        )
        
        assistant_msg = response.choices[0].message
        
        # 把 assistant 回复写回历史（不管有没有 tool_calls）
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (assistant_msg.tool_calls or [])
            ] or None,
        })
        
        # 没有 tool_calls → 结束
        if not assistant_msg.tool_calls:
            return {"final_response": assistant_msg.content, "messages": messages}
        
        # 执行每个工具，结果写回
        for tool_call in assistant_msg.tool_calls:
            output = run_tool(tool_call.function.name, tool_call.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })
    
    return {"final_response": "达到最大迭代次数", "messages": messages}
```

这就是最小的 Hermes Agent 循环。

### 它和真实代码的关系

真实的 `AIAgent.run_conversation()` 比这复杂得多，但核心骨架完全一样：

1. 拼装 messages
2. 调 API
3. 写回 assistant 消息
4. 有 tool_calls 就执行，结果写回
5. 继续

真实代码在这个骨架上加了：preflight 压缩检查、plugin 钩子、memory 注入、reasoning 字段处理、interrupt 支持、流式输出、错误重试。这些都在后续章节展开。

## Hermes Agent 循环的三个独特设计

### 1. Gateway 的实例管理：缓存复用，而非每次新建

在 CLI 模式下，一个 AIAgent 实例从头跑到尾。

Gateway 模式下的**教学简化说法**是"每条消息创建新实例"。实际实现更聪明——Gateway 维护了一个实例缓存：

```python
# gateway/run.py
self._agent_cache: Dict[str, tuple] = {}  # session_key → (AIAgent, 配置签名)
```

流程如下：

```text
消息到达 → 计算配置签名（model + api_key + provider + toolsets）
         → 查缓存
           ├─ 命中 → 复用已有实例（system prompt、工具定义都不变）
           └─ 未命中 → 创建新实例，存入缓存
         → 更新轻量的每条消息字段（callbacks、reasoning_config）
         → 调用 run_conversation()
```

只有用户执行 `/new`（重置会话）、`/model`（换模型）或触发 fallback 时才会淘汰缓存。

复用实例最重要的原因是 **prompt caching**——Anthropic API 要求 system prompt 在多轮间保持不变才能命中缓存，复用实例 = 省钱省时间。

但核心原则不变：**不要把跨消息状态存在实例变量里**。对话历史每次从 SQLite 传入，不存在实例内存里。Agent 实例可以被随时淘汰重建，代码不能依赖它"一直活着"。

### 2. system prompt 缓存

第一次调用时，system prompt 从多个来源组装并缓存。后续调用复用缓存，不重新组装。

这不只是性能优化。Anthropic 的 prompt caching 机制要求 system prompt 在多轮调用间保持不变。如果每轮都重新组装（比如记忆文件被修改了），缓存就失效了。

所以 Hermes Agent 在 continuing session 时，会从 SQLite 里读回之前存的 system prompt，而不是重新组装。

### 3. 同步循环 + 异步桥接

循环本身是同步的 `def`。但有些工具（网络请求、浏览器操作）需要 async。

**核心问题**：Agent 循环里大部分工具是同步的（读文件、写文件、跑命令），但少数工具是异步的（HTTP 请求、浏览器自动化）。怎么在一个循环里同时支持两种？

有两种方案：

**方案 A：整个循环都用 `async def`**

```python
async def run_conversation(...):
    ...
    result = await run_tool(...)  # 所有工具都 await
```

看起来统一，但代价是：所有同步工具也要包一层 async，错误堆栈变复杂，调试变难。

**方案 B（Hermes 的选择）：循环是同步的，遇到 async 工具时桥接过去**

```python
def run_conversation(...):          # 普通 def，不是 async
    ...
    if tool_is_async:
        result = event_loop.run(async_tool(...))  # 桥接到事件循环
    else:
        result = sync_tool(...)     # 直接调用
```

**什么是"持久化的事件循环"？**

`asyncio.run()` 每次调用都会创建一个新的事件循环，用完就销毁。Hermes Agent 不用这种方式，而是在启动时创建一个事件循环，一直留着复用：

```python
# 启动时创建一次
loop = asyncio.new_event_loop()

# 每次需要跑 async 工具时复用它
def bridge_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
```

为什么要持久化？因为有些异步资源（比如浏览器 session、WebSocket 连接）是跨多次工具调用存活的。如果每次都新建事件循环，这些连接就断了。

**一句话总结**：主循环保持同步以求简单，只在遇到 async 工具时把任务扔给一个常驻的事件循环去执行，执行完把结果拿回来继续同步流程。

## 初学者最容易犯的错

### 1. 不写回 assistant 消息

工具结果写回了，但 assistant 消息没写回。下一轮 API 调用时，模型看不到自己上一轮说了什么。

### 2. 不绑定 tool_call_id

模型一轮调了两个工具，但两个结果都没带 id。模型分不清哪条结果对应哪个调用。

### 3. system prompt 放在 messages 列表里

system prompt 应该每次 API 调用时单独拼在前面，不应该作为 messages 列表的一部分存下来。否则它会被持久化、被压缩、被重复。

### 4. 不设迭代上限

没有 `max_iterations` 的循环会在模型反复调用工具时永远不停。Hermes Agent 默认 90 次。

### 5. 以为 agent 实例是长生命周期的

在 Gateway 模式下，每条消息都是一个新实例。不要在实例变量里存跨消息的状态。

## 教学边界

这一章只需要先讲透一件事：

**messages → model → tool_calls → tool_result → next turn**

这条回路是后面所有机制的基础。

刻意停住的东西：

- 工具怎么注册和分发 → `s02`
- 对话怎么持久化 → `s03`
- system prompt 怎么组装 → `s04`
- 上下文太长了怎么办 → `s05`
- API 出错了怎么办 → `s06`

如果读者能凭记忆写出上面那个最小循环，这一章就已经达标了。

## 一句话记住

**Hermes Agent 的循环是同步的，用 OpenAI 兼容接口调任意模型，Gateway 和 CLI 共享同一个循环，工具结果必须写回 messages 才能让模型继续工作。**
