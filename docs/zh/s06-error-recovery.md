# s06: Error Recovery (错误恢复)

`s00 > s01 > s02 > s03 > s04 > s05 > [ s06 ] > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *错误不是例外，而是主循环必须预留出来的一条正常分支。*

## 这一章要解决什么问题

到了 `s05`，agent 已经有了完整的工具系统、持久化、提示词组装和上下文压缩。

这时候系统已经不再是一个 demo，而是一个真的在做事的程序。问题也随之出现：

- 模型输出写到一半被截断（`finish_reason: length`）
- 上下文太长，API 直接返回 400
- 网络超时、限流、服务抖动
- API key 过期或额度用完
- 模型不存在或被下线

如果没有恢复机制，主循环会在第一个错误上直接崩溃。

但很多失败并不是"任务真的失败了"，而只是：

**这一轮需要换一种继续方式。**

Hermes Agent 的做法不是简单的 try/except + retry。它先对错误做分类，再根据分类选择恢复策略。而且因为它支持 200+ 模型和多个提供商，错误种类比单提供商 agent 多得多。

![错误分类与恢复策略](../../illustrations/s06-error-recovery/01-flowchart-error-classification.png)

## 先解释几个名词

### 什么叫错误分类

不同的错误需要不同的处理。

限流（429）应该退避重试。上下文太长（400）应该压缩。认证失败（401）应该换凭证。模型不存在（404）应该切备用模型。

如果不先分类，所有错误都走同一条路，该重试的去压缩了，该放弃的在死循环。

### 什么叫故障转移

当当前的模型或提供商出了不可恢复的问题时，自动切换到备用模型。

比如：主模型限流了，自动切到备用模型继续工作。用户不需要手动干预。

### 什么叫退避重试

出错后不立刻重试，而是等一段时间。

等多久？指数递增 + 随机抖动。第一次等 5 秒，第二次等 10 秒，第三次等 20 秒... 再加一个随机偏移，避免多个 Gateway 会话同时重试撞在一起。

### 什么叫续写

模型输出被截断（`finish_reason: length`），不是模型不会了，是这一轮输出空间不够了。

续写就是追加一条消息告诉模型"接着刚才的继续，不要重新开始"，然后再调一次 API。

## 最小心智模型

教学版只需要先区分 4 类问题：

```text
1. 输出被截断（finish_reason: length）
   → 注入续写提示，再试

2. 上下文太长（400 / context overflow）
   → 触发压缩（s05），再试

3. 临时故障（429 限流 / 503 过载 / 超时）
   → 退避等待，再试

4. 不可恢复（401 认证失败 / 404 模型不存在 / 额度用完）
   → 尝试故障转移到备用模型，或者放弃
```

```text
API call
  |
  +-- 成功，finish_reason: stop
  |      → 正常结束
  |
  +-- 成功，finish_reason: tool_calls
  |      → 执行工具，继续循环
  |
  +-- 成功，finish_reason: length
  |      → 续写（最多 3 次）
  |
  +-- 失败，可恢复
  |      → 分类 → 退避 / 压缩 / 换凭证
  |
  +-- 失败，不可恢复
         → 故障转移 / 放弃
```

## 关键数据结构

### 1. 错误分类结果

```python
classified = {
    "reason": "rate_limit",        # 为什么失败
    "retryable": True,             # 能不能重试
    "should_compress": False,      # 要不要触发压缩
    "should_fallback": False,      # 要不要切备用模型
}
```

把"错误长什么样"和"接下来怎么做"分开。循环不需要理解错误的具体内容，只看分类结果里的几个布尔标记就知道该走哪条路。

### 2. 故障转移原因

Hermes Agent 定义了十几种故障原因，但教学版先记这几种：

```text
rate_limit     → 退避重试
overloaded     → 退避重试
timeout        → 重建连接 + 重试
context_overflow → 触发压缩
billing        → 换凭证或切备用模型
auth           → 换凭证或切备用模型
model_not_found → 切备用模型
```

每种原因对应不同的恢复动作。这就是分类的价值。

### 3. 续写提示

```python
CONTINUE_MESSAGE = (
    "Your response was cut off. Continue EXACTLY from where you stopped. "
    "Do not restart, do not repeat, do not summarize what came before."
)
```

这条提示非常重要。如果你只说"继续"，模型经常会重新总结或重新开头。

## 最小实现

### 第一步：写一个错误分类器

```python
def classify_error(status_code, error_message):
    if status_code == 429:
        return {"reason": "rate_limit", "retryable": True, "should_compress": False, "should_fallback": False}
    
    if status_code == 400 and "context" in error_message.lower():
        return {"reason": "context_overflow", "retryable": True, "should_compress": True, "should_fallback": False}
    
    if status_code in (500, 502, 503):
        return {"reason": "server_error", "retryable": True, "should_compress": False, "should_fallback": False}
    
    if status_code in (401, 403):
        return {"reason": "auth", "retryable": False, "should_compress": False, "should_fallback": True}
    
    if status_code == 404:
        return {"reason": "model_not_found", "retryable": False, "should_compress": False, "should_fallback": True}
    
    return {"reason": "unknown", "retryable": False, "should_compress": False, "should_fallback": False}
```

这一步的关键思想是：

> 分类器把"HTTP 状态码 + 错误消息"翻译成"该重试 / 该压缩 / 该转移 / 该放弃"。循环只看翻译结果。

### 第二步：写退避重试

```python
def jittered_backoff(attempt, base_delay=5.0, max_delay=120.0):
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = random.uniform(0, delay * 0.5)
    return delay + jitter
```

这一步的关键思想是：

> 指数递增 + 随机抖动。递增是为了给服务器喘息时间，抖动是为了避免多个 Gateway 会话同时重试。

### 第三步：接进主循环

```python
retry_count = 0
continuation_count = 0

while iteration < max_iterations:
    try:
        response = client.chat.completions.create(...)
    except Exception as e:
        classified = classify_error(getattr(e, "status_code", None), str(e))
        
        if classified["should_compress"]:
            messages = compress(messages)
            continue
        
        if classified["should_fallback"] and fallback_model:
            switch_to_fallback_model()
            continue
        
        if classified["retryable"] and retry_count < 3:
            retry_count += 1
            time.sleep(jittered_backoff(retry_count))
            continue
        
        raise  # 不可恢复，向上抛
    
    # 拿到响应后
    finish_reason = response.choices[0].finish_reason
    
    if finish_reason == "length" and continuation_count < 3:
        continuation_count += 1
        messages.append({"role": "user", "content": CONTINUE_MESSAGE})
        continue
    
    # 正常处理 tool_calls 或结束
    ...
```

注意这里的关键：**分类和恢复是两步**。先分类，再根据分类走对应的恢复路径。每条路径有自己的重试预算。

### 第四步：故障转移

```python
def switch_to_fallback_model():
    # 切到配置里的备用模型
    self.model = fallback_model["model"]
    self.base_url = fallback_model["base_url"]
    self.api_key = fallback_model["api_key"]
    # 重建 API 客户端
    self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
```

这一步的关键思想是：

> 既然 Hermes Agent 通过 `base_url` 支持任意提供商，那故障转移就只是"换一组配置"。不需要改代码，不需要改消息格式。

## Hermes Agent 在这里的独特设计

### 1. 多提供商意味着更多错误种类

单提供商 agent 只需要处理一个 API 的错误格式。Hermes Agent 支持 OpenRouter、Anthropic、本地端点等多种提供商，每种的错误格式和状态码含义不完全一样。

分类器要从不同提供商的错误消息中提取出统一的故障原因。比如"额度用完"在不同提供商的错误消息里措辞不同，但分类结果都是 `billing`。

### 2. 连接健康检查

`run_conversation()` 开始前，先检查 API 客户端的连接是否健康。如果检测到上一轮留下的死连接（比如上次超时后 TCP 连接还挂着），主动清理掉。

不等到新 API 调用挂在僵尸连接上才发现。

### 3. 主模型恢复

故障转移到备用模型后，下一轮 `run_conversation()` 开始时，先尝试切回主模型。

这样故障转移是临时的。如果主模型恢复了，下一轮自动回去，不需要用户手动切。

### 4. thinking-budget 检测

有些模型（支持 reasoning/thinking 的）可能把所有输出 token 都花在思考上，留给回复的 token 为零。这时候 `finish_reason: length` 但续写没有意义。

Hermes Agent 检测这种情况并直接报错，而不是浪费 3 次续写重试。

## 初学者最容易犯的错

### 1. 把所有错误都当成一种错误

该续写的去压缩了，该等待的在死循环，该放弃的在无限重试。

### 2. 没有重试预算

每条恢复路径都要有上限。续写最多 3 次，退避最多 3 次。没有预算，循环可能永远不结束。

### 3. 续写提示写得太模糊

只写一个"continue"通常不够。你要明确告诉模型不要重复、不要重新总结、直接从中断点接着写。

### 4. 退避不加随机抖动

确定性的退避时间（比如每次都等 10 秒）在 Gateway 多会话场景下会导致所有重试撞在一起（thundering herd）。随机抖动打散它们。

### 5. 故障转移后不尝试恢复主模型

如果切到备用模型就再也不回来，用户会一直用着可能更弱或更贵的备用模型。

## 这一章如何接到主循环里

从这一章开始，主循环不再是简单的"调模型 → 执行工具"。它变成了：

```text
1. 调模型
2. 如果调用失败 → 分类错误 → 选择恢复路径
3. 如果输出被截断 → 续写
4. 如果成功 → 正常执行工具
5. 任何恢复路径失败 → 向上报告
```

也就是说，主循环现在同时维护三件事：

```text
任务推进（调模型、跑工具）
上下文预算（s05 的压缩）
错误恢复（分类、重试、转移）
```

这是阶段 1 的最后一章。到这里为止，你已经有了一个**能工作、能持久化、能组装提示词、能压缩上下文、能从错误中恢复**的单 agent。

阶段 2 开始补智能层：记忆、技能、安全、委派、配置。

## 教学边界

这一章先讲清 4 条恢复路径就够了：

1. 输出截断 → 续写
2. 上下文太长 → 压缩
3. 临时故障 → 退避重试
4. 不可恢复 → 故障转移或放弃

刻意停住的：具体每种提供商的错误格式差异、凭证池轮换、连接健康检查的实现细节。

如果读者能做到"agent 遇到限流不崩溃，遇到截断能续写，主模型挂了能自动切备用"，这一章就达标了。

## 一句话记住

**错误先分类，恢复再执行，失败最后才暴露给用户。Hermes Agent 因为支持多提供商，分类器要从不同格式的错误消息中提取统一的故障原因。**
