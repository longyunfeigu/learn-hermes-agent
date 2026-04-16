# s22: Hook System & BOOT.md (生命周期 Hook)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > [ s22 ] > s23 > s24`

> *到 s21，agent 的核心能力和自我进化机制都已经完整了。但如果你想在"agent 每次启动时自检一遍"或"每次工具调用前加一层审计"——你不需要改核心代码，只需要挂一个 hook。*

![生命周期 Hook 系统](../../illustrations/s22-hook-system/01-framework-lifecycle-hooks.png)

## 这一章要解决什么问题

三个场景。

**场景 1：启动自检。** 你希望 agent 每次启动时自动检查一下昨晚的定时任务有没有失败、磁盘空间够不够。不改代码，只需要写一个 `BOOT.md`：

```markdown
# Startup Checklist
1. Check if any cron jobs failed overnight
2. Check disk usage, alert if any partition > 80%
3. If there are errors in deploy.log, summarize them
```

agent 启动时自动执行这份 checklist，像一个值班工程师一样先巡检一遍。

**场景 2：工具审计。** 你想在每次 `terminal` 工具调用前记一条日志——谁在什么时候执行了什么命令。不改 terminal 工具的代码，挂一个 `pre_tool_call` hook：

```python
def audit_tool(tool_name, args, **kw):
    if tool_name == "terminal":
        log(f"[audit] {datetime.now()} terminal: {args.get('command')}")
```

**场景 3：会话总结。** 每次对话结束后，自动生成一段摘要存到一个 log 文件里。不改核心循环，挂一个 `on_session_end` hook。

三个场景的共同点：**在核心循环的特定时刻插入自定义逻辑，不修改核心代码。**

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — `pre_tool_call` / `post_tool_call` hook 在工具调用的前后触发
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) — Gateway hooks 在消息路由的关键节点触发
- [`s20-background-review.md`](./s20-background-review.md) — 后台审视可以看作一种内置的"session 结束后"hook

## 先解释几个名词

### 什么是生命周期 hook

agent 从启动到退出有几个关键时刻：

```text
gateway:startup  →  session:start  →  agent:start
                                          │
                                     (工具调用循环)
                                     pre_tool_call → 执行 → post_tool_call
                                          │
                                     agent:end  →  session:end
```

hook 是你挂在这些时刻上的回调函数。到了那个时刻，系统自动调你的函数。

### 什么是 BOOT.md

一个 Markdown 文件，放在 `~/.hermes/BOOT.md`。Gateway 启动时自动把它的内容作为 prompt 发给一个一次性 agent 执行。

不是 shell 脚本——是 agent 的指令。你可以在里面写"检查日志"、"发一条消息到 Discord"，agent 会用自己的工具去完成。

### 两套 hook 系统

Hermes Agent 有两套独立的 hook 系统，面向不同场景：

| | Gateway hooks | Plugin hooks |
|---|---|---|
| 范围 | 仅 Gateway 模式 | CLI + Gateway 都可用 |
| 注册方式 | `~/.hermes/hooks/` 目录下的文件 | 代码里 `register_hook()` |
| 触发方式 | `emit(event_type, context)` | `invoke_hook(hook_name, **kwargs)` |
| 执行模型 | 异步（支持 async） | 同步 |
| 用途 | 平台级事件（连接、消息路由） | agent 级事件（工具调用、API 请求） |

教学上先分开讲清楚，再解释为什么是两套。

## 最小心智模型

```text
~/.hermes/BOOT.md
    │  "启动时检查 cron 和磁盘"
    │
    v
Gateway 启动 → emit("gateway:startup")
    │
    │  boot-md hook: 读 BOOT.md → 启动一次性 agent → 执行指令
    │
    v
用户发消息 → emit("session:start") / emit("agent:start")
    │
    │  → plugin hooks: invoke_hook("pre_llm_call") → 注入上下文
    │  → 模型调用
    │  → plugin hooks: invoke_hook("pre_tool_call") → 审计日志
    │  → 工具执行
    │  → plugin hooks: invoke_hook("post_tool_call")
    │
    v
agent 完成 → emit("agent:end")
    │
    │  → plugin hooks: invoke_hook("on_session_end") → 会话总结
    │
    v
会话结束 → emit("session:end")
```

## 第一部分：Gateway hooks

### 事件类型

| 事件 | 触发时机 | context 包含 |
|------|---------|-------------|
| `gateway:startup` | Gateway 进程启动 | `platforms`（已连接的平台列表） |
| `session:start` | 新会话创建 | `platform`, `user_id`, `session_key` |
| `session:end` | 会话结束 | `platform`, `user_id`, `session_key` |
| `session:reset` | 用户执行 `/new` | `platform`, `user_id`, `session_key` |
| `agent:start` | agent 开始处理消息 | `platform`, `user_id`, `message` |
| `agent:end` | agent 完成处理 | `platform`, `user_id`, `message`, `response` |
| `command:*` | 任何斜杠命令 | `platform`, `user_id`, `command`, `args` |

`command:*` 是通配符——注册一次就能监听所有命令。

### hook 文件结构

```text
~/.hermes/hooks/
└── my-audit-hook/
    ├── HOOK.yaml       ← 声明名称、描述、监听哪些事件
    └── handler.py      ← 实际执行的代码
```

**HOOK.yaml：**

```yaml
name: my-audit-hook
description: Log all agent activity
events:
  - agent:start
  - agent:end
```

**handler.py：**

```python
async def handle(event_type: str, context: dict):
    if event_type == "agent:start":
        print(f"[audit] agent started for {context.get('user_id')}")
    elif event_type == "agent:end":
        print(f"[audit] agent done, response: {context.get('response', '')[:50]}")
```

handler 可以是 `def` 也可以是 `async def`——系统用 `asyncio.iscoroutine()` 自动检测。

### HookRegistry

```python
class HookRegistry:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def register(self, event_type: str, handler: Callable):
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event_type: str, context: dict | None = None):
        handlers = list(self._handlers.get(event_type, []))
        # 通配符匹配：command:* 匹配所有 command:xxx
        if ":" in event_type:
            base = event_type.split(":")[0]
            handlers.extend(self._handlers.get(f"{base}:*", []))
        for fn in handlers:
            try:
                result = fn(event_type, context or {})
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"[hooks] Error in handler for '{event_type}': {e}")
```

关键设计：**hook 的异常永远不传播。** `try/except` 确保一个坏 hook 不会搞崩整个 Gateway。

### 自动发现

```python
def discover_and_load(self, hooks_dir: Path):
    """Scan hooks directory, load HOOK.yaml + handler.py."""
    if not hooks_dir.exists():
        return
    for hook_dir in sorted(hooks_dir.iterdir()):
        manifest = hook_dir / "HOOK.yaml"
        handler_file = hook_dir / "handler.py"
        if not manifest.exists() or not handler_file.exists():
            continue
        meta = yaml.safe_load(manifest.read_text())
        # 动态导入 handler.py
        spec = importlib.util.spec_from_file_location(meta["name"], handler_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handle_fn = getattr(module, "handle")
        for event in meta.get("events", []):
            self.register(event, handle_fn)
```

## 第二部分：BOOT.md

BOOT.md 是一个内置的 Gateway hook，绑定到 `gateway:startup` 事件。

### 工作原理

```python
async def handle_boot_md(event_type: str, context: dict):
    boot_path = HERMES_HOME / "BOOT.md"
    if not boot_path.exists():
        return

    content = boot_path.read_text()

    def _run():
        # 创建一次性 agent，执行 BOOT.md 的指令
        conn = init_db(DB_PATH)
        session_id = create_session(conn)
        prompt = build_system_prompt(os.getcwd())
        result = run_conversation(
            user_message=content,
            conn=conn,
            session_id=session_id,
            cached_prompt=prompt,
            max_iterations_override=20,
        )
        conn.close()
        return result

    # 在后台线程执行，不阻塞 Gateway 启动
    thread = threading.Thread(target=_run, daemon=True, name="boot-md")
    thread.start()
```

**场景：启动自检流程**

```text
1. Gateway 启动
2. HookRegistry 发现内置 boot-md hook
3. emit("gateway:startup") → handle_boot_md 被调用
4. 读取 ~/.hermes/BOOT.md:
     "1. 检查 cron 有没有失败
      2. 检查磁盘使用率"
5. 后台线程启动一次性 agent
6. agent 调 terminal 工具跑 df -h，发现 /data 85%
7. agent 调 terminal 工具检查 cron 日志，发现昨晚 backup 失败
8. agent 把结果通过 Gateway 回调发给用户（如果配置了 home channel）
9. Gateway 继续正常运行，不受 boot 过程影响
```

**为什么不用 shell 脚本？** 因为 BOOT.md 里的指令由 agent 执行，agent 可以用它的全部工具——终端、浏览器、MCP 工具。`df -h` 只是最简单的例子，你还可以写"登录监控面板检查告警"。

## 第三部分：Plugin hooks

### hook 类型

| hook | 触发时机 | 能做什么 |
|------|---------|---------|
| `pre_tool_call` | 工具执行**前** | 审计日志、拦截危险操作 |
| `post_tool_call` | 工具执行**后** | 记录结果、统计耗时 |
| `pre_llm_call` | 一轮对话开始前 | 注入额外上下文 |
| `post_llm_call` | 一轮对话完成后 | 记录结果 |
| `on_session_start` | 新会话第一轮 | 初始化资源 |
| `on_session_end` | 每轮对话结束 | 清理、总结 |

### 注册方式

```python
class PluginHookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}

    def register_hook(self, hook_name: str, callback: Callable):
        self._hooks.setdefault(hook_name, []).append(callback)

    def invoke_hook(self, hook_name: str, **kwargs) -> list:
        results = []
        for cb in self._hooks.get(hook_name, []):
            try:
                ret = cb(**kwargs)
                if ret is not None:
                    results.append(ret)
            except Exception as e:
                print(f"  [hook] {hook_name} error: {e}")
        return results
```

### 场景：工具审计 hook

```python
# 注册
hooks = PluginHookRegistry()

audit_log = []

def audit_tool_call(tool_name, args, **kw):
    audit_log.append({
        "time": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
    })

hooks.register_hook("pre_tool_call", audit_tool_call)

# 在工具分发时触发
hooks.invoke_hook("pre_tool_call", tool_name="terminal",
                  args={"command": "rm -rf /tmp/build"})

# audit_log 里就有了一条记录
```

### 集成到 run_conversation

```python
# 工具调用前
hooks.invoke_hook("pre_tool_call", tool_name=tool_name, args=tool_args)
output = registry.dispatch(tool_name, tool_args)
# 工具调用后
hooks.invoke_hook("post_tool_call", tool_name=tool_name,
                  args=tool_args, result=output)
```

## 为什么是两套 hook 系统

| 维度 | Gateway hooks | Plugin hooks |
|------|--------------|-------------|
| 粒度 | 粗（会话级、平台级） | 细（工具调用级、API 调用级） |
| 部署方式 | 文件目录，不需要写代码 | 代码注册，需要 Python |
| 适用场景 | 运维：监控、告警、审计 | 开发：调试、定制、扩展 |
| 热加载 | 启动时扫描，不支持热更新 | 代码注册，启动时执行 |

把两套合并成一套可以吗？技术上可以，但会让简单场景变复杂。运维人员只需要写一个 HOOK.yaml + 几行 Python，不需要理解 plugin 注册链。

## What Changed（s21 → s22）

| 组件 | s21 | s22 |
|------|-----|-----|
| 扩展方式 | 只能改代码 | hook 目录 + 代码注册 |
| 启动行为 | 固定 | BOOT.md 可定制 |
| 工具审计 | 无 | pre/post_tool_call |
| 会话生命周期 | 无 hook | on_session_start/end |
| 错误隔离 | 无 | 所有 hook 异常不传播 |

## 初学者最容易犯的错

### 1. hook 里做耗时操作阻塞主循环

```python
# 错：pre_tool_call 里调外部 API
def slow_audit(tool_name, args, **kw):
    requests.post("https://audit.example.com", json={...})  # 2 秒
```

agent 每调一个工具都要等 2 秒。

**修：耗时操作放进队列或线程。hook 本身只做快速操作（写本地文件、加队列）。**

### 2. handler.py 没有 handle 函数

```python
# 错：handler.py
def on_event(event_type, context):  # 名字不对
    ...
```

系统用 `getattr(module, "handle")` 找入口函数。名字不是 `handle` 就找不到。

**修：函数必须叫 `handle`。**

### 3. 以为 hook 能修改工具参数

```python
# 错：试图在 pre_tool_call 里修改 args
def modify_args(tool_name, args, **kw):
    args["command"] = "echo safe"  # 不会生效
```

hook 收到的 `args` 是传值，不是传引用。修改它不影响实际执行。

**修：如果要拦截，返回 `{"action": "block"}` 让系统阻止执行。**

### 4. BOOT.md 写了交互式操作

```markdown
# 错：需要用户回答
1. Ask the user which project to check
```

BOOT.md 在 Gateway 启动时执行，没有用户在场。交互式操作会卡住。

**修：BOOT.md 里只写不需要用户参与的自动化指令。**

## 教学边界

这一章讲四件事：

1. **Gateway hooks** — 事件类型、HOOK.yaml + handler.py、HookRegistry
2. **BOOT.md** — 内置 gateway hook，启动时自检
3. **Plugin hooks** — pre/post_tool_call、on_session_start/end
4. **为什么两套** — 粒度不同、部署方式不同、面向不同用户

不讲的：

- `pre_api_request` / `post_api_request` → 类似 pre_tool_call，模式相同
- plugin 的发现和加载机制（pip entry-points）→ 包管理细节
- hook 热更新 → 生产优化
- `pre_llm_call` 的上下文注入 → 高级用法

## 这一章和其他章节的关系

- **s02** 的工具分发 → `pre_tool_call` / `post_tool_call` 在分发的前后触发
- **s12** 的 Gateway → Gateway hooks 在 GatewayRunner 的关键节点触发
- **s15** 的定时任务 → BOOT.md 可以检查 cron 任务状态
- **s20** 的后台审视 → 审视本质上是一种内置的 `on_session_end` hook
- **s24** 的 Plugin 架构 → plugin hooks 是 plugin 生态的基础

## 学完这章后，你应该能回答

- 写一个 hook 来记录所有 terminal 工具的执行日志，需要哪些文件？
- BOOT.md 为什么用 agent 执行而不是用 shell？
- Gateway hooks 和 Plugin hooks 为什么不合并成一套？
- hook 里抛了异常会怎样？agent 会崩吗？
- `pre_tool_call` hook 能阻止工具执行吗？怎么做？

---

**一句话记住：hook 让你在 agent 生命周期的关键时刻插入自定义逻辑——不改核心代码，不影响其他功能，异常不传播。BOOT.md 是最简单的 hook：一个 Markdown 文件，agent 启动时自动执行。**
