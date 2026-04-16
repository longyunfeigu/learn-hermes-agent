# s21: Skill Creation Loop (技能创作闭环)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > [ s21 ] > s22 > s23 > s24`

> *agent 不只是执行任务，还能从经验中提取模式，把"一次性的解法"沉淀成"下次可复用的技能"。这是 Hermes Agent 区别于其他 agent 框架最核心的机制。*

![技能创作闭环](../../illustrations/s21-skill-creation/01-flowchart-creation-loop.png)

## 这一章要解决什么问题

s08 讲了技能系统的基础——agent 可以读取和使用技能文件。但那些技能是人预先写好的。

现在考虑一个场景：agent 帮你配置了一个复杂的 CI 流水线，过程中踩了三个坑，改了两次方案，最终跑通了。下周你让另一个同事的 agent 做同样的事——它会重新踩同样的三个坑。

**经验没有被记住。** 每次遇到同样的问题，都要重新摸索。

如果 agent 能在完成任务后自动回顾："这次踩了哪些坑？哪些步骤是通用的？"——然后把答案写成一个技能文件，下次遇到类似任务直接用。

这就是技能创作闭环要解决的问题：**让 agent 从经验中学习，把一次性的解法变成可复用的技能。**

## 建议联读

- [`s08-skill-system.md`](./s08-skill-system.md) — 技能的基础：格式、发现、加载、使用
- [`s10-subagent-delegation.md`](./s10-subagent-delegation.md) — 后台审视用子 agent 实现
- [`s04-prompt-builder.md`](./s04-prompt-builder.md) — 技能索引怎么注入系统提示词

## 先解释几个名词

### 什么是后台审视（background review）

agent 完成一段对话后，**fork 一个副本**在后台回顾这段对话。副本独立运行，不阻塞用户的下一个问题。它分析对话中有没有值得保存的经验——如果有，就调 `skill_manage` 创建或更新技能。

### 什么是技能创作闭环

一个完整的循环：

```text
使用 → 遇到问题，摸索出解法 → 后台审视提取模式 → 创建技能
  → 下次遇到类似任务 → 加载技能，直接用 → 跳过摸索
```

关键是"下次"——今天踩的坑，明天不会再踩。

### 什么是 skill_manage

agent 用来创建、编辑、删除技能的工具。和 `terminal`、`read_file` 一样注册在 registry 里，agent 可以在对话中随时调用。

## 从最笨的实现开始

让用户手动告诉 agent"把这个方案存成技能"：

```text
用户: 帮我配置 GitHub Actions CI
agent: [一番折腾后成功了]
用户: 把刚才的方案存成技能
agent: 好的 → 调 skill_manage(action="create", name="github-actions-ci", content="...")
```

能用。但有两个问题：

### 问题一：用户得记得说"存成技能"

大多数时候用户做完任务就走了，不会专门提醒 agent 总结经验。值得保存的经验就这么丢了。

### 问题二：agent 不知道什么值得保存

用户说"存成技能"，agent 把整段对话的所有步骤都堆进去——包括走错的弯路、无关的试错。结果技能文件又长又杂，下次用的时候反而误导。

**需要一个自动机制：不依赖用户提醒，能识别"什么是值得保存的非平凡经验"。**

## 最小心智模型

```text
agent 正常工作中...
    │
    │  每完成 10 次工具调用，检查一次
    │
    v
触发条件满足？
    │
    是
    │
    v
fork 一个副本（后台审视 agent）
    │  输入：这段对话的完整消息记录
    │  提示：分析对话，找出非平凡的、可复用的模式
    │  限制：最多 8 轮工具调用
    │
    v
后台审视 agent 分析后决定：
    │
    ├── 发现新模式 → skill_manage(action="create", ...)
    ├── 已有技能需要更新 → skill_manage(action="patch", ...)
    └── 没有值得保存的 → "Nothing to save." → 结束
    │
    v
用户看到通知："💾 Skill 'github-ci-setup' created"
    │
    v
下一次对话：新技能出现在可用列表里
```

**后台审视 agent 和主 agent 是完全独立的。** 它在后台线程运行，不阻塞用户的下一个问题。它可以调 skill_manage 工具写技能，但不会修改主对话的消息历史。

## 后台审视的触发逻辑

不是每轮对话都触发。Hermes Agent 用**工具调用计数**控制：

```python
# 每次工具调用后
self._iters_since_skill += 1

# 对话结束时检查
if self._iters_since_skill >= 10:  # 默认每 10 次工具调用触发一次
    spawn_background_review(messages_snapshot, review_skills=True)
    self._iters_since_skill = 0
```

为什么用工具调用次数而不是对话轮次？因为工具调用代表 agent 在"做事"——一段只有闲聊的对话不需要审视。连续调了 10 次工具，说明 agent 在处理一个有一定复杂度的任务，值得回顾。

在 config.yaml 里可以调整频率或关闭：

```yaml
skills:
  creation_nudge_interval: 10  # 每 10 次工具调用触发一次。设为 0 关闭。
```

## 后台审视 agent 收到的提示

```text
"Review the conversation above and consider saving or updating a skill 
if appropriate.

Focus on: was a non-trivial approach used to complete a task that required 
trial and error, or changing course due to experiential findings along 
the way, or did the user expect or desire a different method or outcome?

If a relevant skill already exists, update it with what you learned. 
Otherwise, create a new skill if the approach is reusable.
If nothing is worth saving, just say 'Nothing to save.' and stop."
```

关键词：**non-trivial**、**trial and error**、**changing course**。这些过滤条件排除了简单任务（"帮我翻译这句话"不会触发技能创建）。只有踩过坑、改过方案的经验才值得保存。

## 技能文件长什么样

agent 通过 `skill_manage(action="create")` 创建的技能文件：

```yaml
---
name: github-actions-python-ci
description: Set up GitHub Actions CI for Python projects with pytest and coverage
version: 1.0.0
---

# GitHub Actions Python CI Setup

## Steps

1. Create `.github/workflows/ci.yml`
2. Use `actions/setup-python@v5` with matrix for Python 3.10-3.12
3. Install dependencies with `pip install -e ".[dev]"` (NOT pip install -r requirements.txt)
4. Run tests: `pytest --cov --cov-report=xml`
5. Upload coverage to Codecov with `codecov/codecov-action@v4`

## Pitfalls

- **Don't use `pip install -r requirements.txt` for library projects** — it doesn't install the
  project itself. Use `pip install -e ".[dev]"` so `import mypackage` works in tests.
- **Matrix strategy needs `fail-fast: false`** — otherwise one Python version failing
  cancels all other versions' runs.
- **Codecov token is required since 2024** — add `CODECOV_TOKEN` to repo secrets.
```

注意 **Pitfalls** 部分——这就是后台审视 agent 从对话中提取的"踩坑经验"。下次遇到同样的任务，agent 加载这个技能后直接跳过这些坑。

## 技能怎么被下次对话使用

创建完技能后，下一次对话开始时：

技能的目录结构不只有一个 SKILL.md，还可以带参考文件：

```text
~/.hermes/skills/github-actions-python-ci/
├── SKILL.md                       ← 主文件：步骤 + 坑
├── references/
│   ├── codecov-setup.md           ← 参考：Codecov 详细配置
│   └── matrix-strategy.md         ← 参考：矩阵策略最佳实践
└── templates/
    └── ci.yml.template            ← 模板：可直接复制的 YAML
```

加载是**三层渐进式**的，每一层都是模型主动决定要不要往下走：

```text
Layer 1: 系统提示词里的索引（所有技能的名字 + 一行描述）
  ┌─────────────────────────────────────────────────────────┐
  │ <available_skills>                                       │
  │   github:                                                │
  │     - github-actions-python-ci: Set up GitHub Actions CI │
  │ </available_skills>                                      │
  └─────────────────────────────────────────────────────────┘
  → 模型看到索引，判断"github-actions-python-ci 和当前任务相关"

Layer 2: skill_view("github-actions-python-ci")
  → 加载 SKILL.md 完整内容
  → SKILL.md 里写着"Codecov 详细配置见 references/codecov-setup.md"

Layer 3: skill_view("github-actions-python-ci", file_path="references/codecov-setup.md")
  → 模型读到 SKILL.md 里的引用，判断需要详细配置
  → 按需加载参考文件
```

模型从 Layer 1 → Layer 2 → Layer 3 的每一步都是自己决定的——和 s18 里模型看到图片路径后决定调 vision_analyze 是同一个机制。不需要特殊逻辑，工具列表里有 `skill_view`，模型自己判断什么时候需要更多信息。

### 加载后的动作由文件类型决定

三层加载的机制是统一的——都是 `skill_view(name, file_path=...)`。但**读完之后做什么**取决于文件类型：

| 文件类型 | 加载方式 | 加载后的动作 |
|----------|----------|-------------|
| `references/*.md` | `skill_view(name, file_path="references/...")` | 理解内容，指导操作 |
| `templates/*.yml` | `skill_view(name, file_path="templates/...")` | 复制内容到目标文件 |
| `scripts/*.sh` | `skill_view(name, file_path="scripts/...")` | 通过 `terminal` 工具执行 |

scripts 的完整流程：

```text
SKILL.md 里写着：
  "Step 3: Run scripts/setup.sh to configure the environment"

模型的行为：
  1. skill_view("my-skill", file_path="scripts/setup.sh")  ← 先读脚本
  2. 理解脚本做了什么（安全吗？需要改参数吗？）
  3. terminal("bash ~/.hermes/skills/my-skill/scripts/setup.sh")  ← 通过 terminal 执行
```

**没有"自动执行"机制。** 模型先读脚本内容、判断安全，再通过 terminal 工具执行。s09 的权限系统照常工作——脚本里有危险命令会被拦截。

### 为什么没有第四层、第五层

因为从 Layer 3 开始已经是平的了——都是同一个 `skill_view(name, file_path="...")` 调用。如果 `references/api-guide.md` 里又写了"详见 references/advanced/deep-dive.md"，模型再调一次同样的 `skill_view` 就行。不需要新的机制。

```text
Layer 1: 索引        → 固定机制（提示词自动注入）
Layer 2: SKILL.md    → skill_view(name)
Layer 3+: 任意文件    → skill_view(name, file_path="...")  ← 从这里开始全是同一个调用
```

但实践中如果一个技能需要层层嵌套引用才能说清楚，通常说明**它应该拆成多个技能**：

```text
不好（一个巨型技能，层层嵌套）：
  mega-deploy/
    SKILL.md → references/docker.md → references/docker/advanced.md → ...
    模型要调 5 次 skill_view 才能拿全信息

好（拆成多个独立技能，各自 2-3 层就够）：
  deploy-docker/SKILL.md
  deploy-kubernetes/SKILL.md
  deploy-ci-pipeline/SKILL.md  ← 里面写"如果用 Docker，先加载 deploy-docker"
```

技能之间的引用靠 SKILL.md 里的文字指引。模型读到"先加载 deploy-docker"后自己去调 `skill_view("deploy-docker")`——和加载 references 是同一个决策机制。

**为什么不把所有内容一次性加载？** 省 token。如果有 100 个技能，每个带 3 个参考文件和脚本，全放进提示词就是几十万 token。渐进式让模型只加载当前任务真正需要的部分。

## 用一个完整场景走一遍

```text
=== 第一天 ===

用户: 帮我给这个项目配 GitHub Actions CI
agent: 好的，我来配置...
  → 第一版用了 pip install -r requirements.txt → 测试失败
  → 发现需要 pip install -e ".[dev]" → 修复
  → Codecov 上传失败 → 发现需要 CODECOV_TOKEN → 修复
  → 最终跑通
agent: CI 配置好了。
用户: 谢谢

  [对话结束时，工具调用计数 >= 10 → 触发后台审视]

后台审视 agent:
  "这段对话中 agent 踩了两个坑（requirements 安装方式、Codecov token），
  最终成功。这是一个非平凡的、可复用的模式。"
  → skill_manage(action="create", name="github-actions-python-ci", content="...")

用户看到: "💾 Skill 'github-actions-python-ci' created"

=== 第二天 ===

同事: 帮我给另一个项目也配 CI
agent: [系统提示词里有 github-actions-python-ci]
  → skill_view("github-actions-python-ci") → 加载完整内容
  → 直接用 pip install -e ".[dev]"（不会再犯 requirements.txt 的错）
  → 直接提醒用户添加 CODECOV_TOKEN
  → 一次就通过
```

第一天踩的坑，第二天不会再踩。这就是技能创作闭环的价值。

## 如何接到主循环里

后台审视在对话结束后触发，不在核心循环内部。

```text
核心循环正常运行
  │  每次工具调用 → _iters_since_skill += 1
  v
对话结束（模型返回最终回复）
  │
  │  _iters_since_skill >= 10 ?
  │
  是 → fork 后台审视 agent（daemon thread）
  │    └─ 分析消息快照 → skill_manage → 创建/更新技能
  │
  v
返回回复给用户（不等后台审视完成）
```

## 初学者最容易犯的错

### 1. 每轮对话都触发审视

如果 nudge_interval 设得太小（比如 1），每次工具调用都触发后台审视，浪费 API 调用，而且简单任务也会被审视——产出一堆没用的技能。

**修：默认 10 次工具调用触发一次。简单任务通常不到 10 次工具调用就结束了。**

### 2. 后台审视 agent 能修改主对话

后台审视 agent 收到的是消息**快照**（副本），不是引用。它的操作（创建技能、更新记忆）写到磁盘上的共享目录，但不会修改主对话的消息列表。

### 3. 技能文件里只写了步骤，没写坑

最有价值的不是"怎么做"（用户自己也能搜到），而是**"哪里会出错"**。后台审视的提示词专门强调 "trial and error" 和 "changing course"——就是在引导它提取踩坑经验。

### 4. 把所有技能完整内容塞进系统提示词

100 个技能 × 每个 2000 字 = 20 万字的提示词。模型处理不了，token 成本爆炸。

**修：提示词里只放技能索引（名字+描述）。模型判断相关后用 `skill_view` 按需加载。**

## 教学边界

这一章讲技能创作闭环的完整机制。

讲三件事：

1. **后台审视怎么触发** — 工具调用计数 + 对话结束时检查
2. **审视 agent 怎么决定创建/更新/跳过** — 提示词引导 + "非平凡"过滤
3. **新技能怎么在下次被使用** — 三层渐进加载（索引 → SKILL.md → 参考文件）

不讲的：

- 技能安全扫描的具体规则 → 安全机制
- 技能社区分享（Skills Hub） → 产品功能
- 技能版本管理和回滚 → 当前版本直接覆盖，没有历史
- 跨机器技能同步 → 技能存在本地 ~/.hermes/skills

## 这一章和后续章节的关系

- **s08** 定义了技能的基础格式和使用方式 → 本章在此基础上加了自动创建
- **s10** 的子 agent 机制 → 后台审视就是用子 agent 实现的
- **s07** 的记忆系统 → 后台审视同时更新记忆和技能（两者互补：记忆是事实，技能是方法）
- **s20** 的后台审视（Background Review） → 是本章的基础设施，本章是它的"技能创建"应用

## 学完这章后，你应该能回答

- 后台审视什么时候触发？每轮对话都会吗？
- 后台审视 agent 和主 agent 是同一个进程吗？它能修改主对话吗？
- 技能文件里最有价值的部分是什么？步骤还是踩坑经验？
- 为什么技能不全部放进系统提示词，而是按需加载？
- 一个用户今天创建的技能，另一个用户明天能用吗？

---

**一句话记住：agent 完成任务后，后台副本自动回顾对话、提取非平凡经验、创建技能。下次遇到类似任务，直接加载技能跳过摸索。**
