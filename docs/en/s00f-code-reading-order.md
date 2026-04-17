# s00f: Code Reading Order

> This page answers one question: **in what order should you open the `.py` files under `agents/`?**
>
> It does not teach mechanisms (that is what the main chapters are for). It only tells you "open this first, then that", so you can walk through the source while reading the docs.

## Recommended Order

Every `agents/sNN_*.py` maps to one main chapter. **Read the chapter doc first, then open the matching source file.**

A runnable reference implementation builds intuition faster than any abstract explanation.

### Stage 1: Single-Agent Core (required)

| Order | Source File | Chapter | What to focus on |
|---|---|---|---|
| 1 | `s01_agent_loop.py` | `s01-the-agent-loop.md` | the `messages` list, `run_conversation()` loop |
| 2 | `s02_tool_system.py` | `s02-tool-system.md` | `ToolRegistry`, `@tool` decorator |
| 3 | `s03_session_store.py` | `s03-session-store.md` | `SessionDB`, SQLite schema, FTS5 |
| 4 | `s04_prompt_builder.py` | `s04-prompt-builder.md` | section assembly in `build_context_files_prompt()` |
| 5 | `s05_context_compression.py` | `s05-context-compression.md` | compression threshold and summarization prompt |
| 6 | `s06_error_recovery.py` | `s06-error-recovery.md` | `classify_api_error()`, backoff retry, failover |

After these six files you have a persistent, compressing, fault-tolerant single agent.

### Stage 2: Intelligence Layer

| Order | Source File | Chapter |
|---|---|---|
| 7 | `s07_memory_system.py` | `s07-memory-system.md` |
| 8 | `s08_skill_system.py` | `s08-skill-system.md` |
| 9 | `s09_permission_system.py` | `s09-permission-system.md` |
| 10 | `s10_subagent_delegation.py` | `s10-subagent-delegation.md` |
| 11 | `s11_configuration_system.py` | `s11-configuration-system.md` |

### Stage 3: Multi-Platform

| Order | Source File | Chapter |
|---|---|---|
| 12 | `s12_gateway_architecture.py` | `s12-gateway-architecture.md` |
| 13 | `s13_platform_adapters.py` | `s13-platform-adapters.md` |
| 14 | `s14_terminal_backends.py` | `s14-terminal-backends.md` |
| 15 | `s15_scheduled_tasks.py` | `s15-scheduled-tasks.md` |

### Stage 4: Advanced Capabilities

| Order | Source File | Chapter |
|---|---|---|
| 16 | `s16_mcp.py` | `s16-mcp.md` |
| 17 | `s17_browser_automation.py` | `s17-browser-automation.md` |
| 18 | `s18_voice_vision.py` | `s18-voice-vision.md` |
| 19 | `s19_cli_and_web_interface.py` | `s19-cli-and-web-interface.md` |
| 20 | `s20_background_review.py` | `s20-background-review.md` |

### Stage 5: Self-Evolution

| Order | Source File | Chapter |
|---|---|---|
| 21 | `s21_skill_creation_loop.py` | `s21-skill-creation-loop.md` |
| 22 | `s22_hook_system.py` | `s22-hook-system.md` |
| 23 | `s23_trajectory_and_rl.py` | `s23-trajectory-and-rl.md` |
| — | *(docs only)* | `s24-plugin-architecture.md` |
| 24 | `s25_skill_evolution.py` | `s25-skill-evolution.md` |
| 25 | `s26_evaluation_system.py` | `s26-evaluation-system.md` |
| 26 | `s27_optimization_and_deploy.py` | `s27-optimization-and-deploy.md` |

> Note: `s24` currently ships with documentation only. The doc is self-contained and readable on its own.

## Rhythm for Each File

When you open a `sNN_*.py`, walk through it like this:

1. **Read the top docstring and `if __name__ == "__main__":`** — know what it does and how to run it.
2. **Match it to the "minimal implementation" section in the chapter doc** — find the snippets from the doc in the actual source.
3. **Actually run it** — `python agents/sNN_*.py` and observe the output.
4. **Change something small** — add your own tool, tweak a prompt, change a threshold, and see what changes.

What matters more than "reading all the source in one sitting": **every chapter leaves you with a minimal version you have personally run and personally tweaked.**

## When You Can Skip Ahead

If you have built similar systems before, these skip paths are safe:

- Just the three core things: `s01 → s02 → s03`
- Just "how does multi-platform work": after `s01`, jump to `s12 → s13`
- Just "how does the agent self-evolve": after `s01 → s08`, jump to `s21 → s27`

Otherwise, read in order. The dependencies between chapters are real — later chapters use data structures that earlier chapters define.
