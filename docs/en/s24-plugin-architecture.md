# s24: Plugin Architecture

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > [ s24 ] > s25 > s26 > s27`

> *The built-in memory uses files, but some people want Honcho for user modeling, others want mem0 for semantic search. The plugin system lets everyone use what they prefer without changing a single line of core code.*

![Plugin Architecture](../../illustrations/en/s24-plugin-architecture/01-framework-plugin-interface.png)

## What Problem Does This Chapter Solve

The built-in memory system from s07 uses MEMORY.md and USER.md files for storage. It works, but has limitations:

- Only exact-match lookup, no semantic search ("that bug I mentioned last week" won't be found)
- No user modeling (doesn't know "this person prefers what style" or "what projects this person has worked on before")
- Data is stored in local files and can't sync across devices

The community has many dedicated memory services -- Honcho (user profiling + conversational memory), mem0 (semantic search + fact extraction), holographic (local knowledge graph). Each has its own API and data model.

If you hardcode Honcho into `memory_manager.py`, anyone who wants to switch to mem0 has to modify core code. Doing this for every memory service quickly leads to chaos.

**What's needed is a plugin interface: define "what a memory provider must do," let each service implement it on its own, and switch via configuration.**

This problem isn't unique to memory. Context compression strategies (s05) have a similar need -- the built-in summary compression works, but some people want smarter strategies. That's why Hermes Agent has three independent plugin systems.

## Suggested Reading

- [`s07-memory-system.md`](./s07-memory-system.md) -- The built-in memory system (MEMORY.md / USER.md)
- [`s05-context-compression.md`](./s05-context-compression.md) -- Built-in context compression
- [`s16-mcp.md`](./s16-mcp.md) -- MCP is another way to extend capabilities, but targets tools rather than memory

## Key Concepts

### What Is a MemoryProvider

A unified interface for external memory services. Each provider (Honcho, mem0, etc.) implements this interface and can be plugged into Hermes Agent.

Core constraint: **only one external MemoryProvider can be active at a time.** Built-in memory (MEMORY.md) is always online; the external provider is an optional enhancement.

### What Is a ContextEngine

A unified interface for context compression strategies. The built-in ContextCompressor (the summary compression covered in s05) is the default implementation. You can replace it with another strategy -- again, only one active at a time.

### What Is the MemoryManager

The coordinator. It manages the coexistence of built-in memory and the external provider -- who provides tools, who handles prefetch, who handles sync.

## Starting from the Simplest Approach

Hardcode Honcho directly into the memory management code:

```python
# memory_manager.py
def prefetch(query):
    # Built-in memory
    memory_text = load_memory(MEMORY_FILE)

    # Honcho
    if HONCHO_ENABLED:
        from honcho import HonchoClient
        client = HonchoClient(api_key=HONCHO_KEY)
        honcho_context = client.recall(query)
        return memory_text + "\n" + honcho_context

    return memory_text
```

Two problems:

### Problem 1: Core Code Changes for Every New Service

Added Honcho, now need to add mem0. Then holographic. Each one has different initialization, prefetch, sync, and tool registration -- all crammed into memory_manager.py. This is the same problem as the if-else platform adapters from s12.

### Problem 2: Two External Services Active Simultaneously Will Conflict

Both Honcho and mem0 want to prefetch context before each conversation turn, and both want to register their own tools. Activating them simultaneously could cause interference. But you can't simply forbid it -- some scenarios genuinely require switching.

**Solution: Define a MemoryProvider interface + one rule (only one external provider at a time).**

## Minimal Mental Model

```text
Built-in memory (always on)          External provider (optional, at most one)
 MEMORY.md / USER.md                  Honcho / mem0 / holographic
       |                                    |
       v                                    v
┌──────────────────────────────────────────────┐
│ MemoryManager (coordinator)                   │
│                                               │
│  Before each conversation turn:               │
│    prefetch_all(query)                        │
│    -> built-in: load MEMORY.md                │
│    -> external: call provider.prefetch(query) │
│    -> merge context and inject into messages  │
│                                               │
│  After each conversation turn:                │
│    sync_all(user_msg, assistant_msg)          │
│    -> built-in: may write to MEMORY.md        │
│    -> external: call provider.sync_turn(...)  │
│                                               │
│  Tool routing:                                │
│    built-in tool: memory(action="add", ...)   │
│    external tool: honcho_search(query="...")   │
│    -> route to the correct provider by name   │
└──────────────────────────────────────────────┘
```

## The MemoryProvider Interface

Methods that an external memory provider must implement:

```python
class MemoryProvider(ABC):
    # --- Required ---

    @property
    def name(self) -> str:
        """Short identifier, e.g. 'honcho', 'mem0'."""
        ...

    def is_available(self) -> bool:
        """Check availability (no network requests -- only check config and dependencies)."""
        ...

    def initialize(self, session_id: str, **kwargs):
        """Initialize at session start (create connections, load state)."""
        ...

    def get_tool_schemas(self) -> list[dict]:
        """Return the list of tools this provider exposes to the model."""
        ...

    # --- Optional (have default empty implementations) ---

    def prefetch(self, query: str) -> str:
        """Recall relevant context before each conversation turn. Must be fast (can use background thread prefetch)."""
        return ""

    def sync_turn(self, user_content: str, assistant_content: str):
        """Persist after each conversation turn. Should be non-blocking (queue to background)."""
        pass

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """Execute the provider's own tool calls."""
        return "{}"

    def shutdown(self):
        """Close connections, flush queues."""
        pass
```

4 required methods + 4 optional methods. The same approach as s14's BaseEnvironment (2 methods) and s13's BasePlatformAdapter (3 methods) -- define an interface, and let implementors focus solely on their own logic.

## How the MemoryManager Coordinates

```python
class MemoryManager:
    def __init__(self):
        self._providers: list[MemoryProvider] = []
        self._has_external = False
        self._tool_to_provider: dict[str, MemoryProvider] = {}

    def add_provider(self, provider: MemoryProvider):
        """Register a provider. At most one external provider."""
        if provider.name != "builtin":
            if self._has_external:
                print(f"  [memory] external provider already active, rejecting {provider.name}")
                return
            self._has_external = True

        self._providers.append(provider)

        # Index tool name -> provider for routing
        for schema in provider.get_tool_schemas():
            self._tool_to_provider[schema["name"]] = provider

    def prefetch_all(self, query: str) -> str:
        """Before each conversation turn, recall context from all providers."""
        parts = []
        for provider in self._providers:
            try:
                context = provider.prefetch(query)
                if context:
                    parts.append(f"[{provider.name}] {context}")
            except Exception as exc:
                pass  # One provider failing doesn't affect the others
        return "\n".join(parts)

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """Route to the correct provider by tool name."""
        provider = self._tool_to_provider.get(tool_name)
        if not provider:
            return json.dumps({"error": f"Unknown memory tool: {tool_name}"})
        return provider.handle_tool_call(tool_name, args)
```

Key design: **one provider failing doesn't affect the others.** prefetch, sync, and tool calls are all wrapped in try/except. If the Honcho service goes down, built-in memory keeps working.

## Full Flow Walkthrough with Honcho

```text
1. Configuration
   config.yaml: memory.provider = "honcho"

2. Startup
   -> load_memory_provider("honcho")
   -> Find plugins/memory/honcho/__init__.py
   -> Call register(ctx) -> create HonchoMemoryProvider instance
   -> provider.is_available() -> check that SDK is installed, API key is set
   -> manager.add_provider(provider)
   -> manager.initialize_all(session_id="...")

3. Before each conversation turn (prefetch)
   User says "Did that bug I mentioned last week get fixed?"
   -> manager.prefetch_all("Did that bug I mentioned last week get fixed?")
     -> Built-in: load MEMORY.md (may not have relevant information)
     -> Honcho: semantic search -> "Last week user mentioned #1234 null pointer bug, not yet fixed"
   -> Merged and injected into messages:
     <memory-context>
     [honcho] Last week user mentioned #1234 null pointer bug, not yet fixed
     </memory-context>
   -> Model sees the context, can respond "That bug was #1234, let me check on it"

4. Model calls a Honcho tool
   -> tool_call: honcho_search(query="null pointer bug")
   -> manager.handle_tool_call("honcho_search", ...) -> routes to Honcho provider
   -> Honcho returns search results

5. After each conversation turn (sync)
   -> manager.sync_all("Did that bug I mentioned...", "That bug was #1234, it's been fixed")
     -> Built-in: check whether MEMORY.md needs updating
     -> Honcho: store this conversation turn in Honcho backend (non-blocking, queued to background thread)

6. Shutdown
   -> manager.shutdown_all()
   -> Honcho: flush queue, close connections
```

**What if you switch to mem0?** Change one line in `config.yaml`: `memory.provider = "mem0"`. No changes to core code.

## How Plugins Are Discovered and Loaded

```text
plugins/memory/                      <- Providers bundled with the repo
  ├── honcho/
  │   ├── __init__.py               <- register(ctx) function
  │   └── plugin.yaml               <- Metadata (name, description)
  ├── mem0/
  ├── holographic/
  └── ...

~/.hermes/plugins/                   <- User-installed plugins
  └── my-memory/
      ├── __init__.py
      └── plugin.yaml
```

Loading order: bundled providers take priority; in case of name conflicts, bundled ones win.

Every plugin's `__init__.py` must have a `register(ctx)` function:

```python
# plugins/memory/honcho/__init__.py

def register(ctx):
    ctx.register_memory_provider(HonchoMemoryProvider())
```

`ctx` is a collector object that the loader uses to gather provider instances. This pattern means the plugin doesn't need to know about MemoryManager -- it just registers itself.

## How It Plugs into the Main Loop

The MemoryManager intervenes at two points in the core loop:

```text
Each turn of the core loop:

  1. User message arrives
       |
       v
  2. manager.prefetch_all(user_message)  <- before turn: recall context
       |  inject into messages
       v
  3. Send to model -> model responds
       |
       |-- if tool_call is a memory tool -> manager.handle_tool_call(...)
       |
       v
  4. manager.sync_all(user_msg, assistant_msg)  <- after turn: persist
       |
       v
  5. Next turn
```

The core loop only calls three methods on the manager (prefetch_all, handle_tool_call, sync_all). It neither knows nor cares which provider is behind the scenes.

## Common Beginner Mistakes

### 1. Activating Two External Providers Simultaneously

"I want to use Honcho's user modeling and mem0's semantic search at the same time" -- MemoryManager will reject the second one.

**Fix: Choose one. If you need multiple capabilities, pick the most comprehensive provider, or wait for the community to develop a combined solution.**

### 2. Slow Network Requests in prefetch Making Every Turn Lag

prefetch runs after the user message arrives but before it's sent to the model. If the Honcho API is 2 seconds slow, every conversation turn gains an extra 2-second wait.

**Fix: Use background thread prefetch. Honcho's implementation calls `queue_prefetch()` at the end of each turn to prefetch context for the next turn, so the next `prefetch()` call reads directly from cache.**

### 3. Provider Exceptions Crashing the Conversation

Honcho's API goes down, prefetch throws an exception.

**Fix: MemoryManager wraps every provider call in try/except. One going down doesn't affect the others.**

### 4. Not Understanding "Built-in Is Always On"

Assuming that configuring Honcho means MEMORY.md is no longer used. In reality, built-in memory always works; Honcho is an additional enhancement. Tools and context from both are merged.

## Teaching Boundaries

This chapter covers the most central of Hermes Agent's three plugin systems: memory providers.

Three things covered:

1. **The MemoryProvider interface** -- 4 required methods + 4 optional methods
2. **How the MemoryManager coordinates** -- prefetch, sync, tool routing, single external provider limit
3. **How plugins are discovered and loaded** -- Directory scanning + `register(ctx)` pattern

Not covered:

- ContextEngine (context compression strategy plugin) -> same pattern as MemoryProvider, just a different interface
- General plugin system (hooks, CLI commands) -> broader extension mechanisms
- Internal implementation of each memory provider -> their respective API docs
- Plugin security scanning -> security mechanism

## How This Chapter Relates to Others

- **s07** defined built-in memory -> this chapter lets external services enhance it
- **s05** defined built-in compression -> ContextEngine plugins let external strategies replace it (same pattern)
- **s16**'s MCP extends tool capabilities -> this chapter extends memory capabilities; both are "adding functionality without changing core code"
- **s02**'s tool self-registration -> the plugin's `register(ctx)` follows the same registration pattern

## After This Chapter, You Should Be Able to Answer

- What is the relationship between built-in memory and external providers? Does MEMORY.md still work after configuring Honcho?
- Why can only one external memory provider be active at a time?
- Why must MemoryProvider's `prefetch` be fast? What if the API is slow?
- If Honcho's API goes down, can the agent still have normal conversations?
- How many lines of core code need to change to switch from Honcho to mem0?

---

**One-liner: Define interfaces, load by configuration, route through a coordinator -- switch memory backends without changing a single line of core code.**
