# s08: Skill System (技能系统)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > [ s08 ] > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *工具是硬编码在代码里的能力，技能是 agent 自己管理的经验。*

## 这一章要解决什么问题

到了 `s07`，agent 有了跨会话记忆。但 memory 保存的是**声明性知识**（事实、偏好、约定）。

另一类知识它存不了：

> "做这类任务的时候，应该按什么步骤来？有哪些注意事项？"

比如：

- 做代码审查，要检查哪些项
- 做数据分析，怎么处理缺失值
- 做 MCP server 开发，标准目录结构是什么

这些是**程序性知识** — 不是一条事实，而是一整套做法。

如果把它们塞进 system prompt，很快就会臃肿到不可维护。如果不保存，agent 每次遇到同类任务都要从零摸索。

所以需要技能系统：

**让 agent 把成功的做法沉淀成文件，下次遇到同类任务时按需加载。**

## 先解释几个名词

### 什么是 skill

一份围绕某类任务的可复用说明书。存储为 `SKILL.md` 文件。

它通常会告诉 agent：

- 什么时候该用它
- 做这类任务时有哪些步骤
- 有哪些注意事项
- 可以参考哪些模板或示例

### skill 和 tool 的区别

- `tool`：硬编码在 Python 里的能力。开发者写的。添加新工具需要写代码。
- `skill`：markdown 文件。agent 自己可以创建、编辑、删除。不需要改代码。

技能通过已有的工具来执行。比如一个"数据分析"技能的内容可能是"用终端执行 pandas 脚本"——技能描述做法，工具提供手段。

### skill 和 memory 的区别

- `memory`：声明性知识。"用户偏好 tabs"、"项目用 pytest"。
- `skill`：程序性知识。"做代码审查时按这个清单检查"。

一个简单判断法：

- 一条事实 → memory
- 一套做法 → skill

### 什么是 progressive disclosure（渐进展示）

技能系统分三层展示：

1. **目录层**：只展示名称和描述（几十个技能只占几百 token）
2. **正文层**：模型决定需要时，加载 SKILL.md 的完整内容
3. **附件层**：技能目录里的参考文件、模板、脚本，需要时再加载

平时 system prompt 里只放目录层。正文和附件只在需要时通过工具加载进对话。

## 最小心智模型

```text
system prompt
  |
  +-- Skills available:
      - code-review: Code review checklist
      - data-analysis: CSV/DataFrame analysis workflow
      - mcp-builder: Build an MCP server

当模型判断需要某个技能时：

skill_view("code-review")
   |
   v
tool_result: SKILL.md 完整正文
   |
   v
agent 按照技能内容执行任务
```

但 Hermes Agent 比这多了一步：**agent 不只能读取技能，还能创建和编辑技能。**

```text
agent 完成了一个数据分析任务
   |
   v
agent 判断这套做法值得复用
   |
   v
skill_manage(action="create", name="data-analysis", content="...")
   |
   v
~/.hermes/skills/data-analysis/SKILL.md 被创建

下次遇到类似任务时：

skill_view("data-analysis") → 加载做法 → 直接按步骤执行
```

这是 Hermes Agent 和大多数 agent 框架不同的地方：**技能不全是预先定义的，有一部分是 agent 从经验中沉淀出来的。**

## 关键数据结构

### 1. SKILL.md 格式

```markdown
---
name: code-review
description: Checklist for reviewing code changes
version: 1.0.0
---

# Code Review

## Steps
1. Check for obvious bugs
2. Verify test coverage
3. Review naming conventions
...
```

frontmatter（`---` 之间的部分）是结构化元数据。正文是自由 markdown。

### 2. 技能目录结构

```text
~/.hermes/skills/
├── code-review/
│   └── SKILL.md
├── data-analysis/
│   ├── SKILL.md
│   ├── references/
│   │   └── pandas-cheatsheet.md
│   └── templates/
│       └── report-template.md
└── software-development/
    └── git-workflow/
        └── SKILL.md
```

每个技能是一个目录，里面必须有 `SKILL.md`。可以有 `references/`、`templates/`、`scripts/`、`assets/` 子目录存附件。

### 3. 技能可用性状态

```text
available     — 可以直接使用
setup_needed  — 缺少依赖（比如某个环境变量没配）
unsupported   — 当前平台不支持
```

技能可以声明依赖（环境变量、命令行工具）和平台限制（只在 macOS 上可用）。不满足条件的技能不会出现在目录里。

## 最小实现

### 第一步：扫描技能目录

```python
def discover_skills(skills_dir):
    skills = {}
    for skill_dir in skills_dir.iterdir():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            meta, body = parse_frontmatter(skill_md.read_text())
            skills[meta["name"]] = {
                "name": meta["name"],
                "description": meta.get("description", ""),
                "body": body,
                "path": skill_dir,
            }
    return skills
```

### 第二步：把技能目录放进 system prompt

```python
# 只放名称和描述，不放正文
skills_index = "\n".join(
    f"- {s['name']}: {s['description']}"
    for s in skills.values()
)
prompt_parts.append(f"# Available Skills\n{skills_index}")
```

这一步的关键思想是：

> 目录很便宜（几百 token），正文很贵（可能几千 token）。平时只放目录。

### 第三步：提供查看工具

```python
def skill_view(name, file=None):
    skill = skills.get(name)
    if not skill:
        return f"Skill '{name}' not found"
    if file:
        # 加载附件
        return (skill["path"] / file).read_text()
    return skill["body"]
```

### 第四步：提供管理工具

```python
def skill_manage(action, name, content=None):
    if action == "create":
        skill_dir = skills_dir / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)
        return f"Created skill: {name}"
    
    if action == "edit":
        (skills_dir / name / "SKILL.md").write_text(content)
        return f"Updated skill: {name}"
    
    if action == "delete":
        shutil.rmtree(skills_dir / name)
        return f"Deleted skill: {name}"
```

这一步是 Hermes Agent 的独特之处：agent 不只是技能的消费者，也是技能的创建者。

## 它如何接到主循环里

这一章以后，system prompt 不再只有身份、记忆和项目规则。

它开始长出一个新段落：**可用技能目录。**

而消息流里会出现新的按需注入内容：**某个技能的完整正文。**

也就是说，系统输入现在分成两层：

```text
稳定层（每轮都在）：
  身份、记忆、项目规则、工具定义、技能目录

按需层（需要时才加载）：
  某个技能的 SKILL.md 正文
  某个技能的附件文件
```

这个"稳定层 + 按需层"的分法很重要。因为稳定层决定了 prompt cache 的命中率 — 稳定层越固定，缓存越有效。按需层的内容进入的是 tool_result，不影响 system prompt。

这也是为什么技能正文不应该塞进 system prompt：它会让稳定层变得不稳定。

## Hermes Agent 在这里的独特设计

### 1. agent 自己创建和编辑技能

大多数 agent 框架的 skill 是只读的（开发者预先写好）。Hermes Agent 让 agent 通过 `skill_manage` 工具自己创建、编辑和删除技能。

这意味着 agent 可以从经验中学习："上次这样做效果很好 → 把做法存成技能 → 下次直接用"。

### 2. 安全扫描

agent 创建的技能和从 Hub 安装的技能一样需要安全扫描。系统会检查 SKILL.md 里有没有可疑的命令注入或恶意指令。

### 3. 多来源技能

技能来自多个来源：

- **内置技能**：项目自带的 `skills/` 目录
- **用户技能**：`~/.hermes/skills/` 下 agent 或用户创建的
- **Hub 安装**：从 agentskills.io、GitHub 等来源安装的
- **外部目录**：config 里配置的额外技能目录

多来源同名时，用户技能优先。

### 4. 技能改进 nudge

agent 每隔一定轮数的工具调用会被提醒"审视一下是否有技能值得创建或改进"。这是一个 nudge，不是自动操作。

### 5. 二层缓存

技能目录的 system prompt 片段有两层缓存：进程内 LRU 缓存 + 磁盘快照。避免每次 API 调用都重新扫描文件系统。

## skill、memory、SOUL.md、HERMES.md 的边界

| | skill | memory | SOUL.md | HERMES.md |
|---|---|---|---|---|
| 是什么 | 某类任务的做法 | 跨会话的事实 | 人设 | 项目规则 |
| 例子 | "代码审查清单" | "用户偏好 tabs" | "你是简洁的助手" | "用 pytest 跑测试" |
| 谁写 | agent 或开发者 | agent | 用户 | 开发者 |
| 在 prompt 里的位置 | 目录在 system prompt，正文按需加载 | 冻结在 system prompt 里 | system prompt 最前面 | system prompt 里 |
| 大小 | 每个几百到几千字 | 有字符限制 | 通常很短 | 按项目而定 |

## 初学者最容易犯的错

### 1. 把所有 skill 正文永远塞进 system prompt

20 个技能的正文可能有几万 token。应该只放目录，按需加载正文。

### 2. 把 skill 和 memory 混成一类

skill 是"怎么做"，memory 是"知道什么"。一个是程序，一个是事实。

### 3. 让 agent 创建的技能没有安全检查

agent 生成的 SKILL.md 可能包含危险指令。需要和外部安装的技能一样做安全扫描。

### 4. 技能目录信息写得太弱

只有名字没有描述，模型不知道什么时候该加载它。描述要足够清楚地告诉模型"这个技能适合什么场景"。

### 5. 把 skill 当成绝对规则

skill 更像"推荐做法"，不是每次都必须严格遵守。模型应该能根据实际情况灵活调整。

## 教学边界

这章先守住三件事：

1. **渐进展示**：目录在 prompt 里，正文按需加载
2. **agent 可写**：不只是消费者，也是创建者
3. **和 memory 的边界**：事实 vs 做法

刻意停住的：Hub 安装的完整流程、多来源优先级合并、安全扫描的具体规则、缓存失效策略。

如果读者能做到"agent 把一个成功的做法存成技能文件，下次遇到同类任务时加载它"，这一章就达标了。

## 学完这章后，你应该能回答

- skill 和 tool 的区别是什么？
- skill 和 memory 的区别是什么？
- 为什么 skill 正文不应该永远放在 system prompt 里？
- agent 自己创建的技能需要什么额外的安全考虑？
- 渐进展示的三层分别是什么？

---

**一句话记住：技能是 agent 的程序性记忆 — 不是"知道什么"而是"怎么做"。Hermes Agent 的 agent 不只能用技能，还能从经验中创建和改进技能。**
