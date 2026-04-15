# s04: Prompt Builder (提示词组装)

`s00 > s01 > s02 > s03 > [ s04 ] > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *system prompt 不是一段硬编码字符串，而是从六七个来源按顺序组装出来的。*

## 这一章要解决什么问题

到了 `s03`，agent 已经有了工具系统和会话持久化。

但有一个问题一直被推迟了：**system prompt 从哪来？**

s01 的最小循环里，system prompt 是一个写死的字符串。但真实系统里，agent 需要知道：

- 自己是谁（人设）
- 用户有什么偏好（记忆）
- 当前项目有什么规则（项目配置）
- 有哪些技能可以用（技能清单）
- 现在几点了（时间戳）
- 应该怎么用工具（行为指导）

这些信息来自不同的文件和运行时状态。如果硬编码在一起，每改一处就要改代码。

所以 Hermes Agent 把 system prompt 拆成了**分层组装**：每个来源独立维护，启动时按顺序拼在一起。

## 先解释几个名词

### 什么是 SOUL.md

人设文件。存在 `~/.hermes/` 目录下。定义 agent 的身份和行为风格。

比如：

```text
你是一个简洁、直接的编程助手。
回答尽量简短。
不要在每次回复结尾加总结。
```

### 什么是 HERMES.md / AGENTS.md

项目级配置文件。放在项目目录里，告诉 agent 这个项目的规则。

比如：

```text
这是一个 Python 项目。
测试框架用 pytest。
代码风格遵循 PEP 8。
不要修改 migrations/ 目录。
```

### 什么是 prompt 缓存

system prompt 组装一次后缓存下来。同一个 session 的所有 API 调用复用同一份。

为什么要缓存？两个原因：

1. 不用每次都重新读文件和拼字符串
2. Anthropic 的 prompt caching 要求 system prompt 在多轮间保持不变。变了，缓存就失效，要多花钱

## 最小心智模型

```text
_build_system_prompt()
  |
  v
Layer 1: 人设（SOUL.md，或默认身份）
  |
  v
Layer 2: 行为指导（工具使用规范、模型特定指导）
  |
  v
Layer 3: 记忆（MEMORY.md + USER.md 快照）
  |
  v
Layer 4: 技能清单（已安装技能的索引）
  |
  v
Layer 5: 项目配置（HERMES.md / AGENTS.md / CLAUDE.md / .cursorrules）
  |
  v
Layer 6: 时间戳 + 模型信息
  |
  v
拼成一条完整字符串，缓存
```

关键点：**这些 layer 有优先级。** 如果同时存在 HERMES.md 和 AGENTS.md，只用 HERMES.md（优先级更高）。这避免了重复注入。

## 关键数据结构

### prompt_parts

在组装过程中，各来源的内容先收集到一个列表里：

```python
prompt_parts = [
    "你是一个编程助手...",          # Layer 1: 人设
    "当你需要执行操作时...",         # Layer 2: 行为指导
    "# Memory\n用户偏好...",        # Layer 3: 记忆
    "# Skills\n可用技能...",        # Layer 4: 技能
    "# Project Context\n项目规则...", # Layer 5: 项目配置
    "Conversation started: ...",     # Layer 6: 时间戳
]
```

最后用 `"\n\n".join(prompt_parts)` 拼成一条字符串。

### 项目配置优先级

```text
.hermes.md / HERMES.md   (最高，从当前目录往上找到 git root)
AGENTS.md / agents.md     (仅当前目录)
CLAUDE.md / claude.md     (仅当前目录)
.cursorrules              (仅当前目录)
```

**只用第一个找到的。** 不会全部加载。

这个设计的目的是兼容：从其他 agent 框架迁移过来的项目可能已经有 CLAUDE.md 或 .cursorrules，Hermes Agent 直接用它们，不需要用户重写。

### 每个来源的截断

每个文件最多 20,000 字符。超出截断。

这防止一个巨大的 AGENTS.md 把整个上下文窗口占满。

## 最小实现

### 第一步：读人设

```python
def load_soul():
    soul_path = HERMES_HOME / "SOUL.md"
    if soul_path.exists():
        return soul_path.read_text()[:20000]
    return "You are a helpful assistant."
```

### 第二步：读项目配置（优先级链）

```python
def load_project_context(cwd):
    for name in [".hermes.md", "HERMES.md"]:
        # 从 cwd 往上找到 git root
        path = find_up(cwd, name)
        if path:
            return path.read_text()[:20000]
    
    for name in ["AGENTS.md", "CLAUDE.md", ".cursorrules"]:
        path = Path(cwd) / name
        if path.exists():
            return path.read_text()[:20000]
    
    return ""
```

### 第三步：组装

```python
def build_system_prompt(soul, memory, skills, project_context):
    parts = [soul]
    
    if memory:
        parts.append(f"# Memory\n{memory}")
    if skills:
        parts.append(f"# Skills\n{skills}")
    if project_context:
        parts.append(f"# Project Context\n{project_context}")
    
    parts.append(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    return "\n\n".join(parts)
```

### 第四步：缓存

```python
class AIAgent:
    def __init__(self):
        self._cached_system_prompt = None
    
    def run_conversation(self, user_message, ...):
        if self._cached_system_prompt is None:
            self._cached_system_prompt = build_system_prompt(...)
        
        # 每次 API 调用都用同一份
        api_messages = [
            {"role": "system", "content": self._cached_system_prompt}
        ] + messages
```

组装一次，后面不再重建。只有上下文压缩事件才会清除缓存并重建。

## Hermes Agent 在这里的独特设计

### 1. Gateway 续接 session 时从 SQLite 读 prompt

Gateway 每条消息创建新的 AIAgent 实例。如果每次都重新组装 system prompt：

- MEMORY.md 可能已经被上一轮的 agent 改了
- 新组装出来的 prompt 和上一轮不一样
- Anthropic 的 prompt cache prefix 失效

所以 Hermes Agent 在第一次组装后把 system prompt 存到 SQLite（见 `s03`）。后续实例直接读缓存，不重新组装。

### 2. ephemeral_system_prompt 不进缓存

有些系统级指令只在 API 调用时临时加入（比如 Gateway 的 ephemeral 配置），不存到 SQLite，不进缓存。

它在每次 API 调用时拼在 cached prompt 后面：

```python
effective_system = cached_prompt + "\n\n" + ephemeral_prompt
```

### 3. 记忆注入分两条路

- 内置记忆（MEMORY.md / USER.md）→ 进 system prompt
- 外部记忆提供者（plugin）→ 注入到 user message，不进 system prompt

为什么外部记忆不进 system prompt？因为外部记忆的内容每轮可能不同（取决于用户的问题），放进 system prompt 会破坏缓存。

## 初学者最容易犯的错

### 1. 把所有来源拼成一个巨大的硬编码字符串

改一处就要改代码。应该让每个来源独立维护、按顺序拼装。

### 2. 每轮 API 调用都重新组装

浪费时间，还会破坏 prompt cache。应该组装一次，缓存复用。

### 3. 不截断文件内容

一个 50KB 的 AGENTS.md 会吃掉大量上下文窗口，留给对话的空间变小。

### 4. 加载全部项目配置文件而不是只用优先级最高的

同时加载 HERMES.md 和 AGENTS.md 和 .cursorrules，内容可能冲突或重复。

### 5. 把 system prompt 放在 messages 列表里

system prompt 应该在每次 API 调用时临时拼在前面，不应该作为 messages 的一部分存到 SQLite。否则它会被压缩、被重复、被持久化成历史消息。

## 教学边界

这一章讲的是：

**system prompt 从多个来源分层组装，组装一次缓存复用。**

刻意停住的东西：

- 记忆系统的完整设计 → `s07`
- 技能清单的构建逻辑 → `s08`
- Gateway 续接 session 的完整流程 → `s12`
- 上下文压缩触发后的 prompt 重建 → `s05`

如果读者能做到"system prompt 由多个文件组装而成，改人设只需要改 SOUL.md，改项目规则只需要改 HERMES.md"，这一章就达标了。

## 一句话记住

**Hermes Agent 的 system prompt 是从 SOUL.md、记忆、技能、项目配置等六七个来源按优先级组装的，组装一次缓存复用，Gateway 续接 session 时从 SQLite 读而不是重新组装。**
