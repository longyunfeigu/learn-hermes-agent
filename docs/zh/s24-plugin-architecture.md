# s24: Plugin Architecture (插件架构)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > [ s24 ]`

> *内置记忆用文件存，但有人想用 Honcho 做用户建模，有人想用 mem0 做语义搜索。插件系统让他们各用各的，不改一行核心代码。*

![插件架构与可插拔接口](../../illustrations/s24-plugin-architecture/01-framework-plugin-interface.png)

## 这一章要解决什么问题

s07 讲的内置记忆系统用 MEMORY.md 和 USER.md 文件存储。够用，但有局限：

- 只有全文匹配，没有语义搜索（"我上周提到过一个 bug"找不到）
- 没有用户建模（不知道"这个人偏好什么风格""这个人之前做过哪些项目"）
- 数据存在本地文件里，不能跨设备同步

社区有很多专门做记忆的服务——Honcho（用户画像+对话式记忆）、mem0（语义搜索+事实提取）、holographic（本地知识图谱）。每个都有自己的 API 和数据模型。

如果你把 Honcho 的代码硬编码进 `memory_manager.py`，那想换 mem0 的人就得改核心代码。每个记忆服务都改一次核心代码，系统很快失控。

**需要一个插件接口：定义"记忆提供者必须做什么"，让每个服务自己实现，按配置切换。**

这个问题不只出现在记忆上。上下文压缩策略（s05）也有类似需求——内置的摘要压缩够用，但有人想用更智能的策略。所以 Hermes Agent 有三套独立的插件系统。

## 建议联读

- [`s07-memory-system.md`](./s07-memory-system.md) — 内置记忆系统（MEMORY.md / USER.md）
- [`s05-context-compression.md`](./s05-context-compression.md) — 内置上下文压缩
- [`s16-mcp.md`](./s16-mcp.md) — MCP 是另一种扩展能力的方式，但针对的是工具而不是记忆

## 先解释几个名词

### 什么是 MemoryProvider

外部记忆服务的统一接口。每个提供者（Honcho、mem0 等）实现这个接口，就可以插入 Hermes Agent。

核心约束：**同一时间只能有一个外部 MemoryProvider 激活。** 内置记忆（MEMORY.md）始终在线，外部提供者是可选的增强。

### 什么是 ContextEngine

上下文压缩策略的统一接口。内置的 ContextCompressor（s05 讲的摘要压缩）是默认实现。你可以替换成其他策略，同样同一时间只有一个。

### 什么是 MemoryManager

协调器。管理内置记忆和外部提供者的共存——谁提供工具、谁做 prefetch、谁做 sync。

## 从最笨的实现开始

把 Honcho 直接写进记忆管理代码：

```python
# memory_manager.py
def prefetch(query):
    # 内置记忆
    memory_text = load_memory(MEMORY_FILE)

    # Honcho
    if HONCHO_ENABLED:
        from honcho import HonchoClient
        client = HonchoClient(api_key=HONCHO_KEY)
        honcho_context = client.recall(query)
        return memory_text + "\n" + honcho_context

    return memory_text
```

两个问题：

### 问题一：每加一个服务都改核心代码

加了 Honcho，又要加 mem0。再加 holographic。每个的初始化、prefetch、sync、工具注册全不一样，全写在 memory_manager.py 里。和 s12 的 if-else 平台适配器是同一个问题。

### 问题二：两个外部服务同时激活会冲突

Honcho 和 mem0 都想在每轮对话前 prefetch 上下文，都想注册自己的工具。同时激活可能互相干扰。但你不能简单禁止——有些场景确实需要切换。

**解法：定义 MemoryProvider 接口 + 一个规则（同时只有一个外部提供者）。**

## 最小心智模型

```text
内置记忆（始终在线）          外部提供者（可选，最多一个）
 MEMORY.md / USER.md            Honcho / mem0 / holographic
       │                              │
       v                              v
┌──────────────────────────────────────────┐
│ MemoryManager（协调器）                    │
│                                          │
│  每轮对话前：                              │
│    prefetch_all(query)                   │
│    → 内置：加载 MEMORY.md                 │
│    → 外部：调 provider.prefetch(query)    │
│    → 合并上下文注入消息                    │
│                                          │
│  每轮对话后：                              │
│    sync_all(user_msg, assistant_msg)     │
│    → 内置：可能写 MEMORY.md               │
│    → 外部：调 provider.sync_turn(...)     │
│                                          │
│  工具路由：                                │
│    内置工具：memory(action="add", ...)    │
│    外部工具：honcho_search(query="...")   │
│    → 按工具名路由到正确的提供者            │
└──────────────────────────────────────────┘
```

## MemoryProvider 接口

一个外部记忆提供者必须实现的方法：

```python
class MemoryProvider(ABC):
    # --- 必须实现 ---

    @property
    def name(self) -> str:
        """短标识符，如 'honcho'、'mem0'。"""
        ...

    def is_available(self) -> bool:
        """检查是否可用（不做网络请求，只查配置和依赖）。"""
        ...

    def initialize(self, session_id: str, **kwargs):
        """会话开始时初始化（创建连接、加载状态）。"""
        ...

    def get_tool_schemas(self) -> list[dict]:
        """返回这个提供者暴露给模型的工具列表。"""
        ...

    # --- 可选实现（有默认空实现）---

    def prefetch(self, query: str) -> str:
        """每轮对话前召回相关上下文。必须快（可用后台线程预取）。"""
        return ""

    def sync_turn(self, user_content: str, assistant_content: str):
        """每轮对话后持久化。应该非阻塞（排队到后台）。"""
        pass

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """执行提供者自己的工具调用。"""
        return "{}"

    def shutdown(self):
        """关闭连接、刷新队列。"""
        pass
```

4 个必须方法 + 4 个可选方法。和 s14 的 BaseEnvironment（2 个方法）、s13 的 BasePlatformAdapter（3 个方法）是同一种思路——定义接口，让实现者只关心自己的逻辑。

## MemoryManager 怎么协调

```python
class MemoryManager:
    def __init__(self):
        self._providers: list[MemoryProvider] = []
        self._has_external = False
        self._tool_to_provider: dict[str, MemoryProvider] = {}

    def add_provider(self, provider: MemoryProvider):
        """注册一个提供者。外部提供者最多一个。"""
        if provider.name != "builtin":
            if self._has_external:
                print(f"  [memory] external provider already active, rejecting {provider.name}")
                return
            self._has_external = True

        self._providers.append(provider)

        # 索引工具名 → 提供者，用于路由
        for schema in provider.get_tool_schemas():
            self._tool_to_provider[schema["name"]] = provider

    def prefetch_all(self, query: str) -> str:
        """每轮对话前，向所有提供者召回上下文。"""
        parts = []
        for provider in self._providers:
            try:
                context = provider.prefetch(query)
                if context:
                    parts.append(f"[{provider.name}] {context}")
            except Exception as exc:
                pass  # 一个提供者失败不影响其他
        return "\n".join(parts)

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """按工具名路由到正确的提供者。"""
        provider = self._tool_to_provider.get(tool_name)
        if not provider:
            return json.dumps({"error": f"Unknown memory tool: {tool_name}"})
        return provider.handle_tool_call(tool_name, args)
```

关键设计：**一个提供者失败不影响其他。** prefetch、sync、tool call 全部用 try/except 包裹。Honcho 服务挂了，内置记忆照常工作。

## 用 Honcho 走一遍完整流程

```text
1. 配置
   config.yaml: memory.provider = "honcho"

2. 启动
   → load_memory_provider("honcho")
   → 找到 plugins/memory/honcho/__init__.py
   → 调 register(ctx) → 创建 HonchoMemoryProvider 实例
   → provider.is_available() → 检查 SDK 已装、API key 已配
   → manager.add_provider(provider)
   → manager.initialize_all(session_id="...")

3. 每轮对话前（prefetch）
   用户说"我上周提到的那个 bug 修好了吗？"
   → manager.prefetch_all("我上周提到的那个 bug 修好了吗？")
     → 内置：加载 MEMORY.md（可能没有相关信息）
     → Honcho：语义搜索 → "上周用户提到了 #1234 null pointer bug，当时还没修"
   → 合并注入消息：
     <memory-context>
     [honcho] 上周用户提到了 #1234 null pointer bug，当时还没修
     </memory-context>
   → 模型看到上下文，能回答"那个 bug 是 #1234，我来检查一下"

4. 模型调用 Honcho 工具
   → tool_call: honcho_search(query="null pointer bug")
   → manager.handle_tool_call("honcho_search", ...) → 路由到 Honcho 提供者
   → Honcho 返回搜索结果

5. 每轮对话后（sync）
   → manager.sync_all("我上周提到的...", "那个 bug 是 #1234，已经修好了")
     → 内置：检查是否需要写 MEMORY.md
     → Honcho：把这轮对话存入 Honcho 后端（非阻塞，排队到后台线程）

6. 关闭
   → manager.shutdown_all()
   → Honcho：刷新队列、关闭连接
```

**如果换成 mem0？** 改 `config.yaml` 里一行 `memory.provider = "mem0"`。核心代码不动。

## 插件怎么被发现和加载

```text
plugins/memory/                      ← 仓库自带的提供者
  ├── honcho/
  │   ├── __init__.py               ← register(ctx) 函数
  │   └── plugin.yaml               ← 元数据（名字、描述）
  ├── mem0/
  ├── holographic/
  └── ...

~/.hermes/plugins/                   ← 用户自己装的
  └── my-memory/
      ├── __init__.py
      └── plugin.yaml
```

加载顺序：仓库自带的优先，名字冲突时自带的赢。

每个插件的 `__init__.py` 必须有一个 `register(ctx)` 函数：

```python
# plugins/memory/honcho/__init__.py

def register(ctx):
    ctx.register_memory_provider(HonchoMemoryProvider())
```

`ctx` 是一个 collector 对象，加载器通过它收集提供者实例。这个模式让插件不需要知道 MemoryManager 的存在——它只管把自己注册进去。

## 如何接到主循环里

MemoryManager 在核心循环的两个点介入：

```text
核心循环每一轮：

  1. 用户消息到达
       │
       v
  2. manager.prefetch_all(user_message)  ← 对话前：召回上下文
       │  注入到消息里
       v
  3. 发给模型 → 模型返回
       │
       ├── 如果 tool_call 是记忆工具 → manager.handle_tool_call(...)
       │
       v
  4. manager.sync_all(user_msg, assistant_msg)  ← 对话后：持久化
       │
       v
  5. 下一轮
```

核心循环只调 manager 的三个方法（prefetch_all、handle_tool_call、sync_all）。不知道也不关心背后是哪个提供者。

## 初学者最容易犯的错

### 1. 同时激活两个外部提供者

"我想同时用 Honcho 的用户建模和 mem0 的语义搜索"——MemoryManager 会拒绝第二个。

**修：选一个。如果需要多种能力，选能力最全的提供者，或者等社区出组合方案。**

### 2. prefetch 做了网络请求导致每轮对话变慢

prefetch 在用户消息到达后、发给模型前执行。如果 Honcho API 慢了 2 秒，每轮对话都多等 2 秒。

**修：用后台线程预取。Honcho 的实现在每轮对话结束时 `queue_prefetch()` 预取下一轮的上下文，下一轮 `prefetch()` 直接读缓存。**

### 3. 提供者抛异常导致对话挂了

Honcho 的 API 挂了，prefetch 抛异常。

**修：MemoryManager 对每个提供者的调用都包了 try/except。一个挂了不影响其他。**

### 4. 不理解"内置始终在线"

以为配了 Honcho 就不用 MEMORY.md 了。实际上内置记忆始终工作，Honcho 是额外的增强。两者的工具和上下文会合并。

## 教学边界

这一章讲 Hermes Agent 的三套插件系统中最核心的一套：记忆提供者。

讲三件事：

1. **MemoryProvider 接口** — 4 个必须方法 + 4 个可选方法
2. **MemoryManager 怎么协调** — prefetch、sync、工具路由、单外部提供者限制
3. **插件怎么发现和加载** — 目录扫描 + `register(ctx)` 模式

不讲的：

- ContextEngine（上下文压缩策略插件） → 模式和 MemoryProvider 相同，只是接口不同
- 通用插件系统（hooks、CLI 命令） → 更广泛的扩展机制
- 每个记忆提供者的内部实现 → 各自的 API 文档
- 插件安全扫描 → 安全机制

## 这一章和后续章节的关系

- **s07** 定义了内置记忆 → 本章让外部服务增强它
- **s05** 定义了内置压缩 → ContextEngine 插件让外部策略替换它（同一种模式）
- **s16** 的 MCP 扩展工具能力 → 本章扩展记忆能力，都是"不改核心代码就能加功能"
- **s02** 的工具自注册 → 插件的 `register(ctx)` 是同一种注册模式

## 学完这章后，你应该能回答

- 内置记忆和外部提供者是什么关系？配了 Honcho 后 MEMORY.md 还工作吗？
- 为什么同一时间只能有一个外部记忆提供者？
- MemoryProvider 的 `prefetch` 为什么必须快？如果 API 很慢怎么办？
- 如果 Honcho 的 API 挂了，agent 还能正常对话吗？
- 从 Honcho 切到 mem0，需要改几行核心代码？

---

**一句话记住：定义接口、按配置加载、协调器路由——不改核心代码就能切换记忆后端。**
