[English](./README.md) | [中文](./README-zh.md)

# Learn Hermes Agent

**Build a production-grade autonomous AI agent from scratch in Python.** A 27-chapter, code-first tutorial covering the agent loop, tool system, session persistence, memory, skills, context compression, MCP, multi-platform gateway (Telegram / Discord / Slack / WeChat), and RL-based self-evolution — inspired by Hermes Agent.

Every chapter ships a runnable reference implementation under `agents/sNN_*.py`, paired with a prose explanation under `docs/en/` (and `docs/zh/` for the Chinese mainline). Read, run, tweak, repeat.

This repo does not try to mirror every product detail from the Hermes Agent codebase. It focuses on the mechanisms that actually decide whether an agent can work autonomously across platforms:

- the conversation loop
- tool registry and dispatch
- session persistence
- prompt assembly
- context compression
- memory and skill management
- skill system
- permission and safety
- multi-platform gateway
- terminal backends
- scheduling
- external capability routing

The goal is simple:

**understand the real design backbone well enough that you can rebuild it yourself.**

## What This Repo Is Really Teaching

One sentence first:

**The model does the reasoning. The harness gives the model a working environment that spans platforms, persists across sessions, and manages its own skills.**

That working environment is made of a few cooperating parts:

- `Agent Loop`: send messages to the model, execute tool calls, append results, continue
- `Tool System`: a self-registering dispatch layer — the agent's hands
- `Session Store`: SQLite with FTS5 — conversation memory that survives restarts
- `Prompt Builder`: assemble system prompts from personality, memory, config, and context
- `Context Compression`: keep the active window small when conversations grow long
- `Memory & Skills`: durable knowledge and agent-managed skill files
- `Permission System`: detect dangerous commands before execution
- `Gateway`: a single agent loop that listens on Telegram, Discord, Slack, WeChat, and more
- `Terminal Backends`: run commands locally, in Docker, over SSH, or on serverless platforms
- `Cron / MCP / Voice`: grow the single-agent core into a full working platform

This is the teaching promise of the repo:

- teach the mainline in a clean order
- explain unfamiliar concepts before relying on them
- stay close to real system structure
- avoid drowning the learner in irrelevant product details

## What This Repo Deliberately Does Not Teach

This repo is not trying to preserve every detail that exists in the production system.

If a detail is not central to the agent's core operating model, it should not dominate the teaching line. That includes things like:

- packaging, Nix flakes, and release mechanics
- landing pages and marketing assets
- enterprise subscription and billing wiring
- telemetry and analytics
- RL training pipeline and batch runner internals
- platform-specific API quirks (WeChat XML parsing, Telegram inline keyboards)
- skin/theme engine cosmetics
- historical migration logic

Those details may matter in production. They do not belong at the center of a 0-to-1 teaching path.

## Who This Is For

The assumed reader:

- knows basic Python
- understands functions, classes, async/await basics
- may be completely new to agent systems or multi-platform bots

So the repo tries to keep a few strong teaching rules:

- explain a concept before using it
- keep one concept fully explained in one main place
- start from "what it is", then "why it exists", then "how to implement it"
- avoid forcing beginners to assemble the system from scattered fragments

## Recommended Reading Order

- Overview: [`docs/en/s00-architecture-overview.md`](./docs/en/s00-architecture-overview.md)
- Code Reading Order: [`docs/en/s00f-code-reading-order.md`](./docs/en/s00f-code-reading-order.md)
- Glossary: [`docs/en/glossary.md`](./docs/en/glossary.md)
- Teaching Scope: [`docs/en/teaching-scope.md`](./docs/en/teaching-scope.md)
- Data Structures: [`docs/en/data-structures.md`](./docs/en/data-structures.md)

## If This Is Your First Visit, Start Here

Do not open random chapters first.

The safest path is:

1. Read [`docs/en/s00-architecture-overview.md`](./docs/en/s00-architecture-overview.md) for the full system map.
2. Read [`docs/en/s00f-code-reading-order.md`](./docs/en/s00f-code-reading-order.md) so you know which source files to open first.
3. Follow the five stages in order: `s01-s06 -> s07-s11 -> s12-s15 -> s16-s20 -> s21-s27`.
4. After each stage, stop and rebuild the smallest version yourself before continuing.

If the middle and late chapters start to blur together, reset in this order:

1. [`docs/en/data-structures.md`](./docs/en/data-structures.md)
2. [`docs/en/entity-map.md`](./docs/en/entity-map.md)
3. then return to the chapter body

## Five Stages

1. `s01-s06`: build a working single-agent core with persistence
2. `s07-s11`: add intelligence — memory, skills, safety, delegation, and configuration
3. `s12-s15`: go multi-platform — gateway, adapters, terminal backends, and scheduling
4. `s16-s20`: add advanced capabilities — MCP, browser, voice, vision, and background review
5. `s21-s27`: self-improvement — skill creation, hooks, trajectory/RL, plugins, evaluation, and optimization

## Main Chapters

| Chapter | Topic | What you get |
|---|---|---|
| `s00` | Architecture Overview | the global map, key terms, and learning order |
| `s01` | Agent Loop | the synchronous conversation loop — ask, tool-call, append, continue |
| `s02` | Tool System | a self-registering tool registry with dispatch orchestration |
| `s03` | Session Store | SQLite + FTS5 persistence — conversations that survive restarts |
| `s04` | Prompt Builder | section-based system prompt assembly from personality, memory, and config |
| `s05` | Context Compression | auto-triggered LLM summarization when context grows too long |
| `s06` | Error Recovery | API error classification, retry with backoff, and provider failover |
| `s07` | Memory System | cross-session persistent knowledge with MEMORY.md and USER.md |
| `s08` | Skill System | agent-managed skills — create, edit, and execute |
| `s09` | Permission System | dangerous command detection and approval gates |
| `s10` | Subagent Delegation | spawn fresh context for isolated subtasks |
| `s11` | Configuration System | YAML config, env vars, profiles, and runtime migration |
| `s12` | Gateway Architecture | the multi-platform message dispatch loop |
| `s13` | Platform Adapters | building integrations for Telegram, Discord, Slack, WeChat, and more |
| `s14` | Terminal Backends | run commands in Docker, over SSH, on Modal, or Daytona |
| `s15` | Cron Scheduler | time-based automation with duration strings and cron expressions |
| `s16` | MCP Integration | external capability routing via Model Context Protocol |
| `s17` | Browser Automation | Playwright + Browserbase for web interaction |
| `s18` | Voice & Vision | TTS/STT pipelines and image analysis |
| `s19` | CLI Interface | prompt_toolkit + Rich for an interactive terminal experience |
| `s20` | Background Review | every N turns, a background pass updates memory and extracts skills |
| `s21` | Skill Creation Loop | background review extracts patterns into reusable skills |
| `s22` | Hook System | lifecycle hooks for extensibility without modifying core code |
| `s23` | Trajectory & RL | conversation trajectories become training data for model improvement |
| `s24` | Plugin Architecture | pluggable memory, compression, and capability providers |
| `s25` | Self-Evolution Overview | the core insight, four evolution targets, and full pipeline overview |
| `s26` | Evaluation System | eval datasets, LLM-as-judge fitness scoring, and constraint gates |
| `s27` | Optimization & Deploy | the feedback→mutate→select loop, full pipeline, and Phase 2-4 concepts |

## Chapter Index: What to Focus on in Each Chapter

If this is your first time learning this material systematically, do not spread your attention evenly across all details. For each chapter, focus on 3 things:

1. What new capability this chapter adds.
2. Where the key state lives.
3. After finishing, can you hand-write this minimal mechanism yourself?

| Chapter | Key Data Structures / Entities | What you should have after this chapter |
|---|---|---|
| `s01` | `messages` list / `AIAgent` class / `run_conversation()` | a minimal working synchronous conversation loop |
| `s02` | `ToolRegistry` / `ToolEntry` / `tool_result` | a self-registering, self-discovering tool system |
| `s03` | `SessionDB` / `state.db` / FTS5 index | a SQLite persistence layer — conversations survive restarts |
| `s04` | `build_context_files_prompt()` / `build_skills_system_prompt()` | a pipeline assembling prompts from personality, memory, and config |
| `s05` | `ContextCompressor` / compression trigger threshold | an auto-summarization layer when context grows too long |
| `s06` | `ClassifiedError` / `FailoverReason` / `classify_api_error()` | error classification + backoff retry + provider failover |
| `s07` | `MemoryStore` / `MemoryManager` / `MEMORY.md` / `USER.md` | a layer that separates "temporary context" from "cross-session memory" |
| `s08` | `SkillMeta` / `SkillBundle` / skill SKILL.md files | a skill system that can create, edit, and execute |
| `s09` | `DANGEROUS_PATTERNS` / `detect_dangerous_command()` / `_ApprovalEntry` | a "dangerous operations must pass the gate" approval pipeline |
| `s10` | `delegate_tool` / child `messages` / isolated `AIAgent` | a subagent mechanism with isolated context for one-off delegation |
| `s11` | config dict / `Profile` management / migration functions | YAML config + profiles + runtime migration |
| `s12` | `GatewayRunner` / `MessageEvent` / platform routing | a unified multi-platform message dispatch loop |
| `s13` | `BasePlatformAdapter` / `MessageType` / `SendResult` | a reusable platform adapter pattern |
| `s14` | `BaseEnvironment` / local / docker / ssh / modal / daytona | abstract execution environments: local, Docker, SSH, cloud |
| `s15` | `parse_schedule()` / `create_job()` / `get_due_jobs()` / job dicts | a "when the time comes, work starts" scheduling layer |
| `s16` | `mcp_tool` / MCP config / tool schema bridging | a bus for plugging external tools and capabilities into the system |
| `s17` | `browser_tool` / Playwright / Browserbase provider | a browser automation layer for web interaction |
| `s18` | `tts_tool` / `voice_mode` / `vision_tools` | multimodal pipelines: voice I/O + image analysis |
| `s19` | `HermesCLI` / `CommandDef` / `KawaiiSpinner` / Rich rendering | a fully-featured interactive terminal interface |
| `s20` | `BackgroundReviewer` / `_MEMORY_REVIEW_PROMPT` / dual trigger counters | an "every N turns, auto-reflect → update memory/skills" background review mechanism |
| `s21` | skill creation loop / pattern extraction prompt / skill persistence pipeline | the "discover patterns → create reusable skills" prerequisite for self-evolution |
| `s22` | `HookRegistry` / `PluginHookRegistry` / BOOT.md handler | lifecycle hooks — inject custom logic without modifying core code |
| `s23` | `convert_to_trajectory()` / `compress_trajectory()` / reward functions | conversation data → training pipeline for model improvement |
| `s24` | plugin interfaces / memory providers / compression providers | pluggable memory and compression without touching core code |
| `s25` | `EvalExample` / `EvalDataset` | the foundational data structures for self-evolution |
| `s26` | `SyntheticDatasetBuilder` / `FitnessScore` / `ConstraintValidator` | measurement infrastructure — generate data, score outputs, gate changes |
| `s27` | `SkillOptimizer` / `EvolutionResult` / `evolve_skill()` | the optimization loop and full 7-step pipeline |

## Reading Approaches for Beginners

### Approach 1: Steady Mainline

Best for readers encountering agent systems for the first time.

Read in this order:

`s00 -> s01 -> ... -> s20 -> s21 -> ... -> s27` (follow the numbers; `s24` is docs-only).

### Approach 2: Build First, Complete Later

Best for "get it running, then fill in the gaps" readers.

Read in this order:

1. `s01-s06`: build a core agent with persistence and context compression
2. `s07-s11`: add memory, skills, safety, delegation, and config
3. `s12-s15`: go multi-platform, learn cross-environment execution
4. `s16-s20`: advanced capabilities plus the background self-review
5. `s21-s27`: step into self-evolution — skill creation, hooks, trajectories, evaluation, and optimization

### Approach 3: When You Get Stuck

If you hit a wall in the middle or late chapters, do not push forward blindly.

Reset in this order:

1. [`docs/en/s00-architecture-overview.md`](./docs/en/s00-architecture-overview.md)
2. [`docs/en/data-structures.md`](./docs/en/data-structures.md)
3. [`docs/en/entity-map.md`](./docs/en/entity-map.md)
4. the chapter you are stuck on

When readers truly get stuck, it is usually not "I can't read the code" but rather:

- which layer does this mechanism plug into?
- which data structure holds this state?
- what is the difference between this term and another that looks similar?

## Quick Start

```sh
git clone <repo-url>
cd learn-hermes-agent
pip install -r requirements.txt
cp .env.example .env
```

Then configure your API key in `.env`, and run:

```sh
python agents/s01_agent_loop.py
```

Suggested order:

1. Run `s01` and make sure the minimal loop really works.
2. Read `s00`, then move through `s01 -> s06` in order.
3. Only after the single-agent core plus its persistence feel stable, continue into `s07 -> s11`.
4. Move into gateway and platform chapters `s12 -> s15` only after the core agent makes sense.
5. Continue through `s16 -> s20`, then the self-evolution chapters `s21 -> s27`.

## How To Read Each Chapter

Each chapter is easier to absorb if you keep the same reading rhythm:

1. what problem appears without this mechanism
2. what the new concept means
3. what the smallest correct implementation looks like
4. where the state actually lives
5. how it plugs back into the loop
6. where to stop first, and what can wait until later

If you keep asking:

- "Is this core mainline or just a side detail?"
- "Where does this state actually live?"

go back to:

- [`docs/en/teaching-scope.md`](./docs/en/teaching-scope.md)
- [`docs/en/data-structures.md`](./docs/en/data-structures.md)
- [`docs/en/entity-map.md`](./docs/en/entity-map.md)

## Repository Structure

```text
learn-hermes-agent/
├── agents/              # runnable Python reference implementations per chapter (s24 is an exception, see below)
├── docs/zh/             # Chinese mainline docs
├── docs/en/             # English docs
├── illustrations/       # chalkboard-style diagrams for each chapter
├── tests/               # smoke tests
├── web/                 # web teaching platform (optional)
├── .env.example         # environment variable template
└── requirements.txt     # Python dependencies
```

> Note: `s24 Plugin Architecture` currently ships with documentation only (`docs/en/s24-plugin-architecture.md` and the Chinese counterpart). There is no `agents/s24_*.py` reference implementation. The doc is self-contained and does not block the rest of the reading order.

## Teaching Tradeoffs

To ensure "buildable from 0 to 1", this repo makes deliberate tradeoffs:

- Teach the minimal correct version first, then explain extension boundaries.
- If a real mechanism is complex but the core idea is not, teach the core idea first.
- If an advanced term appears, explain it — do not assume the reader already knows.
- If an edge case in the real system has low teaching value, remove it entirely.

This means the repo aims for:

**High fidelity on core mechanisms, deliberate tradeoffs on peripheral details.**

## Language Status

Chinese is the canonical teaching line and the fastest-moving version.

- `zh`: most reviewed and most complete
- `en`: all chapters s00-s27 available; Chinese is updated first

If you want the fullest and most frequently refined explanation path, use the Chinese docs first.

## End Goal

By the end of the repo, you should be able to answer these questions clearly:

- what is the minimum state an autonomous agent needs to persist across sessions?
- why is the tool registry the center of the agent's capability?
- how does a single conversation loop scale to 15+ messaging platforms?
- what problem do memory, skills, permissions, context compression, and error recovery each solve?
- how do terminal backends abstract away the execution environment?
- when should a single-agent system grow into gateway, scheduling, MCP, and voice?

If you can answer those questions clearly and build a similar system yourself, this repo has done its job.

---

**This is not "copy the source code line by line." This is "grasp the designs that truly matter, then build it yourself."**
