# s19: CLI & Web Interface (终端界面与 Web 面板)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > [ s19 ] > s20 > s21 > s22 > s23 > s24`

> *s01-s17 的 agent 一直在一个 `input()`/`print()` 裸终端里跑。真正面向用户时，你需要流式输出、进度反馈、斜杠命令——还需要一个 Web 面板让你不开终端也能管它。*

![CLI 与 Web 双界面](../../illustrations/s19-cli-web/01-comparison-cli-web.png)

## 这一章要解决什么问题

三个场景。

**场景 1：沉默的等待。** 你让 agent 帮你重构一个文件。它调了 5 个工具，跑了 40 秒。整个过程终端上什么都没有——你以为它挂了，按了 Ctrl+C，结果它正要返回最终结果。

```text
You: 帮我重构 parser.py
                            ← 40 秒沉默
                            ← 用户按 Ctrl+C
(agent 的 5 次工具调用全部丢失)
```

**场景 2：一口气吐。** 你问了一个复杂问题。模型生成了 2000 字。裸 CLI 等 30 秒后一次性把 2000 字砸到屏幕上——你的眼睛追着滚了 3 屏。

```text
You: 解释一下这个系统的架构
                            ← 30 秒沉默
Assistant: [2000 字瞬间涌出，滚了 3 屏]
```

**场景 3：想改配置但不想开终端。** 周末你在手机上，想看看 agent 昨天执行了什么定时任务、改一下 API key。但 agent 只有 CLI 入口——你得 SSH 到服务器才能操作。

这一章解决这三个问题：

1. **交互式终端** — prompt_toolkit 让输入区固定在底部，输出往上滚，工具调用有 spinner
2. **流式输出** — 模型每生成一个 token 就立刻渲染，不用等完整回复
3. **Web 管理面板** — FastAPI 暴露 REST API，React 前端做配置和会话管理

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — 工具进度回调是 s02 工具调用机制的扩展
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) — Web 面板本质上是又一个 adapter
- [`s15-scheduled-tasks.md`](./s15-scheduled-tasks.md) — Web 面板可以管理定时任务

## 先解释几个名词

### 什么是 patch_stdout

prompt_toolkit 的核心技巧。正常的 `print()` 会把文字写到光标当前位置——如果你的输入区在底部，`print()` 会把输入区搅乱。

`patch_stdout()` 劫持所有 `print()` 调用，把输出重定向到输入区上方的滚动区域。**输入区永远不动，输出往上滚。**

```text
┌──────────────────────────────────┐
│  [tool] terminal: ls -la    0.3s │  ← 输出区（往上滚）
│  [tool] read_file: src/...  0.1s │
│  Assistant: 这个目录下有...      │
│                                  │
├──────────────────────────────────┤
│ You: _                           │  ← 输入区（固定在底部）
└──────────────────────────────────┘
```

### 什么是 stream_delta

模型 API 在流式模式下，不是等生成完毕才返回，而是每生成一个 token 就通过回调发送一个 delta（增量文本片段）。

`stream_delta_callback` 是 CLI 注册到 agent 上的一个函数——每收到一个 delta，CLI 就立刻渲染到屏幕上。

### 什么是斜杠命令

用户输入以 `/` 开头的文本不发给模型，而是由 CLI 自己处理。例如：

- `/help` — 显示帮助
- `/new` — 开始新会话
- `/model` — 切换模型
- `/tools` — 管理工具集

斜杠命令通过一个中心注册表 `COMMAND_REGISTRY` 定义，支持别名和 Tab 补全。

## 最小心智模型

```text
用户
  │
  ├── 终端输入
  │     │
  │     v
  │   HermesCLI
  │     ├── 斜杠命令？ → process_command() 本地处理
  │     └── 普通消息？ → run_conversation()
  │                          │
  │                          │ stream_delta_callback(token)
  │                          v
  │                     _stream_delta()
  │                          │ 行缓冲 → _cprint() → patch_stdout → 屏幕
  │                          │
  │                     _on_tool_progress(event)
  │                          │ spinner 更新 / 持久化行
  │
  └── 浏览器
        │
        v
      FastAPI (/api/sessions, /api/config, /api/cron, ...)
        │
        └── 读写同一个 SQLite / config.yaml / jobs.json
```

CLI 和 Web 不是两个独立的系统。它们操作的是同一份数据——SQLite 里的会话、config.yaml 里的配置、jobs.json 里的定时任务。

## 第一部分：交互式终端

### 从裸 CLI 到 TUI

s01-s17 的 `run_cli()` 是这样的：

```python
while True:
    user_input = input("You: ")       # 阻塞，无法同时显示进度
    result = run_conversation(...)     # 等全部完成才返回
    print(f"Assistant: {result}")      # 一次性吐出
```

三个问题在这三行里全都能看到。

HermesCLI 的做法：

```python
class HermesCLI:
    def __init__(self, model=None, toolsets=None, ...):
        self.streaming_enabled = config["display"].get("streaming", False)
        self._pending_input = queue.Queue()   # 用户输入队列
        self._interrupt_queue = queue.Queue() # agent 运行中的打断队列

    def run(self):
        with patch_stdout():   # ← 所有 print 重定向到输入区上方
            app = Application(
                layout=Layout(HSplit([
                    # 输出区（自动滚动）
                    # spinner 状态行
                    # 分隔线
                    # 输入区（固定底部）
                ])),
                key_bindings=self._build_key_bindings(),
            )
            app.run()
```

`patch_stdout()` 是关键。有了它，agent 在后台调工具时 `print()` 的进度信息会出现在输入区上方，不会干扰你正在打字的区域。

### 输入路由状态机

用户按 Enter 的时候，输入不一定是发给模型的——可能是回答 sudo 密码、审批危险命令、或选择一个选项。

```text
用户按 Enter
    │
    ├── sudo_state 活跃？ → 密码交给 sudo 队列
    ├── approval_state 活跃？ → 选择交给审批队列
    ├── clarify_state 活跃？ → 回答交给选择队列
    ├── agent 正在运行？
    │     ├── 输入是斜杠命令？ → 立即执行
    │     └── 普通文本？ → 放进 interrupt_queue（下一轮插入）
    └── 空闲状态 → 放进 pending_input 队列
```

每种模态状态都有自己的队列。HermesCLI 的 `run()` 循环从 `_pending_input` 取消息处理；工具在需要交互时设置对应的 state 并等待对应的队列。

**场景：agent 要跑 `rm -rf /tmp/build`**

```text
1. terminal 工具检测到危险命令（s09）
2. 设置 _approval_state，显示审批面板
3. 用户看到面板："允许 rm -rf /tmp/build？[y/n]"
4. 用户按 y + Enter → 路由到审批队列
5. terminal 工具拿到审批结果，继续执行
6. _approval_state 清除，输入路由恢复正常
```

### 工具进度回调

agent 每调用一个工具，CLI 会收到两个事件：

```python
def _on_tool_progress(self, event_type, function_name, preview,
                      function_args, duration, is_error):
    if event_type == "tool.started":
        # 更新 spinner：显示工具名和参数摘要
        # "⚙ terminal: pip install numpy"
        pass

    elif event_type == "tool.completed":
        # 打印持久化行到滚动区
        # "  [tool] terminal: pip install numpy    2.3s"
        pass
```

Spinner 是实时更新的——agent 调了 3 个工具，你会看到 spinner 从 `terminal` 变成 `read_file` 再变成 `write_file`。每个工具完成后变成滚动区里的一行持久记录。

**四种显示模式**（通过 `display.tool_progress` 配置）：

| 模式 | 行为 |
|------|------|
| `off` | 不显示工具进度 |
| `new` | 每种工具只显示第一次（连续重复的跳过） |
| `all` | 每次调用都显示 |
| `verbose` | 显示 + 额外调试信息 |

## 第二部分：流式输出

### 回调注册

流式输出的核心是一个回调链：

```text
模型 API（流式模式）
    │ token
    v
AIAgent._fire_stream_delta(text)
    │
    ├── stream_delta_callback → HermesCLI._stream_delta(text)
    └── _stream_callback → (TTS 等其他消费者)
```

注册点在创建 agent 时：

```python
# CLI 启动时
agent = AIAgent(
    stream_delta_callback=self._stream_delta if self.streaming_enabled else None,
)
```

如果 `streaming_enabled=False`，不传回调，agent 等生成完毕后一次性返回完整文本。

### 行缓冲

模型返回的 delta 是任意长度的文本片段——可能是半个字、一个词、或几行。直接渲染半个字会导致终端闪烁。

`_stream_delta` 做行缓冲：攒够一个完整行（遇到 `\n`）才渲染。

```python
def _stream_delta(self, text):
    # None = 轮次边界信号（工具调用结束）
    if text is None:
        self._flush_stream()      # 冲刷缓冲区
        self._reset_stream_state()
        return

    self._buffer += text
    while "\n" in self._buffer:
        line, self._buffer = self._buffer.split("\n", 1)
        self._cprint(line)  # 通过 patch_stdout 渲染到输入区上方
```

### 轮次边界

agent 在一次对话中可能调多个工具。每次工具调用之间，agent 会发送 `None` 作为边界信号：

```text
模型生成文本 → delta("让我先看看文件")
模型调工具   → delta(None)          ← 轮次边界
工具执行完毕
模型继续生成 → delta("文件内容是...")
模型调工具   → delta(None)          ← 轮次边界
工具执行完毕
模型最终回复 → delta("修改完成，...")
```

CLI 收到 `None` 时：关闭当前的输出框，刷新缓冲区，准备好显示下一轮的工具进度。

## 第三部分：斜杠命令系统

### 中心注册表

所有命令在一个列表里定义：

```python
@dataclass
class CommandDef:
    name: str              # 规范名："background"
    description: str       # 帮助文本
    category: str          # "Session" / "Configuration" / "Tools & Skills"
    aliases: tuple = ()    # 短名：("bg",)
    args_hint: str = ""    # 参数占位："<prompt>"
    cli_only: bool = False # 只在 CLI 可用
    gateway_only: bool = False

COMMAND_REGISTRY = [
    CommandDef("new", "Start a new session", "Session", aliases=("reset",)),
    CommandDef("clear", "Clear screen and start new session", "Session", cli_only=True),
    CommandDef("history", "Show conversation history", "Session", cli_only=True),
    CommandDef("model", "Switch model or provider", "Configuration", args_hint="[name]"),
    CommandDef("tools", "Manage toolsets", "Tools & Skills", args_hint="[list|enable|disable]"),
    CommandDef("background", "Run prompt in background", "Session", aliases=("bg",), args_hint="<prompt>"),
    CommandDef("quit", "Exit", "Exit", cli_only=True, aliases=("exit",)),
    # ... 30+ 命令
]
```

### 分发

```python
def process_command(self, command: str) -> bool:
    cmd_word = command.split()[0].lstrip("/").lower()
    resolved = resolve_command(cmd_word)  # 查注册表，解析别名

    if resolved.name == "quit":
        return False
    elif resolved.name == "help":
        self._show_help()
    elif resolved.name == "model":
        self._handle_model_command(command)
    elif resolved.name == "tools":
        self._handle_tools_command(command)
    # ...
    return True
```

**为什么不用 if-elif 匹配原始字符串？** 因为命令有别名。`/bg` 和 `/background` 是同一个命令。注册表统一做别名解析，分发逻辑只认规范名。

**为什么有 `cli_only` 和 `gateway_only`？** 因为 `/clear`（清屏）在 Telegram 上没意义，`/approve`（审批）在 CLI 里不需要（CLI 直接弹交互式面板）。

## 第四部分：Web 管理面板

### 不是聊天界面

Web 面板不是让你在浏览器里和 agent 对话的。它是 agent 的**控制台**——查看会话历史、修改配置、管理定时任务。

为什么不做聊天？因为 CLI 的交互式体验（Tab 补全、文件路径补全、sudo 面板、inline diff）在浏览器里没法原样复制。Web 做管理，CLI 做交互。

### FastAPI 后端

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Hermes Agent")

# CORS 只允许 localhost——Web 面板只在本地用
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 临时 Token 安全

浏览器和后端在同一台机器上，但你仍然需要防止其他网站的 JavaScript 偷偷调你的 API（CSRF）。

```python
import secrets, hmac

_SESSION_TOKEN = secrets.token_urlsafe(32)  # 启动时生成

@app.middleware("http")
async def auth_middleware(request, call_next):
    if request.url.path.startswith("/api/") and path not in _PUBLIC_PATHS:
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {_SESSION_TOKEN}"
        if not hmac.compare_digest(auth.encode(), expected.encode()):
            return JSONResponse(status_code=401, detail="Unauthorized")
    return await call_next(request)
```

Token 在服务器启动时生成，通过模板变量注入到 SPA 的 HTML 里。每次重启 Token 都变——没有持久化，没有泄露风险。

`hmac.compare_digest` 防止计时攻击：即使攻击者能精确测量响应时间，也无法逐字节猜出 token。

### 核心 API

```text
GET  /api/status                    ← 公开：版本、运行状态
GET  /api/sessions?limit=20         ← 会话列表（分页）
GET  /api/sessions/search?q=...     ← 全文搜索（FTS5）
GET  /api/config                    ← 读配置
PUT  /api/config                    ← 写配置
GET  /api/cron/jobs                 ← 定时任务列表
POST /api/cron/jobs                 ← 创建定时任务
GET  /api/env                       ← 环境变量列表
PUT  /api/env                       ← 设置环境变量
GET  /api/tools/toolsets            ← 工具集列表
GET  /api/skills                    ← 技能列表
```

**场景：周末在手机上改 API key**

```text
1. 手机浏览器打开 http://your-server:8080
2. SPA 加载，自动带上注入的 session token
3. 点 "Env" 标签页
4. 找到 OPENAI_API_KEY，点 "Edit"
5. PUT /api/env {"key": "OPENAI_API_KEY", "value": "sk-new-xxx"}
6. 后端写入 .env 文件
7. 下次 agent 启动时自动读取新 key
```

### Web 面板和其他入口的关系

```text
               ┌── CLI (prompt_toolkit)
               │     交互式对话、流式输出、斜杠命令
               │
用户 ──────────┼── Web 面板 (FastAPI + React)
               │     配置管理、会话浏览、定时任务、日志
               │
               └── Gateway 适配器 (Telegram / Discord / ...)
                     多平台消息收发
               
               所有入口共享同一份数据：
               SQLite / config.yaml / jobs.json / skills/
```

Web 面板本质上是另一个"适配器"——只不过它不走 agent 对话循环，而是直接操作底层数据。

## What Changed（s17 → s19）

| 组件 | s17 | s19 |
|------|-----|-----|
| CLI 输入 | `input()` 阻塞式 | prompt_toolkit 固定输入区 |
| CLI 输出 | `print()` 一次性 | `patch_stdout()` + 流式渲染 |
| 工具进度 | 无反馈 | spinner + `_on_tool_progress` 回调 |
| 模型输出 | 等完整回复 | `stream_delta_callback` 逐 token 渲染 |
| 命令系统 | 无 | `COMMAND_REGISTRY` + 别名 + Tab 补全 |
| 模态交互 | 无 | sudo / 审批 / 选择面板（队列驱动） |
| Web 接口 | 无 | FastAPI REST API + React SPA |
| 安全 | 无 | 临时 token + CORS localhost-only |

## 初学者最容易犯的错

### 1. 不用 patch_stdout 直接 print

```python
# 错：print 会打断输入区
print("工具执行完毕")
```

在 prompt_toolkit 的 Application 里直接 `print()` 会把输出写到输入区中间，布局全乱。

**修：所有输出必须走 `patch_stdout()` 上下文里的 `print()`，或者用 prompt_toolkit 的 `print_formatted_text()`。**

### 2. 流式回调里做耗时操作

```python
def _stream_delta(self, text):
    # 错：在回调里做文件写入
    with open("log.txt", "a") as f:
        f.write(text)
    self._render(text)
```

`_stream_delta` 在模型返回的 IO 线程里被调用。耗时操作会阻塞后续 token 的接收，让流式输出变成间歇性的卡顿。

**修：回调里只做渲染。日志写入放到队列里异步处理。**

### 3. Web API 忘了 CORS 限制

```python
# 错：允许所有来源
app.add_middleware(CORSMiddleware, allow_origins=["*"])
```

你的 API 能读写 API key 和配置。`allow_origins=["*"]` 意味着任何网站的 JavaScript 都能调你的 API——打开一个恶意网页就能偷走你的 key。

**修：只允许 localhost。`allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"`**

### 4. 字符串比较 token 导致计时攻击

```python
# 错：普通字符串比较
if auth_header == f"Bearer {token}":
```

Python 的 `==` 在发现第一个不匹配的字符时就返回 False。攻击者可以通过测量响应时间逐字节猜出 token。

**修：`hmac.compare_digest()` 恒定时间比较。**

## 教学边界

这一章讲四件事：

1. **prompt_toolkit TUI 布局** — 固定输入区、输出滚动、模态面板
2. **流式输出** — stream_delta 回调、行缓冲、轮次边界
3. **斜杠命令系统** — 中心注册表、别名解析、分发
4. **Web 管理面板** — FastAPI + 临时 token + REST API

不讲的：

- 皮肤引擎 / 主题切换 → 装饰性，不是核心机制
- React 组件实现 → 前端开发教学
- OAuth 集成 → 生产接线
- 语音模式 UI → s18 范畴
- Rich 库的排版细节 → 查文档就行

## 这一章和其他章节的关系

- **s01** 的 `run_conversation()` → HermesCLI 包装了它，加了流式和进度回调
- **s02** 的工具系统 → 工具进度回调是 dispatch 的扩展
- **s09** 的权限系统 → 审批面板通过模态状态机接入 CLI
- **s11** 的配置系统 → Web 面板读写同一个 config.yaml
- **s12** 的 Gateway → Web 面板和 Gateway 适配器是同一层思路：不同入口，同一份数据
- **s15** 的定时任务 → Web 面板提供 cron API 管理 jobs.json

## 学完这章后，你应该能回答

- 为什么 `patch_stdout()` 是 prompt_toolkit TUI 的基础？不用它会怎样？
- `_stream_delta` 收到 `None` 意味着什么？为什么需要这个信号？
- 斜杠命令为什么要通过注册表分发，而不是直接 if-elif 匹配字符串？
- Web 面板为什么不做聊天功能？它和 CLI 是什么关系？
- 临时 token 为什么要用 `hmac.compare_digest` 比较？普通 `==` 有什么问题？

---

**一句话记住：CLI 用 prompt_toolkit 让输入区固定、输出流式渲染；Web 面板用 FastAPI 暴露管理 API。两者操作同一份数据，分工不同——CLI 做交互，Web 做管理。**
