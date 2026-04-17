[English](./README.md) | [中文](./README-zh.md)

# Learn Hermes Agent

一个面向实现者的教学仓库：从零开始，手搓一个生产级自主 AI Agent。

这里教的不是"如何逐行模仿 Hermes Agent 的源码"，而是"如何抓住真正决定 agent 能力的核心机制"，用清晰、渐进、可自己实现的方式，把一个类似 Hermes Agent 的系统从 0 做到能用、好用、可跨平台运行。

## 这个仓库到底在教什么

先把一句话说清楚：

**模型负责思考。代码负责给模型提供一个跨平台、可持久、可管理技能的工作环境。**

这个"工作环境"就是 `harness`。
对 Hermes Agent 来说，harness 主要由这些部分组成：

- `Agent Loop`：不停地"向模型提问 -> 执行工具 -> 把结果喂回去"的同步对话循环。
- `Tool System`：自注册的工具系统 — agent 的双手。
- `Session Store`：SQLite + FTS5 全文搜索 — 让对话跨重启存活。
- `Prompt Builder`：从人设、记忆、配置和上下文组装系统提示词。
- `Context Compression`：对话变长时，自动用 LLM 做摘要压缩。
- `Memory & Skills`：持久化知识和 agent 管理的技能文件。
- `Permission System`：危险命令执行前的检测与审批。
- `Gateway`：同一套 agent 循环，接入 Telegram、Discord、Slack、微信等 15+ 平台。
- `Terminal Backends`：本地、Docker、SSH、Modal、Daytona — 不管在哪执行命令。
- `Cron / MCP / Voice`：让单 agent 升级成完整的工作平台。

本仓库的目标，是让你真正理解这些机制为什么存在、最小版本怎么实现、什么时候该升级到更完整的版本。

## 这个仓库不教什么

本仓库**不追求**把 Hermes Agent 生产仓库的所有实现细节逐条抄下来。

下面这些内容，如果和 agent 的核心运行机制关系不大，就不会占据主线篇幅：

- 打包、Nix flake、发布流程
- 落地页和营销素材
- 企业订阅和计费接线
- 遥测和数据分析
- RL 训练管道和批量轨迹生成的内部细节
- 平台特定的 API 细节（微信 XML 解析、Telegram 内联键盘等）
- 皮肤/主题引擎
- 历史版本迁移逻辑

这不是偷懒，而是教学取舍。

一个好的教学仓库，应该优先保证三件事：

1. 读者能从 0 到 1 自己做出来。
2. 读者不会被大量无关细节打断心智。
3. 真正关键的机制、数据结构和模块协作关系讲得完整、准确、没有幻觉。

## 面向的读者

这个仓库默认读者是：

- 会一点 Python
- 知道函数、类、async/await 这些基础概念
- 但不一定系统做过 agent、多平台机器人或复杂工程架构

所以这里会坚持几个写法原则：

- 新概念先解释再使用。
- 同一个概念尽量只在一个地方完整讲清。
- 先讲"它是什么"，再讲"为什么需要"，最后讲"如何实现"。
- 不把初学者扔进一堆互相引用的碎片文档里自己拼图。

## 学习承诺

学完这套内容，你应该能做到两件事：

1. 自己从零写出一个结构清楚、可运行、可跨平台部署的自主 AI Agent。
2. 看懂更复杂系统时，知道哪些是主干机制，哪些只是产品化外围细节。

我们追求的是：

- 对关键机制和关键数据结构的高保真理解
- 对实现路径的高可操作性
- 对教学路径的高可读性

而不是把"原始源码里存在过的所有复杂细节"一股脑堆给你。

## 建议阅读顺序

先读总览，再按顺序向后读。

- 总览：[`docs/zh/s00-architecture-overview.md`](./docs/zh/s00-architecture-overview.md)
- 代码阅读顺序：[`docs/zh/s00f-code-reading-order.md`](./docs/zh/s00f-code-reading-order.md)
- 术语表：[`docs/zh/glossary.md`](./docs/zh/glossary.md)
- 教学范围：[`docs/zh/teaching-scope.md`](./docs/zh/teaching-scope.md)
- 数据结构总表：[`docs/zh/data-structures.md`](./docs/zh/data-structures.md)

## 第一次打开仓库，最推荐这样走

如果你是第一次进这个仓库，不要随机点章节。

最稳的入口顺序是：

1. 先看 [`docs/zh/s00-architecture-overview.md`](./docs/zh/s00-architecture-overview.md)，确认系统全景。
2. 再看 [`docs/zh/s00f-code-reading-order.md`](./docs/zh/s00f-code-reading-order.md)，确认本地 `agents/*.py` 该按什么顺序打开。
3. 然后按五阶段读主线：`s01-s06 -> s07-s11 -> s12-s15 -> s16-s20 -> s21-s27`。
4. 每学完一个阶段，停下来自己手写一个最小版本，不要等全部看完再回头补实现。

如果你读到一半开始打结，最稳的重启顺序是：

1. [`docs/zh/data-structures.md`](./docs/zh/data-structures.md)
2. [`docs/zh/entity-map.md`](./docs/zh/entity-map.md)
3. 再回当前章节正文

## 五阶段主线

| 阶段 | 目标 | 章节 |
|---|---|---|
| 阶段 1 | 先做出一个能工作、能持久化的单 agent | `s01-s06` |
| 阶段 2 | 再补智能层 — 记忆、技能、安全、委派、配置 | `s07-s11` |
| 阶段 3 | 跨平台 — Gateway、适配器、终端后端、定时任务 | `s12-s15` |
| 阶段 4 | 高级能力 — MCP、浏览器、语音、视觉、后台审视 | `s16-s20` |
| 阶段 5 | 自我进化 — 技能创作、Hook、轨迹/RL、插件、技能自进化 | `s21-s27` |

## 全部章节

| 章节 | 主题 | 你会得到什么 |
|---|---|---|
| `s00` | 架构总览 | 全局地图、名词、学习顺序 |
| `s01` | Agent Loop | 同步对话循环 — 提问、工具调用、追加结果、继续 |
| `s02` | Tool System | 自注册的工具注册表与分发调度 |
| `s03` | Session Store | SQLite + FTS5 持久化 — 对话跨重启存活 |
| `s04` | Prompt Builder | 基于分区的系统提示词组装：人设、记忆、配置 |
| `s05` | Context Compression | 对话过长时自动触发 LLM 摘要压缩 |
| `s06` | Error Recovery | API 错误分类、退避重试与服务商故障转移 |
| `s07` | Memory System | 跨会话持久知识：MEMORY.md 与 USER.md |
| `s08` | Skill System | agent 管理的技能 — 创建、编辑、执行 |
| `s09` | Permission System | 危险命令检测与审批关卡 |
| `s10` | Subagent Delegation | 为隔离子任务创建独立上下文 |
| `s11` | Configuration System | YAML 配置、环境变量、Profile 与运行时迁移 |
| `s12` | Gateway Architecture | 多平台消息分发循环 |
| `s13` | Platform Adapters | 接入 Telegram、Discord、Slack、微信等平台 |
| `s14` | Terminal Backends | 在 Docker、SSH、Modal、Daytona 中执行命令 |
| `s15` | Cron Scheduler | 支持时长字符串和 cron 表达式的定时自动化 |
| `s16` | MCP Integration | 通过 Model Context Protocol 接入外部能力 |
| `s17` | Browser Automation | Playwright + Browserbase 网页交互 |
| `s18` | Voice & Vision | TTS/STT 管道与图像分析 |
| `s19` | CLI Interface | prompt_toolkit + Rich 交互式终端 |
| `s20` | Background Review | 每 N 轮后台审视对话，自动更新记忆、抽取技能 |
| `s21` | Skill Creation Loop | 后台审视提取模式，自动创建可复用技能 |
| `s22` | Hook System | 生命周期钩子，不改核心代码扩展行为 |
| `s23` | Trajectory & RL | 对话轨迹变训练数据，强化学习改进模型 |
| `s24` | Plugin Architecture | 可插拔的记忆、压缩、能力提供者 |
| `s25` | Self-Evolution Overview | 核心洞察、四层进化目标、完整管线总览 |
| `s26` | Evaluation System | 评估数据集、LLM-as-judge 打分、约束门控 |
| `s27` | Optimization & Deploy | 收集反馈→改写→择优循环、完整管线、Phase 2-4 概念 |

## 章节总索引：每章最该盯住什么

如果你是第一次系统学这套内容，不要把注意力平均分给所有细节。
每章都先盯住 3 件事：

1. 这一章新增了什么能力。
2. 这一章的关键状态放在哪里。
3. 学完以后，你自己能不能把这个最小机制手写出来。

| 章节 | 最该盯住的数据结构 / 实体 | 这一章结束后你手里应该多出什么 |
|---|---|---|
| `s01` | `messages` 列表 / `AIAgent` 类 / `run_conversation()` | 一个最小可运行的同步对话循环 |
| `s02` | `ToolRegistry` / `ToolEntry` / `tool_result` | 一个能自注册、自发现的工具系统 |
| `s03` | `SessionDB` / `state.db` / FTS5 索引 | 一个 SQLite 持久化层，对话重启不丢 |
| `s04` | `build_context_files_prompt()` / `build_skills_system_prompt()` | 一条从人设、记忆、配置组装提示词的管道 |
| `s05` | `ContextCompressor` / 压缩触发阈值 | 一个上下文膨胀时自动摘要的压缩层 |
| `s06` | `ClassifiedError` / `FailoverReason` / `classify_api_error()` | 一套错误分类 + 退避重试 + 故障转移 |
| `s07` | `MemoryStore` / `MemoryManager` / `MEMORY.md` / `USER.md` | 一套区分"临时上下文"和"跨会话记忆"的持久层 |
| `s08` | `SkillMeta` / `SkillBundle` / SKILL.md 技能文件 | 一个能创建、编辑、执行的技能系统 |
| `s09` | `DANGEROUS_PATTERNS` / `detect_dangerous_command()` / `_ApprovalEntry` | 一条"危险操作先过闸"的审批管道 |
| `s10` | `delegate_tool` / 子 `messages` / 隔离的 `AIAgent` 实例 | 一个能隔离上下文、做一次性委派的子 agent 机制 |
| `s11` | config 字典 / Profile 管理 / 迁移函数 | 一套 YAML 配置 + Profile + 运行时迁移 |
| `s12` | `GatewayRunner` / `MessageEvent` / 平台路由 | 一个统一的多平台消息分发循环 |
| `s13` | `BasePlatformAdapter` / `MessageType` / `SendResult` | 一个可复用的平台适配器模式 |
| `s14` | `BaseEnvironment` / local / docker / ssh / modal / daytona | 一套抽象执行环境：本地、Docker、SSH、云端 |
| `s15` | `parse_schedule()` / `create_job()` / `get_due_jobs()` / job 字典 | 一套"时间到了就能自动开工"的定时触发层 |
| `s16` | `mcp_tool` / MCP 配置 / 工具 schema 桥接 | 一套把外部工具与外部能力接入主系统的总线 |
| `s17` | `browser_tool` / Playwright / Browserbase provider | 一个能自动操作网页的浏览器自动化层 |
| `s18` | `tts_tool` / `voice_mode` / `vision_tools` | 语音输入输出 + 图像分析的多模态管道 |
| `s19` | `HermesCLI` / `CommandDef` / `KawaiiSpinner` / Rich 渲染 | 一个功能完整的交互式终端界面 |
| `s20` | `BackgroundReviewer` / `_MEMORY_REVIEW_PROMPT` / 双触发计数器 | 一套"每 N 轮自动反思→更新记忆/技能"的后台审视机制 |
| `s21` | 技能创作循环 / 模式抽取提示词 / 技能落盘管道 | 一套"发现模式→创建可复用技能"的自进化前置能力 |
| `s22` | `HookRegistry` / `PluginHookRegistry` / BOOT.md 处理 | 生命周期钩子——不改核心代码就能注入自定义逻辑 |
| `s23` | `convert_to_trajectory()` / `compress_trajectory()` / 奖励函数 | 对话数据→训练管线，用 RL 改进模型 |
| `s24` | 插件接口 / 记忆提供者 / 压缩提供者 | 可插拔的记忆和压缩，不碰核心代码 |
| `s25` | `EvalExample` / `EvalDataset` | 自进化的基础数据结构 |
| `s26` | `SyntheticDatasetBuilder` / `FitnessScore` / `ConstraintValidator` | 度量基础设施——生成数据、打分、约束门控 |
| `s27` | `SkillOptimizer` / `EvolutionResult` / `evolve_skill()` | 优化循环 + 完整 7 步管线 |

## 如果你是初学者，最推荐这样读

### 读法 1：最稳主线

适合第一次系统接触 agent 的读者。

按这个顺序读：

`s00 -> s01 -> ... -> s20 -> s21 -> ... -> s27`（按编号顺序，`s24` 只有文档无实现）

### 读法 2：先做出能跑的，再补完整

适合"想先把系统搭出来，再慢慢补完"的读者。

按这个顺序读：

1. `s01-s06`：先做出一个能持久化、能压缩上下文的核心 agent
2. `s07-s11`：补上记忆、技能、安全、委派和配置
3. `s12-s15`：接入多平台，学会跨环境执行
4. `s16-s20`：补高级能力与后台自反思
5. `s21-s27`：进入自我进化 — 技能创作、钩子、轨迹、评估、优化

### 读法 3：卡住时这样回看

如果你在中后半程开始打结，先不要硬往下冲。

回看顺序建议是：

1. [`docs/zh/s00-architecture-overview.md`](./docs/zh/s00-architecture-overview.md)
2. [`docs/zh/data-structures.md`](./docs/zh/data-structures.md)
3. [`docs/zh/entity-map.md`](./docs/zh/entity-map.md)
4. 当前卡住的那一章

因为读者真正卡住时，往往不是"代码没看懂"，而是：

- 这个机制到底接在系统哪一层
- 这个状态到底存在哪个结构里
- 这个名词和另一个看起来很像的名词到底差在哪

## 快速开始

```sh
git clone <repo-url>
cd learn-hermes-agent
pip install -r requirements.txt
cp .env.example .env
```

把 `.env` 里的 API Key 配置好以后：

```sh
python agents/s01_agent_loop.py
```

建议顺序：

1. 先跑 `s01`，确认最小循环真的能工作。
2. 一边读 `s00`，一边按顺序跑 `s01 -> s06`。
3. 等单 agent 核心吃透后，再进入 `s07 -> s11`。
4. Gateway 和平台章节 `s12 -> s15` 在核心 agent 理解清楚后再看。
5. 按阶段继续推进 `s16 -> s20`，最后进入自进化章节 `s21 -> s27`。

## 如何读这套教程

每章都配有黑板粉笔风格（chalkboard）的概念插图，帮助你快速建立心智模型。

每章都建议按这个顺序看：

1. `问题`：没有这个机制会出现什么痛点。
2. `概念定义`：先把新名词讲清楚。
3. `最小实现`：先做最小但正确的版本。
4. `核心数据结构`：搞清楚状态到底存在哪里。
5. `主循环如何接入`：它如何与 agent loop 协作。
6. `这一章先停在哪里`：先守住什么边界，哪些扩展可以后放。

如果你是初学者，不要着急追求"一次看懂所有复杂机制"。
先把每章的最小实现真的写出来，再理解升级版边界，会轻松很多。

如果你在阅读中经常冒出这两类问题：

- "这一段到底算主线，还是维护者补充？"
- "这个状态到底存在哪个结构里？"

建议随时回看：

- [`docs/zh/teaching-scope.md`](./docs/zh/teaching-scope.md)
- [`docs/zh/data-structures.md`](./docs/zh/data-structures.md)
- [`docs/zh/entity-map.md`](./docs/zh/entity-map.md)

## 本仓库的教学取舍

为了保证"从 0 到 1 可实现"，本仓库会刻意做这些取舍：

- 先教最小正确版本，再讲扩展边界。
- 如果一个真实机制很复杂，但主干思想并不复杂，就先讲主干思想。
- 如果一个高级名词出现了，就解释它是什么，不假设读者天然知道。
- 如果一个真实系统里某些边角分支对教学价值不高，就直接删掉。

这意味着本仓库追求的是：

**核心机制高保真，外围细节有取舍。**

## 项目结构

```text
learn-hermes-agent/
├── agents/              # 每一章对应一个可运行的 Python 参考实现（s24 例外，见下）
├── docs/zh/             # 中文主线文档
├── docs/en/             # 英文文档
├── illustrations/       # 每章配套的黑板风格插图（chalkboard style）
├── tests/               # 冒烟测试
├── web/                 # Web 教学平台（可选）
├── .env.example         # 环境变量示例
└── requirements.txt     # Python 依赖
```

> 注：`s24 Plugin Architecture` 当前仅提供文档（`docs/zh/s24-plugin-architecture.md` 和英文对应），未提供 `agents/s24_*.py` 参考实现。文档本身可独立阅读，不影响其他章节的学习顺序。

## 语言说明

当前仓库以中文文档为主线，最完整、更新也最快。

- `zh`：主线版本，最完整
- `en`：主要章节可用

如果你要系统学习，请优先看中文。

## 最后的目标

读完这套内容，你不应该只是"知道 Hermes Agent 很厉害"。

你应该能自己回答这些问题：

- 一个自主 agent 跨会话运行最少要持久化哪些状态？
- 工具注册表为什么是 agent 能力的核心？
- 同一套对话循环怎么扩展到 15+ 消息平台？
- 记忆、技能、权限、上下文压缩、错误恢复分别解决什么问题？
- 终端后端如何抽象掉执行环境的差异？
- 一个系统什么时候该从单 agent 升级成 Gateway、定时任务、MCP 和语音？

如果这些问题你都能清楚回答，而且能自己写出一个相似系统，那这套仓库就达到了它的目的。

---

**这不是"照着源码抄"。这是"抓住真正关键的设计，然后自己做出来"。**
