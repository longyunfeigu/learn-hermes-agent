# s00: Architecture Overview

> This chapter is the map for the entire repository.  
> If all you want to know right now is "what modules make up the system and why should I learn them in this order," start here.

## How Hermes Agent Differs from Other Agent Tutorials

Most agent tutorials teach you to build "one person chatting with an AI in a terminal."

Hermes Agent is different. From day one it was designed as a **cross-platform autonomous agent**:

- The same core loop can power a terminal conversation and simultaneously serve Telegram, Discord, WeChat, Lark, and a dozen other platforms
- Terminal commands don't have to run locally -- they can execute in Docker, over SSH on a remote machine, or in the cloud
- The agent can create and edit its own skill files, not just use predefined tools
- Every 10 turns the agent automatically forks a background copy to review the conversation, updating memory and skills on its own -- **a closed-loop self-evolution system**
- All conversations are persisted to SQLite with full-text search; nothing is lost on restart
- No vendor lock-in: 200+ models are supported through the OpenAI-compatible API interface
- A complete trajectory collection and RL training pipeline -- conversation history can be used directly to train the next-generation model

These are not features bolted on after the fact. They shaped the core design from the very beginning.

So when you study this system, you are not looking at "a simple loop plus a bag of tools." You are looking at a platform architecture with clear layering.

## What This Repository Reconstructs

What this repository truly aims to reconstruct is:

- What the core layers of Hermes Agent are
- Why each layer exists
- What happens between the moment a user sends a message and the moment the agent replies
- Where the critical state lives
- Which design decisions enable it to serve multiple platforms at once

Our goal:

**Reconstruct the design decisions and architectural layering unique to Hermes Agent, rather than deliver generic agent tutorials.**

## Three Reading Principles

### 1. Start with CLI, Then Move to Gateway

Hermes Agent has two entry points: the interactive terminal (CLI) and the multi-platform gateway (Gateway).

You don't need to learn both at once. Phases 1 and 2 cover only the CLI entry point. Gateway is not introduced until Phase 3.

This works because CLI and Gateway ultimately call the same core loop. Master the core loop first, and plugging in multiple platforms later is just "swapping the message source."

### 2. Start with Local Execution, Then Move to Multiple Backends

Same logic. Terminal commands can run in Docker, over SSH, or in the cloud, but Phase 1 covers only local execution.

Once you understand the full path through the tool system, adding execution-environment abstraction is just "swapping where the command runs."

### 3. Build the Minimal Version First; Stop at the Teaching Boundary

Every chapter starts with a minimal but correct implementation, then tells you "what you would add if you kept iterating."

Don't try to absorb all the complexity in one pass.

![Hermes Agent Five-Layer Architecture](../../illustrations/en/s00-architecture/01-framework-five-layers.png)

## The Five-Layer Architecture of Hermes Agent

This is what sets Hermes Agent apart from most agent tutorials: it is not "one loop + a bag of tools" but a system with five distinct layers.

```text
+-------------------------------------+
| Entry Layer                         |
| Where does the user come from?      |
| CLI / Telegram / Discord / WeChat / ... |
+----------------+--------------------+
                 |
                 v
+-------------------------------------+
| Core Loop Layer                     |
| Model thinks -> call tools ->       |
| write results back -> continue      |
| Synchronous loop; async tools       |
| bridged via an event loop           |
+----------------+--------------------+
                 |
                 v
+-------------------------------------+
| Tool & Intelligence Layer           |
| Self-registering tools / memory /   |
| skills / approval gates             |
| Adding a tool never touches the     |
| core loop                           |
+----------------+--------------------+
                 |
                 v
+-------------------------------------+
| Execution Environment Layer         |
| Where do commands run?              |
| Local / Docker / SSH / Cloud        |
+----------------+--------------------+
                 |
                 v
+-------------------------------------+
| Persistence Layer                   |
| SQLite sessions / MEMORY.md /       |
| skill files                         |
| Conversations and knowledge survive |
| across restarts                     |
+-------------------------------------+
```

### Why These Five Layers

**Entry Layer**: Most agents have a single terminal entry point. Hermes Agent has two -- CLI and Gateway. Inside the Gateway there are over a dozen platform adapters. The entry layer's job is to normalize messages from different sources into a unified format and hand them to the core loop.

**Core Loop Layer**: This is the heart of the system. No matter where a message comes from, it enters the same loop: send to model -> process tool calls -> write results back -> continue. The loop is synchronous. Async tools (such as network requests) are bridged in through a persistent event loop rather than making the entire loop async.

**Tool & Intelligence Layer**: Tools are not function calls scattered across the codebase. They form a self-registration system -- each tool file automatically registers itself on import. Memory, skills, and dangerous-command approval also live in this layer. They don't modify the core loop's code; instead, they insert logic before and after tool calls.

**Execution Environment Layer**: Terminal commands don't have to run locally. Hermes Agent abstracts an execution-environment interface with six implementations: local, Docker, SSH, Modal, Daytona, and Singularity. Upper-layer tools don't need to know where a command runs.

**Persistence Layer**: Conversation history lives in SQLite (not flat files), supporting concurrent reads/writes and full-text search. Memory lives in MEMORY.md / USER.md. Skills live in a skills directory. All this state survives process restarts.

![Message Flow Path](../../illustrations/en/s00-architecture/02-flowchart-message-flow.png)

## How a Message Flows Through the System

Taking the CLI scenario as an example (the simplest path):

```text
1. User types a message in the terminal
2. CLI creates an AIAgent instance
3. AIAgent assembles the system prompt
   - Read SOUL.md (persona)
   - Read MEMORY.md / USER.md (memory)
   - Read HERMES.md or AGENTS.md (project configuration)
   - Append tool definitions and skill index
4. Send messages + system prompt + tools to the model API
   (via the OpenAI SDK; all providers use the same interface)
5. Model returns:
   - If plain text -> display to user, done
   - If tool_calls -> continue
6. For each tool_call:
   - Look up the handler in the tool registry
   - Check whether it matches a dangerous-command pattern
   - Execute the tool (in the current execution environment)
   - Write the result back into messages with role "tool"
7. Go back to step 4 for the next iteration
8. After the loop ends, persist the entire session to SQLite
```

Taking the Gateway scenario as an example (adds a message-routing layer):

```text
1. User sends a message in Telegram
2. The Telegram adapter receives the message and converts it to the unified format
3. Gateway looks up or creates a session based on chat_id
4. Gateway creates an AIAgent instance (passing in historical messages)
5. The remaining steps are identical to CLI (steps 3-8)
6. The agent's reply is sent back to the user through the Telegram adapter
```

Key insight: **The only difference between the Gateway scenario and the CLI scenario is the entry and exit points; the core loop is exactly the same.**

## Five Key Design Decisions in Hermes Agent

These five decisions are the keys to understanding the system. Without grasping them, later chapters will leave you wondering "why was it done this way?"

### 1. Why Use the OpenAI SDK as the Only API Client

Hermes Agent is not locked to any single model provider. It uses the OpenAI Python SDK (`from openai import OpenAI`) and connects to different providers by setting different `base_url` values.

This means switching from OpenRouter to Anthropic or a local endpoint requires zero code changes -- just a configuration update.

This decision dictates the message format for the entire system: all messages use the OpenAI format (`role: user/assistant/tool`, `tool_calls`, `tool_call_id`).

### 2. Why the Core Loop Is Synchronous

Most modern Python frameworks lean toward fully async. But the core loop in Hermes Agent is a synchronous `def run_conversation()`, not an `async def`.

The reasons are practical:

- Most tools (file I/O, terminal commands) are inherently synchronous
- Error handling and debugging are far simpler in a synchronous loop
- The few async tools (network requests) are bridged in through a persistent event loop

This "synchronous body + async bridge" pattern runs through the entire tool layer.

### 3. Why Tools Use Self-Registration Instead of Central Configuration

Each tool file automatically calls the registry's `register()` method on Python import.

The import chain is clear: the registry depends on no tools -> tools depend on the registry -> the orchestration layer imports all tools to trigger registration -> the core loop uses the orchestration layer.

This means adding a new tool only requires writing one file; no other file needs to change.

### 4. Why SQLite Instead of the File System

Because in the Gateway scenario, messages from multiple platforms can arrive simultaneously. SQLite's WAL mode supports concurrent reads and writes, and FTS5 enables full-text search over historical sessions.

A file-system approach works fine for single-user CLI use, but breaks down under multi-platform concurrency.

### 5. Why the Agent Can Modify Itself

This is the most fundamental difference between Hermes Agent and frameworks like LangChain or AutoGen: **the agent can not only execute tasks but also learn from experience and rewrite its own behavior.**

This is embodied in three mechanisms:

- **Background Review**: Every N conversation turns, the main agent forks a background copy whose sole job is to ask "were there user preferences worth remembering? were there solutions worth abstracting into skills?" -- without any user prompting, it automatically updates MEMORY.md/USER.md or creates new skills
- **Skill Authoring Loop**: The agent can directly create, edit, and patch its own skill files through `skill_manager_tool`. The next time it encounters a similar task, it reuses the skill instead of reasoning from scratch
- **Trajectory + RL Pipeline**: All conversation trajectories can be compressed into training data and used to RL-train the next-generation model

The first two mechanisms operate at runtime ("learning"); the third operates offline ("evolution"). Together they form a complete closed loop: **use -> remember -> abstract -> train -> use better**.

Phase 5 covers this loop in detail.

## Five-Phase Learning Path

| Phase | Goal | Chapters | What You Are Learning |
|---|---|---|---|
| 1 | Build a working single agent | s01-s06 | Agent loop, tool registration, SQLite persistence, prompt assembly, context compression, error recovery |
| 2 | Add intelligence and safety | s07-s11 | Memory, skill management, dangerous-command approval, sub-agent delegation, configuration system |
| 3 | Connect to multiple platforms | s12-s15 | Gateway architecture, platform adapters, terminal backend abstraction, scheduled tasks |
| 4 | Advanced capabilities | s16-s19 | MCP, browser automation, voice & vision, CLI and web interfaces |
| 5 | Self-evolution and production readiness | s20-s24 | Background review, skill authoring loop, hook system, trajectory & RL, plugin architecture |

After each phase, pause and hand-write a minimal version from memory before moving on.

### Phase 5: Dedicated Chapters

This is the part most agent tutorials never cover -- Hermes Agent's true differentiator:

- **s20: Background Review** -- How the agent introspects, periodically forking a self-review process
- **s21: Skill Authoring Loop** -- How the agent reads and writes its own skill files, turning one-off solutions into reusable capabilities
- **s22: Hook System and BOOT.md** -- Driving continuous adaptation through lifecycle hooks: self-check at startup, summarize at session end
- **s23: Trajectory and RL Training Loop** -- `batch_runner` + `trajectory_compressor` + `rl_cli`: how conversation data becomes training data
- **s24: Plugin Architecture and Memory-Provider Ecosystem** -- holographic, honcho, mem0, supermemory, and other pluggable memory backends

## The Critical State You Need to Understand

### messages -- Working Memory

All messages in the current conversation. This is not a chat-log display -- it is the input the model will read on its next turn.

### Tool Registry -- Capability Directory

A mapping from "tool name -> handler function." Tools register themselves; at runtime, calls are dispatched by looking up the table.

### SQLite Session -- Persistent Record

Complete session metadata and message history. Full-text searchable, concurrency-safe.

### SOUL.md / MEMORY.md / HERMES.md -- Long-Term Context

Three different sources of long-term context: persona, memory, and project configuration. They are assembled into the system prompt at the start of each conversation.

### Execution Environment -- Where Commands Run

An abstract interface, transparent to upper layers. Tools don't care whether a command runs locally or inside Docker.

## Where Readers Get Stuck Most Often

### "What exactly is the relationship between Gateway and CLI?"

They are two different entry points into the same core loop. Learn CLI first; look at Gateway in Phase 3.

### "Tools, skills, and MCP are all capabilities -- what's the difference?"

- Tools: capabilities hard-coded in the source
- Skills: capability files the agent can create and edit at runtime
- MCP: third-party capabilities connected through an external protocol

### "Why are there so many configuration sources?"

Because the agent may run in different scenarios (CLI development, Telegram production, Docker isolation), and each scenario needs different settings. The configuration system merges multiple sources using a priority chain.

## Where to Go from Here

Recommended reading order:

1. Start with `s01` (agent loop) and `s02` (tool system) -- the minimum viable agent
2. Then `s03` through `s06` -- add persistence, prompt assembly, compression, error handling
3. Move to `s07` through `s11` -- add memory, skills, safety, delegation, configuration
4. Continue with `s12` through `s15` -- enter multi-platform territory
5. Then `s16` through `s19` -- advanced capabilities and interface layers
6. Finally `s20` through `s24` -- the self-evolution loop and extensible architecture

If you just want a "working agent," finishing Phases 1-2 is enough.
If you want to connect messaging platforms, read through Phase 3.
If you want to understand **what makes Hermes Agent special** -- you must read through Phase 5.

If the terminology starts to tangle at any chapter, come back to this chapter and the [`glossary.md`](./glossary.md) for a refresher.

---

**One sentence to remember:**

The core design of Hermes Agent is "a synchronous agent loop + self-registering tool system + SQLite persistence." This core connects to multiple platforms through the Gateway, executes on multiple backends through environment abstraction, and forms a self-evolution loop through Background Review + Skill Authoring + RL Training.
