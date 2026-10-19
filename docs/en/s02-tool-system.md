# s02: Tool System

`s00 > s01 > [ s02 ] > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *"Adding a tool means adding a single file"* -- no changes to the loop, the registry, or the orchestration layer.
>
> **Harness layer**: Tool registration and dispatch -- enabling 50+ tools and MCP external tools to coexist without interfering with each other.

## The Problem

In the s01 loop, `run_tool()` is a black box. The most intuitive implementation is an if/elif chain, but Hermes Agent has 50+ built-in tools, plus MCP external tools that can join dynamically. If every new tool requires modifying the dispatch code, the system will quickly spiral out of control.

Key insight: adding a tool should not require changing the loop or any central configuration file.

## The Solution

![Tool System Import Chain](../../illustrations/en/s02-tool-system/01-framework-import-chain.png)

Hermes Agent splits the tool system into three layers, connected by an import chain:

```
registry.py          (imports no tools)
     ^
tools/*.py           (imports registry, registers itself)
     ^
model_tools.py       (imports all tools/*.py, triggering registration)
     ^
run_agent.py         (imports model_tools.py, uses the interface)

The registry sits at the bottom and depends on no tools.
This is the key to making the whole design work.
```

## How It Works

### 1. Tool Files Self-Register

Each tool file calls `register()` at the end:

```python
# tools/web_tools.py
from tools.registry import registry

def handle_web_search(args, **kwargs):
    query = args.get("query", "")
    # ... perform search ...
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

### 2. The Orchestration Layer Triggers Discovery

The orchestration layer's purpose is to bring all tools online automatically, without manual one-by-one configuration.

It leverages a fundamental Python rule: **when a module is imported, its top-level code executes immediately.** The `registry.register(...)` call at the end of each tool file is top-level code -- as soon as the module is imported, registration happens automatically.

All the orchestration layer needs to do is import every tool module:

```python
# model_tools.py
from tools.registry import registry

_modules = [
    "tools.web_tools",       # import -> register() at the end executes -> web_search registered
    "tools.terminal_tool",   # import -> register() executes -> terminal registered
    "tools.file_tools",      # import -> register() executes -> read_file, write_file registered
    "tools.vision_tools",
    "tools.skills_tool",
    "tools.memory_tool",
    # ... 20+ modules
]
for mod in _modules:
    importlib.import_module(mod)

# MCP external tools are also discovered and registered here
from tools.mcp_tool import discover_mcp_tools
discover_mcp_tools()
```

`importlib.import_module("tools.web_tools")` has the same effect as writing `import tools.web_tools` directly, except the module name can be a string variable -- so it can be placed in a list and imported in a loop. Adding a new tool only requires adding one string to the list.

![Tool Registration and Dispatch](../../illustrations/en/s02-tool-system/02-flowchart-dispatch.png)

The overall flow:

```text
model_tools.py starts
  -> import tools.web_tools    -> register("web_search") executes automatically
  -> import tools.terminal_tool -> register("terminal")  executes automatically
  -> import tools.file_tools   -> register("read_file")  executes automatically
  -> ...
  -> discover_mcp_tools()      -> external MCP tools are also registered

Result: the registry now contains 50+ tools, and dispatch("web_search") in the loop can find it
```

### 3. The Registry Dispatches Execution

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

The `is_async` flag is a design unique to Hermes. The core loop is synchronous, but tools like network requests and browser operations are async. When the registry sees the flag, it automatically routes through the async bridge. Neither the tool files nor the core loop need to worry about this detail.

### 4. Async Bridge

```python
# model_tools.py
def _run_async(coro):
    # Don't use asyncio.run() -- it creates a new loop then closes it,
    # breaking cached httpx clients
    # Use a persistent event loop instead
    tool_loop = _get_tool_loop()
    return tool_loop.run_until_complete(coro)
```

Why not just use `asyncio.run()`? Because it creates a new loop each time and then closes it. Tools that internally cache httpx / AsyncOpenAI clients bind to the old loop -- once the loop is closed, those clients become unusable. A persistent loop keeps the client caches valid.

### 5. Toolset Toggles and Availability Checks

```python
# Specify a check_fn at registration time
registry.register(
    name="browser_navigate",
    toolset="browser",
    check_fn=lambda: bool(os.environ.get("BROWSERBASE_API_KEY")),
    # ...
)

# get_definitions() only returns tools whose check_fn passes
# No API key -> this tool won't appear in the schema list sent to the model
```

## Changes Relative to s01

| Component | Before (s01) | After (s02) |
|---|---|---|
| Tools | `run_tool` black box | Registry -> orchestration layer -> dispatch |
| Adding a new tool | Requires changing the loop | Just add one file |
| Async tools | Not supported | `is_async` flag + persistent event loop bridge |
| Tool filtering | None | Toolset toggles + check_fn availability checks |
| MCP external tools | None | Discovered by the orchestration layer and registered into the same registry |
| Core loop | Unchanged | Unchanged |

## Try It Out

```sh
cd learn-hermes-agent
python agents/s02_tool_system.py
```

Try these prompts:

1. `Search for what's new in Python 3.12` -- routes to the web_search tool
2. `Read requirements.txt` -- routes to the read_file tool
3. `Run ls -la in the terminal` -- routes to the terminal tool
4. `Create a hello.py file` -- routes to the write_file tool

Notice: you did not change the loop code, yet four different tools all work correctly.

## When You Start Sensing "Tools Are More Than Registration + Dispatch"

Up to this point, the tool system has been presented as:

- schema (the instruction manual for the model)
- handler (the function that actually executes)
- dispatch (look up by name and call)

That is correct, and you need to learn it this way first.

But as the system grows, you will find that tool execution sprouts pre- and post-processing: permission checks (`s09`), MCP external tool bridging (`s16`), result size limits, and parallel execution strategies. These are expanded in later chapters.

## Teaching Boundary

This chapter drives home three things:

1. **Self-registration pattern** -- tool files register themselves; the orchestration layer just imports them
2. **Import chain** -- registry <- tools <- model_tools <- run_agent; never in reverse
3. **Async bridge** -- `is_async` flag + persistent event loop

Deliberately left out: permissions (`s09`), MCP (`s16`), the relationship between skills and tools (`s08`).

Adding a tool means adding a single file -- if you can do that, you have completed this chapter.
