# s16: MCP Integration

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > [ s16 ] > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Built-in tools live in your codebase; MCP tools come from external processes. But to the agent, both kinds of tools are used in exactly the same way.*

![MCP Client-Server Protocol](../../illustrations/en/s16-mcp/01-framework-mcp-protocol.png)

## What problem does this chapter solve

The tool system from s02 has one prerequisite: **tools are hardcoded in the codebase.** To add a GitHub tool, you write a `github_tool.py` that calls the GitHub API, then `registry.register()`.

But if the community already has a ready-made GitHub MCP server that can list issues, create PRs, and search code -- you just start it, and the agent can use all those capabilities. No tool code required.

MCP (Model Context Protocol) is what makes this possible: **a standard protocol that lets external processes expose their capabilities to an agent.**

## Suggested reading

- [`s02-tool-system.md`](./s02-tool-system.md) -- tool registration and dispatch; MCP tools reuse the same system
- [`s08-skill-system.md`](./s08-skill-system.md) -- tools vs. skills vs. MCP: understanding the differences

## Key terms

### What is MCP

Model Context Protocol -- an open protocol that defines how "tool providers" and "tool consumers" communicate. Hermes Agent is the consumer (MCP client); external processes are the providers (MCP servers).

The protocol specifies three things:
- How to discover tools (the server tells the client "here are the tools I have")
- How to invoke tools (the client sends a request, the server returns a result)
- How to transport messages (two options: stdio pipes or HTTP)

### What is an MCP server

An independent process that exposes a set of tools via the MCP protocol. For example:

- `@modelcontextprotocol/server-github` -- provides GitHub API tools
- `@modelcontextprotocol/server-filesystem` -- provides file system tools
- A Python script you wrote yourself -- as long as it implements the MCP protocol

### What are stdio transport and HTTP transport

An MCP server can communicate with a client in two ways:

- **stdio**: Hermes starts a subprocess (e.g., `npx @modelcontextprotocol/server-github`) and communicates via stdin/stdout pipes. Simple, runs locally.
- **HTTP**: The MCP server runs remotely; Hermes communicates via HTTP requests. Suitable for cloud services and shared servers.

## Starting with the simplest implementation

You want the agent to use the GitHub API. The most direct approach: write a built-in tool.

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

This works. But there are three problems.

### Problem 1: You have to build every API from scratch

The GitHub API has dozens of endpoints: list issues, create PRs, search code, manage releases... Each one requires writing a handler, defining a schema, handling errors, handling pagination. Meanwhile, the community has already done all of this, packaged as an MCP server.

### Problem 2: Tools are tightly coupled to the agent

Built-in tools run inside the agent process. If a tool depends on Node.js (the GitHub MCP server is written in Node), your Python agent also needs the Node runtime installed. If the tool crashes, the agent crashes with it.

An MCP server runs in its own process. If it crashes, the agent is unaffected -- just restart it.

### Problem 3: No unified discovery mechanism

Today you integrate GitHub, tomorrow Jira, next day Slack. Each has a different API, different authentication, different schema format. There is no uniform way for the agent to "discover" these tools.

MCP unifies all three concerns: **discovery (list_tools), invocation (call_tool), and transport (stdio / HTTP).**

## Minimal mental model

```text
At agent startup:

config.yaml has two MCP servers configured
    |
    v
Hermes starts two external processes (or connects to two HTTP endpoints)
    |
    v
Asks each server: "What tools do you have?"  <- list_tools
    |
    v
Registers them in s02's registry <- names prefixed: mcp_github_list_issues
    |
    v
The tool list the agent sees = built-in tools + MCP tools (mixed together, no distinction)

At runtime:

The agent calls mcp_github_list_issues(repo="...")
    |
    v
The registry finds the handler -> handler forwards the request to the GitHub MCP server
    |
    v
The MCP server calls the GitHub API -> returns the result
    |
    v
The handler returns the result to the agent (same format as built-in tools)
```

**To the agent, there is no difference between MCP tools and built-in tools.** It doesn't know -- and doesn't need to know -- that `mcp_github_list_issues` is backed by an external process calling the GitHub API.

## Key data structures

### MCP server configuration

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  github:
    command: "npx"                              # stdio transport
    args: ["@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    tools:
      include: [list_issues, create_issue, search_code]   # Only enable these three

  analytics:
    url: "https://mcp.example.com/analytics"    # HTTP transport
    headers:
      Authorization: "Bearer ${ANALYTICS_KEY}"
```

### Tool naming convention

When MCP tools are registered in the registry, their names are prefixed with `mcp_<server_name>_`:

```text
MCP server "github" provides a tool "list_issues"
  -> registered as "mcp_github_list_issues"
  -> toolset is "mcp-github"

MCP server "analytics" provides a tool "query"
  -> registered as "mcp_analytics_query"
  -> toolset is "mcp-analytics"
```

The prefix exists to **avoid name collisions with built-in tools**. If there's a built-in `read_file` and an MCP server also provides `read_file`, it gets registered as `mcp_filesystem_read_file` -- both coexist without interference. If there is a genuine collision (without the prefix), the built-in tool takes priority and the MCP tool is skipped.

## Minimal implementation

### Step 1: Start the MCP server and discover tools

```python
import subprocess, json

def discover_mcp_tools(server_name: str, config: dict) -> list[dict]:
    """Start an MCP server and ask it what tools it has."""

    # Start subprocess (stdio transport)
    proc = subprocess.Popen(
        [config["command"]] + config.get("args", []),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=config.get("env", {}),
    )

    # MCP protocol: send initialize request
    send_jsonrpc(proc.stdin, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "hermes-agent"},
    })
    read_jsonrpc(proc.stdout)  # Read initialize response

    # Send tools/list request
    send_jsonrpc(proc.stdin, "tools/list", {})
    result = read_jsonrpc(proc.stdout)

    return result["tools"]
    # -> [{"name": "list_issues", "description": "...", "inputSchema": {...}}, ...]
```

The actual Hermes Agent uses the MCP Python SDK (`from mcp import ClientSession`) rather than sending JSON-RPC manually, but the underlying work is the same.

### Step 2: Register MCP tools in the registry

```python
def register_mcp_tools(server_name: str, tools: list[dict], config: dict):
    """Register an MCP server's tools in s02's registry."""

    # Tool filtering
    include = config.get("tools", {}).get("include")
    exclude = config.get("tools", {}).get("exclude", [])

    for tool in tools:
        name = tool["name"]

        # Allowlist / blocklist filtering
        if include and name not in include:
            continue
        if name in exclude:
            continue

        # Add prefix
        prefixed_name = f"mcp_{server_name}_{name}"

        # Check for collision with built-in tools
        if registry.has_tool(prefixed_name):
            print(f"  [mcp] {prefixed_name} collides with built-in, skipped")
            continue

        # Create handler: forward calls to the MCP server
        handler = make_mcp_handler(server_name, name)

        registry.register(
            name=prefixed_name,
            toolset=f"mcp-{server_name}",
            schema={"name": prefixed_name, "description": tool["description"],
                    "parameters": tool["inputSchema"]},
            handler=handler,
        )
```

### Step 3: The MCP tool handler -- forwarding calls

This is the most critical step. The handler in the registry is a synchronous function, but MCP calls are asynchronous. A bridge is needed:

```python
# Global: MCP connection pool
_servers: dict[str, MCPServerTask] = {}  # server_name -> connection object

def make_mcp_handler(server_name: str, tool_name: str):
    """Create a handler that forwards calls to the MCP server."""

    def handler(args: dict, **kwargs) -> str:
        server = _servers.get(server_name)
        if not server or not server.session:
            return json.dumps({"error": f"MCP server '{server_name}' not connected"})

        # Async call, wait synchronously for the result
        async def _call():
            result = await server.session.call_tool(tool_name, arguments=args)
            if result.isError:
                return json.dumps({"error": str(result.content)})
            text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
            return json.dumps({"result": text})

        return run_on_mcp_loop(_call())

    return handler
```

`run_on_mcp_loop()` schedules the async coroutine onto a background event loop and blocks until the result is ready:

```python
_mcp_loop: asyncio.AbstractEventLoop = None  # Background event loop

def run_on_mcp_loop(coro, timeout=30) -> str:
    """Execute an async call on the background event loop, waiting synchronously for the result."""
    future = asyncio.run_coroutine_threadsafe(coro, _mcp_loop)
    return future.result(timeout=timeout)
```

Why a background event loop? Because MCP connections are long-lived async connections (stdio pipes or persistent HTTP connections). They run on a dedicated background thread, independent of the agent's synchronous main loop.

### Full flow walkthrough

```text
1. Agent starts up
   -> Reads config.yaml, finds a github MCP server configured
   -> Starts npx @modelcontextprotocol/server-github subprocess
   -> Sends tools/list -> gets [list_issues, create_issue, search_code]
   -> Registers as mcp_github_list_issues, mcp_github_create_issue, mcp_github_search_code

2. Agent is running
   -> The model decides to call mcp_github_list_issues(repo="hermes-agent")
   -> The registry finds the handler -> handler forwards via MCP protocol to the GitHub server
   -> The GitHub server calls the GitHub API -> returns the issue list
   -> The handler returns the result to the agent
   -> The agent presents the issue list to the user

3. Agent shuts down
   -> Sends a shutdown signal to each MCP server
   -> Waits for subprocesses to exit (force kill after 10-second timeout)
```

## How it plugs into the main loop

MCP tools and built-in tools share the same registry. The core loop requires no changes.

```text
Core loop
  |  tool_call: mcp_github_list_issues(repo="hermes-agent")
  v
registry.dispatch("mcp_github_list_issues", args)
  |  <- same dispatch as calling a built-in tool
  v
mcp handler -> run_on_mcp_loop -> server.session.call_tool
  |
  v
GitHub MCP server (external process)
  |  Calls GitHub API -> returns result
  v
handler returns json -> registry -> core loop
```

The core loop has no idea this tool comes from an external process. All it sees is that registry.dispatch returned a string.

## Common beginner mistakes

### 1. Passing API keys in MCP server environment variables

You configured `env: { OPENAI_API_KEY: "..." }` in config.yaml -- this leaks your LLM key to an external process.

**Fix: Only pass the environment variables the MCP server actually needs (e.g., `GITHUB_TOKEN`). Hermes passes only safe base variables (PATH, HOME, etc.) by default; only user-configured variables are forwarded.**

### 2. Registering all tools without filtering

A single MCP server might expose 50 tools. Registering them all gives the model a very long tool list, making selection harder and increasing token consumption.

**Fix: Use `tools.include` as an allowlist to enable only the ones you need.**

### 3. Not noticing when an MCP server crashes

If the stdio subprocess crashes, the agent only discovers the broken connection when it tries to make a call, returning an error.

**Fix: Hermes's MCPServerTask has automatic reconnection logic -- 3 retries on initial connection failure, 5 retries for mid-run disconnections, with exponential backoff.**

### 4. Name collision between MCP tools and built-in tools

An MCP server provides a `read_file` that collides with the built-in `read_file`.

**Fix: MCP tools are automatically prefixed with `mcp_<server>_`. If a collision still occurs, the built-in tool takes priority and the MCP tool is skipped.**

## Scope of this chapter

This chapter only covers Hermes Agent as an **MCP client** (consuming external tools).

It covers three things:

1. **How MCP tools are registered in the registry** -- discover -> filter -> prefix -> register handler
2. **The full call chain for MCP tool invocation** -- handler -> background event loop -> MCP server -> result
3. **Sync/async bridging** -- the registry is synchronous, MCP is asynchronous, and the background event loop bridges the two

Not covered:

- Hermes as an MCP server (exposing messaging capabilities to external clients) -> the reverse integration direction
- JSON-RPC details of the MCP protocol -> the SDK handles it; no need to manually construct JSON
- OAuth 2.1 PKCE authentication flow -> an enhancement for HTTP transport
- Sampling (MCP server requesting LLM generation in reverse) -> advanced feature
- MCP resources and prompts -> auxiliary capabilities that don't affect the core tool invocation flow

## How this chapter relates to others

- **s02** defines tool registration and dispatch -> MCP tools reuse the same system
- **s08**'s skill system lets the agent create/edit capabilities -> MCP is a third capability source: tools (code), skills (markdown), MCP (external processes)
- **s14**'s terminal backend abstracts away "where commands run" -> MCP abstracts away "where tools run" -- the same decoupling approach

## After finishing this chapter, you should be able to answer

- Is there any difference between a built-in tool and an MCP tool from the agent's perspective?
- After an MCP server's tool is registered in the registry, what does its name look like? Why the prefix?
- If an MCP server provides 50 tools but you only want 3, how do you configure it?
- The registry handler is synchronous, but MCP calls are asynchronous. How does Hermes resolve this mismatch?
- If an MCP server crashes, will the agent crash too? Why or why not?

---

**One sentence to remember: MCP lets tools from external processes register in the same registry, and the agent calls them with zero distinction from built-in tools.**
