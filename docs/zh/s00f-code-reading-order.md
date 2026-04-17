# s00f: 本仓库代码阅读顺序

> 这一页只回答一个问题：**`agents/` 目录下的 `.py` 文件应该按什么顺序打开？**
>
> 它不讲原理（原理在主线章节里），只告诉你"先看哪个、再看哪个"，让你在读文档的同时能对着源码走一遍。

## 建议顺序

每个 `agents/sNN_*.py` 都对应一个主线章节。**先读章节文档，再打开同编号的源码。**

一份可运行的代码比一页抽象解释更能建立直觉。

### 阶段 1：单 agent 核心（必读）

| 顺序 | 源文件 | 对应章节 | 先盯住什么 |
|---|---|---|---|
| 1 | `s01_agent_loop.py` | `s01-the-agent-loop.md` | `messages` 列表、`run_conversation()` 循环 |
| 2 | `s02_tool_system.py` | `s02-tool-system.md` | `ToolRegistry`、`@tool` 装饰器 |
| 3 | `s03_session_store.py` | `s03-session-store.md` | `SessionDB`、SQLite schema、FTS5 |
| 4 | `s04_prompt_builder.py` | `s04-prompt-builder.md` | `build_context_files_prompt()` 的分区组装 |
| 5 | `s05_context_compression.py` | `s05-context-compression.md` | 压缩阈值、摘要提示词 |
| 6 | `s06_error_recovery.py` | `s06-error-recovery.md` | `classify_api_error()`、退避重试、故障转移 |

读完这 6 个文件，你已经拥有一个能持久化、能压缩、能容错的最小单 agent。

### 阶段 2：智能层

| 顺序 | 源文件 | 对应章节 |
|---|---|---|
| 7 | `s07_memory_system.py` | `s07-memory-system.md` |
| 8 | `s08_skill_system.py` | `s08-skill-system.md` |
| 9 | `s09_permission_system.py` | `s09-permission-system.md` |
| 10 | `s10_subagent_delegation.py` | `s10-subagent-delegation.md` |
| 11 | `s11_configuration_system.py` | `s11-configuration-system.md` |

### 阶段 3：跨平台

| 顺序 | 源文件 | 对应章节 |
|---|---|---|
| 12 | `s12_gateway_architecture.py` | `s12-gateway-architecture.md` |
| 13 | `s13_platform_adapters.py` | `s13-platform-adapters.md` |
| 14 | `s14_terminal_backends.py` | `s14-terminal-backends.md` |
| 15 | `s15_scheduled_tasks.py` | `s15-scheduled-tasks.md` |

### 阶段 4：高级能力

| 顺序 | 源文件 | 对应章节 |
|---|---|---|
| 16 | `s16_mcp.py` | `s16-mcp.md` |
| 17 | `s17_browser_automation.py` | `s17-browser-automation.md` |
| 18 | `s18_voice_vision.py` | `s18-voice-vision.md` |
| 19 | `s19_cli_and_web_interface.py` | `s19-cli-and-web-interface.md` |
| 20 | `s20_background_review.py` | `s20-background-review.md` |

### 阶段 5：自我进化

| 顺序 | 源文件 | 对应章节 |
|---|---|---|
| 21 | `s21_skill_creation_loop.py` | `s21-skill-creation-loop.md` |
| 22 | `s22_hook_system.py` | `s22-hook-system.md` |
| 23 | `s23_trajectory_and_rl.py` | `s23-trajectory-and-rl.md` |
| — | *(仅文档)* | `s24-plugin-architecture.md` |
| 24 | `s25_skill_evolution.py` | `s25-skill-evolution.md` |
| 25 | `s26_evaluation_system.py` | `s26-evaluation-system.md` |
| 26 | `s27_optimization_and_deploy.py` | `s27-optimization-and-deploy.md` |

> 注：`s24` 当前仅提供文档，未提供参考实现文件。文档本身已可独立阅读。

## 阅读每个文件的节奏

每打开一个 `sNN_*.py`，建议这样走：

1. **先看顶部 docstring 和 `if __name__ == "__main__":`** — 快速知道这个文件能做什么、怎么跑。
2. **对照章节文档里的"最小实现"小节** — 把文档里讲的代码片段在源码里定位到。
3. **真的把它跑起来** — `python agents/sNN_*.py`，观察输出。
4. **动手改一点** — 加一个自己的工具、改一个提示词、换一个阈值，看输出怎么变。

比"一口气读完所有源码"更重要的是：**每一章都有一个你亲手跑过、亲手改过的最小版本。**

## 什么时候可以跳读

如果你已经做过类似的系统，以下跳读路径是安全的：

- 只想看最核心的三件事：`s01 → s02 → s03`
- 只想看"跨平台怎么做到的"：读完 `s01` 后直接跳到 `s12 → s13`
- 只想看"agent 怎么自己进化"：读完 `s01 → s08` 后直接跳到 `s21 → s27`

其他情况下，建议按顺序读。章节之间的依赖不是装饰——后面章节会直接使用前面章节定义的数据结构。
