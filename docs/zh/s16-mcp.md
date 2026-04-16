# s16: MCP Integration (外部工具协议)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > [ s16 ] > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *内置工具写在代码里，MCP 工具来自外部进程。但对 agent 来说，两种工具用起来一模一样。*

![MCP 客户端-服务端协议](../../illustrations/s16-mcp/01-framework-mcp-protocol.png)

## 这一章要解决什么问题

s02 讲的工具系统有一个前提：**工具是硬编码在代码里的。** 要加一个 GitHub 工具，就要写一个 `github_tool.py`，里面调 GitHub API，然后 `registry.register()`。

但如果社区已经有一个现成的 GitHub MCP 服务器，能列 issue、建 PR、搜代码——你只需要启动它，agent 就能用这些能力。不用写一行工具代码。

MCP（Model Context Protocol）就是干这个的：**一个标准协议，让外部进程把自己的能力暴露给 agent。**

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — 工具注册和分发机制，MCP 工具复用同一套
- [`s08-skill-system.md`](./s08-skill-system.md) — 工具 vs 技能 vs MCP 的区别

## 先解释几个名词

### 什么是 MCP

Model Context Protocol——一个开放协议，定义了"工具提供者"和"工具使用者"之间怎么通信。Hermes Agent 是使用者（MCP client），外部进程是提供者（MCP server）。

协议规定了三件事：
- 怎么发现工具（server 告诉 client "我有哪些工具"）
- 怎么调用工具（client 发请求，server 返回结果）
- 怎么传输（两种方式：stdio 管道 或 HTTP）

### 什么是 MCP server

一个独立的进程，通过 MCP 协议暴露一组工具。比如：

- `@modelcontextprotocol/server-github` — 提供 GitHub API 工具
- `@modelcontextprotocol/server-filesystem` — 提供文件系统工具
- 你自己写的 Python 脚本 — 只要实现 MCP 协议就行

### 什么是 stdio 传输和 HTTP 传输

MCP server 可以通过两种方式和 client 通信：

- **stdio**：Hermes 启动一个子进程（比如 `npx @modelcontextprotocol/server-github`），通过 stdin/stdout 管道通信。简单，本地跑。
- **HTTP**：MCP server 跑在远程，Hermes 通过 HTTP 请求通信。适合云服务和共享服务器。

## 从最笨的实现开始

你想让 agent 能用 GitHub API。最直接的做法：写一个内置工具。

```python
def handle_github_list_issues(args, **kwargs):
    import requests
    resp = requests.get(
        f"https://api.github.com/repos/{args['repo']}/issues",
        headers={"Authorization": f"token {GITHUB_TOKEN}"},
    )
    return json.dumps(resp.json()[:10])

registry.register(
    name="github_list_issues",
    toolset="github",
    schema={...},
    handler=handle_github_list_issues,
)
```

能用。但有三个问题。

### 问题一：每个 API 都要从头写

GitHub API 有几十个端点：列 issue、建 PR、搜代码、管 release……每个都要写 handler、定义 schema、处理错误、处理分页。而社区已经有人把这些全做好了，打包成一个 MCP server。

### 问题二：工具和 agent 绑死了

内置工具跑在 agent 进程里。如果工具依赖 Node.js（GitHub MCP server 是 Node 写的），你的 Python agent 还得装 Node 运行时。如果工具崩了，agent 跟着崩。

MCP server 跑在独立进程里。崩了不影响 agent，重启就好。

### 问题三：没有统一的发现机制

你今天接了 GitHub，明天接 Jira，后天接 Slack。每个都是不同的 API、不同的认证、不同的 schema 格式。没有统一的方式让 agent "发现"这些工具。

MCP 统一了这三件事：**发现（list_tools）、调用（call_tool）、传输（stdio / HTTP）。**

## 最小心智模型

```text
agent 启动时：

config.yaml 里配了两个 MCP server
    │
    v
Hermes 启动两个外部进程（或连接两个 HTTP 端点）
    │
    v
向每个 server 问："你有哪些工具？"  ← list_tools
    │
    v
把它们注册进 s02 的 registry ← 名字加前缀：mcp_github_list_issues
    │
    v
agent 看到的工具列表 = 内置工具 + MCP 工具（混在一起，没有区别）

agent 运行时：

agent 调用 mcp_github_list_issues(repo="...")
    │
    v
registry 找到 handler → handler 把请求转发给 GitHub MCP server
    │
    v
MCP server 调 GitHub API → 返回结果
    │
    v
handler 把结果返回给 agent（和内置工具一样的格式）
```

**对 agent 来说，MCP 工具和内置工具没有任何区别。** 它不知道也不需要知道 `mcp_github_list_issues` 背后是一个外部进程在调 GitHub API。

## 关键数据结构

### MCP server 配置

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  github:
    command: "npx"                              # stdio 传输
    args: ["@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    tools:
      include: [list_issues, create_issue, search_code]   # 只启用这三个

  analytics:
    url: "https://mcp.example.com/analytics"    # HTTP 传输
    headers:
      Authorization: "Bearer ${ANALYTICS_KEY}"
```

### 工具命名规则

MCP 工具注册到 registry 时，名字加 `mcp_<server名>_` 前缀：

```text
MCP server "github" 提供的工具 "list_issues"
  → 注册为 "mcp_github_list_issues"
  → toolset 为 "mcp-github"

MCP server "analytics" 提供的工具 "query"
  → 注册为 "mcp_analytics_query"
  → toolset 为 "mcp-analytics"
```

加前缀是为了**避免和内置工具撞名**。如果内置有 `read_file`，MCP server 也提供 `read_file`，注册为 `mcp_filesystem_read_file`——两个共存，互不影响。如果真的撞了（不带前缀的情况下），内置工具优先，MCP 工具被跳过。

## 最小实现

### 第一步：启动 MCP server 并发现工具

```python
import subprocess, json

def discover_mcp_tools(server_name: str, config: dict) -> list[dict]:
    """启动一个 MCP server，问它有哪些工具。"""

    # 启动子进程（stdio 传输）
    proc = subprocess.Popen(
        [config["command"]] + config.get("args", []),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=config.get("env", {}),
    )

    # MCP 协议：发 initialize 请求
    send_jsonrpc(proc.stdin, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "hermes-agent"},
    })
    read_jsonrpc(proc.stdout)  # 读 initialize 响应

    # 发 tools/list 请求
    send_jsonrpc(proc.stdin, "tools/list", {})
    result = read_jsonrpc(proc.stdout)

    return result["tools"]
    # → [{"name": "list_issues", "description": "...", "inputSchema": {...}}, ...]
```

实际的 Hermes Agent 用 MCP Python SDK（`from mcp import ClientSession`）而不是手动发 JSON-RPC，但底层做的事一样。

### 第二步：把 MCP 工具注册进 registry

```python
def register_mcp_tools(server_name: str, tools: list[dict], config: dict):
    """把 MCP server 的工具注册进 s02 的 registry。"""

    # 工具过滤
    include = config.get("tools", {}).get("include")
    exclude = config.get("tools", {}).get("exclude", [])

    for tool in tools:
        name = tool["name"]

        # 白名单 / 黑名单过滤
        if include and name not in include:
            continue
        if name in exclude:
            continue

        # 加前缀
        prefixed_name = f"mcp_{server_name}_{name}"

        # 检查是否和内置工具撞名
        if registry.has_tool(prefixed_name):
            print(f"  [mcp] {prefixed_name} collides with built-in, skipped")
            continue

        # 创建 handler：把调用转发给 MCP server
        handler = make_mcp_handler(server_name, name)

        registry.register(
            name=prefixed_name,
            toolset=f"mcp-{server_name}",
            schema={"name": prefixed_name, "description": tool["description"],
                    "parameters": tool["inputSchema"]},
            handler=handler,
        )
```

### 第三步：MCP 工具的 handler——转发调用

这是最关键的一步。registry 里的 handler 是同步函数，但 MCP 调用是异步的。需要一个桥接：

```python
# 全局：MCP 连接池
_servers: dict[str, MCPServerTask] = {}  # server_name → 连接对象

def make_mcp_handler(server_name: str, tool_name: str):
    """创建一个 handler，把调用转发给 MCP server。"""

    def handler(args: dict, **kwargs) -> str:
        server = _servers.get(server_name)
        if not server or not server.session:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})

        # 异步调用，同步等结果
        async def _call():
            result = await server.session.call_tool(tool_name, arguments=args)
            if result.isError:
                return json.dumps({"error": str(result.content)})
            text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
            return json.dumps({"result": text})

        return run_on_mcp_loop(_call())

    return handler
```

`run_on_mcp_loop()` 把异步协程调度到后台事件循环上执行，然后阻塞等结果：

```python
_mcp_loop: asyncio.AbstractEventLoop = None  # 后台事件循环

def run_on_mcp_loop(coro, timeout=30) -> str:
    """在后台事件循环上执行异步调用，同步等结果。"""
    future = asyncio.run_coroutine_threadsafe(coro, _mcp_loop)
    return future.result(timeout=timeout)
```

为什么需要后台事件循环？因为 MCP 连接是长驻的异步连接（stdio 管道或 HTTP 长连接）。它们跑在一个独立的后台线程上，和 agent 的同步主循环互不干扰。

### 完整流程走一遍

```text
1. agent 启动
   → 读 config.yaml，发现配了 github MCP server
   → 启动 npx @modelcontextprotocol/server-github 子进程
   → 发 tools/list → 拿到 [list_issues, create_issue, search_code]
   → 注册为 mcp_github_list_issues, mcp_github_create_issue, mcp_github_search_code

2. agent 运行中
   → 模型决定调用 mcp_github_list_issues(repo="hermes-agent")
   → registry 找到 handler → handler 通过 MCP 协议转发给 GitHub server
   → GitHub server 调 GitHub API → 返回 issue 列表
   → handler 把结果返回给 agent
   → agent 把 issue 列表展示给用户

3. agent 关闭
   → 向每个 MCP server 发 shutdown 信号
   → 等子进程退出（10 秒超时后强制 kill）
```

## 如何接到主循环里

MCP 工具和内置工具共用同一个 registry。核心循环不需要任何改动。

```text
核心循环
  │  tool_call: mcp_github_list_issues(repo="hermes-agent")
  v
registry.dispatch("mcp_github_list_issues", args)
  │  ← 和调内置工具用同一个 dispatch
  v
mcp handler → run_on_mcp_loop → server.session.call_tool
  │
  v
GitHub MCP server（外部进程）
  │  调 GitHub API → 返回结果
  v
handler 返回 json → registry → 核心循环
```

核心循环不知道这个工具来自外部进程。它只看到 registry.dispatch 返回了一段文本。

## 初学者最容易犯的错

### 1. 把 API key 传给了 MCP server 的环境变量

config.yaml 里配了 `env: { OPENAI_API_KEY: "..." }`——这把你的 LLM 密钥泄露给了外部进程。

**修：MCP server 的环境变量只传它需要的（如 `GITHUB_TOKEN`）。Hermes 默认只传安全的基础变量（PATH、HOME 等），用户显式配置的才会传。**

### 2. 不过滤工具，全部注册

一个 MCP server 可能暴露 50 个工具。全注册到 agent 里，模型的工具列表会很长，选择变难，token 消耗增大。

**修：用 `tools.include` 白名单只启用你需要的。**

### 3. MCP server 崩了不知道

stdio 子进程崩了，agent 调用时才发现连接断了，返回一个错误。

**修：Hermes 的 MCPServerTask 有自动重连逻辑——初始连接失败重试 3 次，运行中断线重试 5 次，指数退避。**

### 4. MCP 工具和内置工具撞名

MCP server 提供的 `read_file` 和内置的 `read_file` 撞了。

**修：MCP 工具自动加 `mcp_<server>_` 前缀。如果仍然撞了，内置工具优先，MCP 工具被跳过。**

## 教学边界

这一章只讲 Hermes Agent 作为 **MCP client**（使用外部工具）的部分。

讲三件事：

1. **MCP 工具怎么注册进 registry** — 发现 → 过滤 → 加前缀 → 注册 handler
2. **MCP 工具调用的完整链路** — handler → 后台事件循环 → MCP server → 结果
3. **同步/异步桥接** — registry 是同步的，MCP 是异步的，后台事件循环做桥

不讲的：

- Hermes 作为 MCP server（暴露消息能力给外部 client） → 是反方向的集成
- MCP 协议的 JSON-RPC 细节 → 用 SDK 就够，不需要手动拼 JSON
- OAuth 2.1 PKCE 认证流程 → HTTP 传输的增强
- sampling（MCP server 反过来请求 LLM 生成） → 高级特性
- MCP resources 和 prompts → 辅助能力，不影响工具调用的核心流程

## 这一章和后续章节的关系

- **s02** 定义了工具注册和分发机制 → MCP 工具复用同一套
- **s08** 的技能系统让 agent 可以创建/编辑能力 → MCP 是第三种能力来源：工具（代码）、技能（markdown）、MCP（外部进程）
- **s14** 的终端后端是把"命令在哪跑"抽象掉 → MCP 是把"工具在哪跑"抽象掉，都是同一种解耦思路

## 学完这章后，你应该能回答

- 内置工具和 MCP 工具对 agent 来说有区别吗？
- MCP server 的工具注册进 registry 后，名字变成了什么格式？为什么要加前缀？
- 如果一个 MCP server 提供了 50 个工具，你只想用其中 3 个，怎么配？
- registry 的 handler 是同步的，MCP 调用是异步的。Hermes 怎么解决这个矛盾？
- MCP server 崩了，agent 会跟着崩吗？为什么？

---

**一句话记住：MCP 让外部进程的工具注册进同一个 registry，agent 调用时和内置工具没有任何区别。**
