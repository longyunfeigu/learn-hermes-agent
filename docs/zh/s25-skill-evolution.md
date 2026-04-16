# s25: Self-Evolution Overview (自进化总览)

`s00 > s01 > ... > s23 > s24 > [ s25 ] > s26 > s27`

> *s23 通过训练让模型本身变强。s25-s27 不改模型——只改模型收到的文本。技能指令、工具描述、系统提示词、甚至工具代码，全是文本，全可以被系统性地优化。*

![自进化公式](../../illustrations/s25-skill-evolution/01-infographic-evolution-formula.png)

## 这一章要解决什么问题

先退一步看全局。

agent 运行时收到的**所有东西**——系统提示词、技能指令、工具描述——全是文本。模型的表现由两件事决定：

```text
agent 表现 = 模型能力 × 上下文文本质量
```

s23 改的是等号左边的**模型能力**（RL 训练，需要 GPU，成本高）。

但等号右边的**上下文文本质量**呢？技能是 s21 自动生成的，可能写得粗糙；工具描述是人写的，可能措辞不精确导致模型选错工具；系统提示词里的行为指南可能不够清晰。

这些文本直接影响 agent 表现，但从来没有被系统性地测试和改进过。

Hermes Agent 的自进化要解的就是这个问题：**用"打分 → 改写 → 择优"的循环，系统性地优化 agent 收到的所有文本。**

关键特性：
- 不需要训练模型，不需要 GPU
- 成本极低：~$2-10/次优化
- 即时生效：改完文本，下次对话就用新版本

## 建议联读

- [`s08-skill-system.md`](./s08-skill-system.md) — 技能的基础：格式、发现、加载
- [`s21-skill-creation-loop.md`](./s21-skill-creation-loop.md) — 技能怎么被创建的
- [`s23-trajectory-and-rl.md`](./s23-trajectory-and-rl.md) — 离线训练 vs 文本优化的对比

## 先解释几个名词

### 什么是文本优化（text optimization）

不改模型权重，只改模型收到的**文本**。通过系统性地试不同版本的文本、评估效果、保留更好的版本，来提升 agent 的表现。

一个类比：你不换厨师（模型），只换菜谱（技能文本）。好菜谱让同一个厨师做出更好的菜。

### 什么是 GEPA

**Genetic-Pareto Prompt Evolution**，ICLR 2026 的论文，集成在 DSPy 框架里。核心思路：读执行 trace，理解**为什么**失败（不只是"失败了"），然后做针对性的文本变异。

Hermes Agent 实际用的就是 `dspy.GEPA()`。后续章节的教学实现用最简方式模拟同一个思路——不依赖 DSPy。

### 什么是 Darwinian Evolver

专门进化代码的框架（AGPL v3），用 git 管理代码变体。Hermes 在 Phase 4（代码进化）中使用它。和 GEPA 不同，它操作的是 Python 源码而不是提示词。

## 四层进化目标

自进化不是只针对 skill 的小功能。它是一个通用的文本优化管线，覆盖四类目标。四层共享同一个优化循环（打分 → 改写 → 择优），区别在于进化的对象和风险等级。

### Phase 1: Skill 文件（最高价值，最低风险）

技能是纯文本的任务指令——"第一步做 X，注意 Y 坑，如果 Z 则..."。

为什么从这里开始？容易变异（改一段 markdown），容易评估（让 agent 用它做个任务看效果），改坏了也只影响一个 skill。

引擎：DSPy + GEPA。状态：**已实现**。

### Phase 2: Tool descriptions（中等价值，低风险）

工具描述决定了模型"什么时候选哪个工具"。比如 `search_files` 的描述如果不够清晰，模型可能在该用 `search_files` 的时候错选了 `terminal(grep)`。

优化方式：生成"任务→应该用哪个工具"的测试集，GEPA 变异描述文本，评估模型是否选对了工具。

约束：每个工具描述不超过 500 字符（每次 API 调用都会发送全部工具 schema）。

引擎：DSPy + GEPA。状态：计划中。

### Phase 3: System prompt sections（高价值，高风险）

系统提示词里的行为指南——"什么时候该保存记忆""什么时候该搜索历史对话"。改好了，agent 整体行为改善；改坏了，影响所有对话。

约束最严：每个 section 不能比原版大 20% 以上（防止提示词膨胀突破缓存边界），必须跑 benchmark 回归检查。

引擎：DSPy + GEPA。状态：计划中。

### Phase 4: Tool implementation code（高价值，最高风险）

实际的 Python 代码。和前三层不同——前三层改的是自然语言文本，这一层改的是代码。

约束最硬：全量测试必须 100% 通过，函数签名不能改，registry.register() 调用不能动。

引擎：Darwinian Evolver（外部 CLI）。状态：计划中。

## 完整管线：7 步

不管进化哪一层，管线都是同一个结构：

```text
┌──────────────────────────────────────────────────┐
│  1. SELECT TARGET                                │
│     选一个需要改进的 skill / tool desc / prompt    │
│                                                  │
│  2. BUILD EVAL DATASET           ← s26 详讲      │
│     生成测试用例，分 train/val/holdout            │
│                                                  │
│  3. EVALUATE BASELINE            ← s26 详讲      │
│     用适应度函数给当前版本打分                     │
│                                                  │
│  4. CHECK CONSTRAINTS            ← s26 详讲      │
│     当前版本通过约束检查吗？                       │
│                                                  │
│  5. OPTIMIZE (repeat N times)    ← s27 详讲      │
│     收集反馈 → 针对性改写 → 打分 → 择优             │
│                                                  │
│  6. VALIDATE EVOLVED             ← s27 详讲      │
│     进化版通过约束吗？holdout 分数如何？           │
│                                                  │
│  7. DEPLOY                       ← s27 详讲      │
│     备份 → 写入 → 下次对话自动生效                │
│                                                  │
│  步骤 2-4 = "度量体系" (s26)                      │
│  步骤 5-7 = "优化与部署" (s27)                    │
└──────────────────────────────────────────────────┘
```

这 7 步直接对齐 Hermes 的 `evolve_skill.py`。

## Hermes 的架构：独立仓库，作用于 agent

一个重要的架构决策：**自进化系统不在 hermes-agent 仓库里，而是一个独立仓库**（`NousResearch/hermes-agent-self-evolution`），作用于 hermes-agent。

```text
hermes-agent-self-evolution/        ← 独立仓库
├── evolution/
│   ├── core/
│   │   ├── config.py               ← 配置 + hermes-agent 路径发现
│   │   ├── dataset_builder.py      ← 评估数据集生成
│   │   ├── external_importers.py   ← 从 Claude Code/Copilot/Hermes 挖数据
│   │   ├── fitness.py              ← 适应度函数（LLM-as-judge）
│   │   └── constraints.py          ← 约束门控
│   ├── skills/
│   │   ├── skill_module.py         ← 把 SKILL.md 包装成 DSPy module
│   │   └── evolve_skill.py         ← Phase 1 主管线
│   ├── tools/                      ← Phase 2（计划中）
│   ├── prompts/                    ← Phase 3（计划中）
│   ├── code/                       ← Phase 4（计划中）
│   └── monitor/                    ← Phase 5 自动触发（计划中）
├── datasets/                       ← 生成的评估数据集
└── tests/
```

为什么独立？因为自进化是**开发时工具**，不是运行时功能。它读 hermes-agent 的代码和数据，输出改进后的文件，通过 git PR 提交——永远不会在用户对话过程中执行。

## 从最笨的实现开始

人手动改 skill：

```text
你: [打开 SKILL.md，读一遍]
你: 哦，第 3 步缺了错误处理的说明
你: [手动改 SKILL.md]
你: [跑几个测试看看改好了没]
```

能用。但两个问题：

### 问题一：没有量化的评估标准

"这个技能好不好"是一个模糊的判断。改了 SKILL.md，怎么知道改得更好了而不是更差了？需要量化评估，不能靠感觉。

→ **s26 解决这个问题**：构建评估数据集 + 适应度函数 + 约束门控。

### 问题二：没有系统性的改进策略

就算知道分数低，怎么改？凭直觉改一处？改了之后要不要回退？要改几轮？

→ **s27 解决这个问题**：收集反馈→针对性改写→打分→择优的循环 + 完整管线。

## 教学边界

本章只讲"自进化是什么、为什么做、全貌是什么"。

**不讲**具体实现——那是 s26（度量体系）和 s27（优化与部署）的事。

本章是地图，后两章是实际走路。

## 后续两章预告

| 章节 | 核心问题 | 你会得到什么 |
|------|---------|------------|
| **s26** | 怎么知道好不好？ | EvalDataset + FitnessScore + ConstraintValidator + 数据从哪来 |
| **s27** | 怎么改进和上线？ | SkillOptimizer + evolve_skill() 完整管线 + Phase 2-4 应用 |

## 学完这章后，你应该能回答

- agent 的能力由什么决定？模型和文本各起什么作用？
- 为什么优化文本不需要 GPU？和 RL 训练有什么互补关系？
- 四层进化目标分别是什么？风险等级怎么排？
- 完整管线的 7 步是什么？哪几步属于"度量"，哪几步属于"优化"？
- 自进化仓库为什么独立于 hermes-agent？它是运行时功能还是开发时工具？

---

**一句话记住：不改模型，只改文本。四层目标，一套管线。**
