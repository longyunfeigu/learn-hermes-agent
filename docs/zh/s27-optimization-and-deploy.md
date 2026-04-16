# s27: Optimization & Deploy (优化与部署)

`s00 > ... > s24 > s25 > s26 > [ s27 ]`

> *s26 教了怎么量化"好不好"。这一章把量化能力组装成一个自动优化循环：收集 feedback、变异、评估、选择、部署。完整管线，从输入一个 skill 名字到输出一个更好的版本。*

![优化闭环](../../illustrations/s27-optimization-deploy/01-flowchart-optimization-loop.png)

## 这一章要解决什么问题

s26 给了你三个工具：SyntheticDatasetBuilder（生成测试数据）、evaluate_skill（打分）、ConstraintValidator（门控）。

但这三个工具是散的。你需要手动把它们串起来：生成数据 → 跑评估 → 看分数 → 手动改 skill → 再跑评估 → 检查约束 → ...

这一章把手动过程自动化——**一行命令，输入 skill 名字，输出更好的版本。**

## 建议联读

- [`s25-skill-evolution.md`](./s25-skill-evolution.md) — 自进化总览，7 步管线
- [`s26-evaluation-system.md`](./s26-evaluation-system.md) — 度量三件套（本章的消费者）

## 优化循环：收集反馈 → 针对性改写 → 打分 → 择优

这是整个自进化管线的核心——s25 管线图里的步骤 5。

```text
                 ┌─────────────────┐
                 │  当前 skill 版本  │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
          ┌──────│ 在 train set 评估 │
          │      │ 收集 feedback     │
          │      └────────┬────────┘
          │               │
          │      ┌────────▼────────┐
          │      │ LLM 基于 feedback │
          │      │ 重写 skill 文本   │
          │      └────────┬────────┘
          │               │
          │      ┌────────▼────────┐
          │      │ 在 val set 评估   │
     重复 N 轮   │ 新版本分数更高？   │
          │      └────┬───────┬────┘
          │           │       │
          │          是      否
          │           │       │
          │      保留新版  回退到当前版
          │           │       │
          └───────────┘       │
                              │
                 ┌────────────▼────┐
                 │  最佳版本出循环   │
                 └─────────────────┘
```

### 为什么用 feedback 驱动变异而不是随机变异

随机变异：把 skill 文本交给 LLM 说"改改"——LLM 不知道该改什么，随机加点内容、删点内容，大概率越改越差。

Feedback 驱动变异：先跑评估拿到具体反馈（"缺少错误处理步骤""步骤 3 不够清晰"），然后让 LLM 基于这些反馈改——有方向，命中率高。

这就是 GEPA 和传统遗传算法的区别。传统 GA 靠随机变异 + 选择压力慢慢逼近；GEPA 读执行 trace 理解原因，做针对性修改。教学版用 feedback 字段模拟同一个思路。

## 变异提示词

```python
_MUTATE_PROMPT = (
    "You are optimizing an AI agent skill file...\n\n"
    "CURRENT SKILL TEXT:\n{current_text}\n\n"
    "PERFORMANCE FEEDBACK from evaluation:\n{feedback}\n\n"
    "Based on this feedback, rewrite the skill text to address the issues.\n"
    "Keep the same general purpose and structure, but improve:\n"
    "- Clarity of instructions\n"
    "- Handling of edge cases mentioned in feedback\n"
    "- Step-by-step procedure\n\n"
    "Return ONLY the improved skill text, no explanations."
)
```

注意几个设计细节：
- "Keep the same general purpose and structure"——不要大改，只做针对性改进
- "Return ONLY the improved skill text"——不要解释，直接给新版本
- feedback 截断到 2000 字符——防止提示词过长

## 完整管线：evolve_skill()

s25 的 7 步管线，现在变成可执行的代码：

```python
def evolve_skill(skill_name, iterations=5, use_llm=True):
    # 1. 查找并加载 skill
    skill_file = SKILLS_DIR / skill_name / "SKILL.md"
    raw = skill_file.read_text()
    metadata, body = _parse_frontmatter(raw)

    # 2. 生成评估数据集（s26 的 SyntheticDatasetBuilder）
    dataset = SyntheticDatasetBuilder().generate(body, num_cases=12)

    # 3. 验证 baseline 约束（s26 的 ConstraintValidator）
    validator = ConstraintValidator()
    validator.validate_all(body)

    # 4. 运行优化器
    optimizer = SkillOptimizer(use_llm=use_llm)
    result = optimizer.optimize(body, dataset, iterations=iterations)

    # 5. 验证进化后约束
    evolved_checks = validator.validate_all(result.evolved_text, baseline=body)

    # 6. 在 holdout set 上评估（最终考试）
    holdout_score = optimizer._score_on_split(result.evolved_text, dataset.holdout)

    # 7. 备份原始 + 写入进化版
    if result.improvement > 0:
        # 备份到 backups/SKILL_<timestamp>.md.bak
        # 写入新版本
```

## 场景走读：从命令行进化一个 skill

```text
$ python agents/s27_optimization_and_deploy.py --evolve github-actions-python-ci

  [evolve] loaded: github-actions-python-ci (1200 chars)
  [evolve] generating eval dataset...
  [evolve] dataset: 7t/2v/3h

  [evolve] baseline size_limit: OK (1200/15000)
  [evolve] baseline non_empty: OK
  [evolve] baseline skill_structure: OK

  [evolve] running optimizer (5 iterations)...
  [evolve] baseline score: 0.520

  [evolve] iter 1: 0.520 -> 0.610 (+0.090)
  [evolve] iter 2: 0.610 -> 0.610 (no improvement)
  [evolve] iter 3: 0.610 -> 0.680 (+0.070)
  [evolve] iter 4: no change, skipping
  [evolve] iter 5: 0.680 -> 0.680 (no improvement)

  [evolve] evolved size_limit: OK (1450/15000)
  [evolve] evolved growth_limit: +20.8% FAIL
  → 约束检查失败，不部署
```

约束失败是正常的——LLM 倾向于加内容。这正是 growth_limit 存在的意义。

## 部署策略：教学版 vs Hermes 实际

| 方面 | 教学版 | Hermes 实际 |
|------|--------|------------|
| 备份 | 文件副本（`backups/SKILL_<ts>.md.bak`） | git 分支（`evolve/<target>-<ts>`） |
| 部署 | 直接覆盖 SKILL.md | 创建 PR，人工 review 后合入 |
| 回滚 | 手动从备份恢复 | `git revert` |
| 审批 | 无 | PR review 必须通过 |

教学版简化是合理的——教的是优化循环本身，不是 git 工作流。但生产环境**必须**用 PR——自动生成的改动需要人类审查。

## Hermes 实际用的 DSPy + GEPA

教学版的 SkillOptimizer 和 Hermes 的 evolve_skill.py 在结构上一一对应：

```python
# 教学版
optimizer = SkillOptimizer(use_llm=False)
result = optimizer.optimize(skill_text, dataset, iterations=5)

# Hermes 实际
optimizer = dspy.GEPA(metric=skill_fitness_metric, max_steps=10)
optimized_module = optimizer.compile(baseline_module, trainset=trainset, valset=valset)
```

GEPA 多了什么？
- **反射分析**：不只看分数，还读完整的执行 trace 理解失败原因
- **Pareto 优化**：同时优化多个维度（正确性 vs 简洁性），找帕累托前沿
- **Population 管理**：维护多个候选版本，不只是 current vs best

但核心思路一样：打分 → 理解为什么差 → 针对性改写 → 择优。

## Phase 2-4 怎么用同一套机制

本章实现了 Phase 1（skill 进化）。Phase 2-4 用同一个「打分 → 改写 → 择优」循环，只是换了进化对象和评估方式。

### Phase 2: Tool description 进化

```python
# 概念代码（Hermes 计划中，教学版不实现）
# 进化对象：工具描述文本
target_text = registry._tools["search_files"].schema["description"]

# 评估方式：工具选择准确率
# "给定任务描述，agent 是否选了正确的工具？"
eval_dataset = generate_tool_selection_dataset()  # (task, correct_tool) pairs

# 约束：每个描述 ≤ 500 字符
constraints = ConstraintValidator(max_size=500)
```

### Phase 3: System prompt section 进化

```python
# 进化对象：提示词的某个 section（比如"记忆使用指南"）
target_text = MEMORY_GUIDANCE_SECTION

# 评估方式：行为测试
# "agent 是否在该保存记忆的时候保存了？"
eval_dataset = generate_behavioral_test_cases()

# 约束：section 不能比原版大 20%（防止提示词缓存失效）
constraints = ConstraintValidator(max_growth=0.2)
```

### Phase 4: Tool code 进化

```python
# 进化对象：Python 源码（用 Darwinian Evolver，不是 GEPA）
# 评估方式：pytest 全量通过 + benchmark 不回归
# 约束最严：函数签名不能改，error handling 不能删
```

**核心不变：打分 → 改写 → 择优。变的只是"评什么"和"约束多严"。**

## 初学者最容易犯的错

### 1. 迭代次数越多越好

不一定。3 次迭代可能就找到最佳版本了，第 4-10 次都在做无用功。而且每次迭代都有 API 成本。

**修：观察 improvement 曲线。连续 2-3 次 no improvement 就可以提前停止。**

### 2. 进化后直接用，不跑 holdout

优化器在 train + val 上反复调过了——分数可能有偏。holdout 是从未被优化器看过的数据，是真正的"考试"。

**修：永远在 holdout 上做最终评估。如果 holdout 分数比 baseline 差，别部署。**

### 3. 忽略约束检查

"分数提高了 0.15，但大小超了 20%"——分数诱人，但技能膨胀会影响所有使用它的对话。

**修：约束是硬门控。不管分数多好，约束不过就不部署。**

## 教学边界

讲的：
- 优化循环的完整实现（收集反馈 → 针对性改写 → 打分 → 择优）
- 完整管线（evolve_skill 7 步）
- Phase 2-4 的概念和差异
- Hermes 实际实现的对比

不讲的：
- DSPy/GEPA 的 API 使用 → 外部框架
- Darwinian Evolver 的 git organism 机制 → Phase 4 专属
- 自动触发（Phase 5）→ 目前全是手动 CLI
- PR 创建和 code review 流程 → git 工作流，不是进化本身

## 这一章和其他章节的关系

- **s25** 是地图 → 本章是步骤 5-7 的具体实现
- **s26** 是度量工具 → 本章消费它们（SyntheticDatasetBuilder + evaluate_skill + ConstraintValidator）
- **s08** 的 `skill_manage` → 本章用它做最终部署
- **s23** 改模型 + 本章改文本 = agent 的两条进化路径

## 学完这章后，你应该能回答

- 优化循环的四步是什么？为什么用 feedback 而不是随机变异？
- evolve_skill() 的 7 步分别做什么？哪几步用了 s26 的组件？
- 如果优化后约束检查失败，应该怎么办？
- Phase 2（工具描述）和 Phase 1（技能）的评估方式有什么不同？
- 教学版和 Hermes 的 GEPA 核心思路一样吗？差在哪里？

---

**一句话记住：收集反馈 → 让 LLM 针对性改写 → 打分 → 更好就留，否则丢。循环 N 轮，通过约束就部署。**
