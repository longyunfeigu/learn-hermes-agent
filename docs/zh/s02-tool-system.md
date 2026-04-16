# s02: Tool System (工具系统)

`s00 > s01 > [ s02 ] > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *"加一个工具，只加一个文件"* — 循环不用动，注册表不用改，编排层不用改。
>
> **Harness 层**: 工具注册与分发 — 让 50+ 工具和 MCP 外部工具共存而互不干扰。

## 问题

s01 的循环里 `run_tool()` 是个黑盒。最直觉的实现是 if/elif 链，但 Hermes Agent 有 50+ 内置工具，还有 MCP 外部工具可以动态加入。每加一个工具就要改分发代码，系统会很快失控。

关键洞察: 加工具不需要改循环，也不需要改任何中心配置文件。

## 解决方案

Hermes Agent 把工具系统分成三层，靠导入链连接：

![工具系统导入链](../../illustrations/s02-tool-system/01-framework-import-chain.png)

```
registry.py          (不导入任何工具)
     ^
tools/*.py           (导入 registry，注册自己)
     ^
model_tools.py       (导入所有 tools/*.py，触发注册)
     ^
run_agent.py         (导入 model_tools.py，使用接口)

注册表在最底层，不依赖任何工具。这是整个设计能工作的关键。
```

## 工作原理

### 1. 工具文件自注册

每个工具文件在末尾调用 `register()`：

```python
# tools/web_tools.py
from tools.registry import registry

def handle_web_search(args, **kwargs):
    query = args.get("query", "")
    # ... 执行搜索 ...
    return json.dumps({"results": [...]})

registry.register(
    name="web_search",
    toolset="web",
    schema={"name": "web_search", "description": "Search the web", "parameters": {...}},
    handler=handle_web_search,
    is_async=True,
    requires_env=["SERP_API_KEY"],
)
```

### 2. 编排层触发发现

编排层的作用是让所有工具"自动上线"，而不需要手动一个个配置。

它利用的是 Python 的一个基本规则：**`import` 一个模块时，模块里的顶层代码会立即执行**。上面每个工具文件末尾的 `registry.register(...)` 就是顶层代码——只要被导入，注册就自动发生。

编排层要做的就是把所有工具模块导入一遍：

```python
# model_tools.py
from tools.registry import registry

_modules = [
    "tools.web_tools",       # import → 末尾的 register() 自动执行 → web_search 注册了
    "tools.terminal_tool",   # import → register() 执行 → terminal 注册了
    "tools.file_tools",      # import → register() 执行 → read_file、write_file 注册了
    "tools.vision_tools",
    "tools.skills_tool",
    "tools.memory_tool",
    # ... 20+ 模块
]
for mod in _modules:
    importlib.import_module(mod)

# MCP 外部工具也在这里发现和注册
from tools.mcp_tool import discover_mcp_tools
discover_mcp_tools()
```

`importlib.import_module("tools.web_tools")` 和直接写 `import tools.web_tools` 效果一样，只不过模块名可以是字符串变量，所以能放在列表里循环导入。加一个新工具只需要往列表里加一行字符串。

整体流程：

![工具注册与分发流程](../../illustrations/s02-tool-system/02-flowchart-dispatch.png)

```text
model_tools.py 启动
  → import tools.web_tools    → register("web_search") 自动执行
  → import tools.terminal_tool → register("terminal")  自动执行
  → import tools.file_tools   → register("read_file")  自动执行
  → ...
  → discover_mcp_tools()      → 外部 MCP 工具也注册进来

结果：registry 里现在有了 50+ 工具，循环里 dispatch("web_search") 就能找到它
```

### 3. 注册表分发执行

```python
# tools/registry.py
class ToolRegistry:
    def dispatch(self, name, args, **kwargs):
        entry = self._tools.get(name)
        if not entry:
            return json.dumps({"error": f"Unknown tool: {name}"})
        if entry.is_async:
            return _run_async(entry.handler(args, **kwargs))
        return entry.handler(args, **kwargs)
```

`is_async` 标记是 Hermes 独有的设计。核心循环是同步的，但网络请求、浏览器操作等工具是 async 的。注册表看到标记后自动走异步桥接，工具文件和核心循环都不需要关心这个细节。

### 4. 异步桥接

```python
# model_tools.py
def _run_async(coro):
    # 不用 asyncio.run()（它会创建新循环然后关闭，缓存的 httpx 客户端会报错）
    # 而是用持久化事件循环
    tool_loop = _get_tool_loop()
    return tool_loop.run_until_complete(coro)
```

为什么不直接 `asyncio.run()`? 因为它每次创建新循环然后关闭。工具内部缓存的 httpx / AsyncOpenAI 客户端绑定在旧循环上，循环关了客户端就废了。持久化循环让客户端缓存一直有效。

### 5. Toolset 开关和可用性检查

```python
# 注册时可以指定 check_fn
registry.register(
    name="browser_navigate",
    toolset="browser",
    check_fn=lambda: bool(os.environ.get("BROWSERBASE_API_KEY")),
    # ...
)

# get_definitions() 只返回 check_fn 通过的工具
# 没有 API key → 这个工具不会出现在给模型的 schema 列表里
```

## 相对 s01 的变更

| 组件 | 之前 (s01) | 之后 (s02) |
|---|---|---|
| 工具 | `run_tool` 黑盒 | 注册表 → 编排层 → 分发 |
| 添加新工具 | 要改循环 | 只加一个文件 |
| 异步工具 | 不支持 | `is_async` 标记 + 持久化事件循环桥接 |
| 工具筛选 | 无 | toolset 开关 + check_fn 可用性检查 |
| MCP 外部工具 | 无 | 编排层发现后注册进同一个注册表 |
| 核心循环 | 不变 | 不变 |

## 试一试

```sh
cd learn-hermes-agent
python agents/s02_tool_system.py
```

试试这些 prompt:

1. `搜索 Python 3.12 的新特性` — 走 web_search 工具
2. `读一下 requirements.txt` — 走 read_file 工具
3. `在终端里执行 ls -la` — 走 terminal 工具
4. `创建一个 hello.py 文件` — 走 write_file 工具

观察：你没有改循环代码，但四种不同的工具都能正常调用。

## 如果你开始觉得"工具不只是注册 + 分发"

到这里为止，工具系统先讲成：

- schema（给模型看的说明书）
- handler（真正执行的函数）
- dispatch（按名字查表调用）

这是对的，必须先这么学。

但继续做大时，你会发现工具执行前后还会长出：权限检查（`s09`）、MCP 外部工具桥接（`s16`）、结果大小限制、并行执行策略。这些在后续章节展开。

## 教学边界

这一章讲透三件事：

1. **自注册模式** — 工具文件注册自己，编排层只管导入
2. **导入链** — registry ← tools ← model_tools ← run_agent，不能反向
3. **异步桥接** — `is_async` 标记 + 持久化事件循环

先不管的：权限（`s09`）、MCP（`s16`）、技能和工具的关系（`s08`）。

加一个工具只需要加一个文件 — 如果读者能做到这一点，这一章就达标了。
