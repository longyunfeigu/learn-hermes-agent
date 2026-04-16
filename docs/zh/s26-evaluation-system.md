# s26: Evaluation System (度量体系)

`s00 > ... > s24 > s25 > [ s26 ] > s27`

> *在改进任何东西之前，先学会量化它。这一章构建度量基础设施：怎么生成测试数据、怎么给 agent 输出打分、怎么用硬约束拦住坏的变更。*

![度量体系三组件](../../illustrations/s26-evaluation-system/01-framework-evaluation-components.png)

## 这一章要解决什么问题

s25 讲了自进化的全貌和管线。但管线里有一个前提：**你得有办法量化"好不好"。**

手动改一个 SKILL.md 后，怎么知道改好了还是改坏了？靠感觉？靠跑一两个例子看看？

自进化需要的是**可重复、可量化、可自动化**的评估——同一个 skill，跑同一组测试用例，得到一个分数。改完再跑一遍，比较分数。这就是度量体系。

三个组件：

1. **评估数据集**——测什么？（SyntheticDatasetBuilder）
2. **适应度函数**——怎么打分？（FitnessScore + LLM-as-judge）
3. **约束门控**——什么情况直接拒绝？（ConstraintValidator）

## 建议联读

- [`s25-skill-evolution.md`](./s25-skill-evolution.md) — 自进化总览，本章是管线的步骤 2-4
- [`s08-skill-system.md`](./s08-skill-system.md) — 技能文件格式（被评估的对象）

## 先解释几个关键设计决策

### 为什么 expected_behavior 是 rubric 而不是精确文本

```python
# 不好：精确匹配
expected_behavior = "pip install -e '.[dev]'"

# 好：rubric 描述
expected_behavior = "应该使用可编辑模式安装而不是 requirements.txt"
```

精确文本太脆——agent 说"use `pip install -e .[dev]`"和"run editable install via pip"是同一个意思，但精确匹配会判为失败。rubric 让 LLM-as-judge 做语义理解，更接近人类评估。

### 为什么 train/val/holdout 要分三份

| 数据集 | 谁用 | 目的 |
|--------|------|------|
| **train** | 优化器每轮都看 | 收集 feedback，指导变异方向 |
| **val** | 优化器选最佳版本 | 防止过拟合 train |
| **holdout** | 最终评估时才看 | 真正的"考试"，优化过程中从不使用 |

如果只用一份数据，优化器会"背答案"——针对这几个测试用例越调越好，但换个新任务就不行了。三份数据的分离防止这种过拟合。

### 为什么 feedback 比分数更重要

```python
@dataclass
class FitnessScore:
    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    feedback: str = ""          # ← 这个字段驱动整个优化
```

分数告诉你"好不好"，feedback 告诉你"**为什么不好、怎么改**"。

s27 的优化器每轮收集 feedback，然后把 feedback 喂给 LLM 做针对性变异。没有 feedback，变异就是盲目的——随机改一改，碰运气。有了 feedback，变异是有方向的——"缺少错误处理"就加错误处理，"步骤不清晰"就改措辞。

这就是 GEPA 的核心思路：**读 trace → 理解 why → 针对性变异。** 教学版用 feedback 字段模拟同一个思路。

## 组件一：SyntheticDatasetBuilder

### 它做什么

读一段 skill 文本，让 LLM 生成一组测试用例。每个用例是一个 `(task_input, expected_behavior)` 对。

### 数据从哪来

Hermes 支持三种数据来源：

| 来源 | 实现 | 质量 | 教学版 |
|------|------|------|--------|
| **Synthetic** | LLM 读 skill → 生成用例 | 中 | 实现 |
| **SessionDB** | 从真实对话历史挖掘 + LLM 评分 | 高 | 概念介绍 |
| **Golden** | 人工手写的测试集 | 最高 | 概念介绍 |

Hermes 的 `external_importers.py`（~500 行）还能从 Claude Code、Copilot、Hermes 自身的历史对话里挖数据——解决"新用户没有 golden dataset"的冷启动问题。它做了密钥检测（防止 API key 泄露进数据集）、相关性过滤（LLM 判断一条对话是否和目标 skill 相关）、自动评分。

教学版只实现 synthetic——核心思路一样，不需要外部数据源。

### 最小实现

```python
class SyntheticDatasetBuilder:
    def generate(self, skill_text: str, num_cases: int = 15) -> EvalDataset:
        prompt = f"Read this skill and generate {num_cases} test cases..."
        response = client.chat.completions.create(model=MODEL, messages=[...])
        # 解析 JSON → 创建 EvalExample 列表
        # 打乱 → 按 60/20/20 分割为 train/val/holdout
```

## 组件二：evaluate_skill() + FitnessScore

### 它做什么

给定一个 skill 文本和一个测试用例，回答"这个 skill 在这个任务上表现如何"。

### 两步流程

```text
第一步：让 agent 用 skill 处理任务
  system prompt = skill 文本
  user message = task_input
  → 得到 agent_output

第二步：LLM-as-judge 打分
  输入 = skill + task + rubric + agent_output
  → 得到 correctness / procedure_following / conciseness / feedback
```

两次 API 调用。第一次做事，第二次评分。

### 快速启发式模式

LLM-as-judge 很准但很慢。优化过程中每轮要跑 N 个测试用例 × M 次迭代——全用 LLM 太贵。

Hermes 的 `skill_fitness_metric()` 用 keyword overlap 做快速代理评分：

```python
expected_words = set(expected_behavior.lower().split())
skill_words = set(skill_text.lower().split())
overlap = len(expected_words & skill_words) / len(expected_words)
score = 0.3 + 0.7 * overlap
```

不精确，但够用——优化过程中用它加速，最终评估时切回 LLM-as-judge。

## 组件三：ConstraintValidator

### 它做什么

进化后的文本必须通过四个硬检查。**任何一条不过就拒绝**，不管分数多高。

### 四个约束

| 约束 | 规则 | 为什么 |
|------|------|--------|
| `size_limit` | ≤ 15KB | 防止技能膨胀——LLM 倾向于"加更多说明"来提分 |
| `growth_limit` | ≤ 原始大小的 120% | 防止一次进化暴涨 |
| `non_empty` | 不能为空 | 变异可能产生空文本 |
| `skill_structure` | 必须以 `#` 或 `---` 开头 | 保持合法的 markdown 格式 |

这四个约束直接对齐 Hermes 的 `evolution/core/constraints.py`。

Hermes 还有一些教学版不实现的约束：
- pytest 全量通过（代码进化用）
- Benchmark 回归检查（TBLite 分数不能下降超过 2%）
- 语义保真度（不能偏离原始目的）
- 缓存兼容性（不能导致中间对话的缓存失效）

## 场景走读：评估一个 skill

```text
=== 输入 ===
skill_text: "# GitHub Actions CI\n1. Create .github/workflows/ci.yml\n2. Use pip install..."
test_case: EvalExample(
    task_input="帮我给 Python 项目配 CI",
    expected_behavior="应该用 pip install -e 而不是 pip install -r，提到 Codecov token"
)

=== 第一步：agent 执行 ===
system: "Follow these instructions:\n# GitHub Actions CI\n1. Create..."
user: "帮我给 Python 项目配 CI"
→ agent_output: "好的，我来帮你配置...\n1. 创建 ci.yml...\n使用 pip install -r requirements.txt..."

=== 第二步：LLM-as-judge 打分 ===
输入: skill + task + rubric + agent_output
→ {
    "correctness": 0.4,       // 用了 pip install -r，不是 -e
    "procedure_following": 0.7, // 大部分步骤遵循了
    "conciseness": 0.8,       // 回答简洁
    "feedback": "Skill 没有明确说不要用 pip install -r，应该在步骤 2 加上警告"
  }
→ composite = 0.5*0.4 + 0.3*0.7 + 0.2*0.8 = 0.57

=== 约束检查 ===
size_limit: 800/15000 chars → OK
non_empty: OK
skill_structure: starts with # → OK
```

注意 feedback 的内容："Skill 没有明确说不要用 pip install -r"——这不是对 agent 的反馈，而是对 **skill 文本本身**的改进建议。s27 的优化器会用这个 feedback 来重写 skill。

## 初学者最容易犯的错

### 1. 用精确匹配做评估

"输出必须包含 `pip install -e`" → agent 说了同义的表达但不完全匹配 → 判为失败。

**修：用 rubric 描述 + LLM-as-judge，让评估做语义理解。**

### 2. 约束门控放在评估之后

先跑完评估（贵），再发现进化后的 skill 超过 15KB（约束不通过）。浪费了评估的 API 调用。

**修：约束检查放在评估之前。Hermes 先检查 baseline 约束，再跑优化，最后检查进化后约束。**

### 3. 评估数据集太小

3 个测试用例 → 优化器很容易"背答案"过拟合。

**修：至少 12-15 个用例，按 60/20/20 分三份。GEPA 最少能用 3 个例子工作，但更多更好。**

## 教学边界

这一章讲度量体系的三个组件。

讲的：
- 评估数据集怎么生成（synthetic）
- 适应度函数怎么打分（LLM-as-judge + 启发式）
- 约束门控怎么拦截（四个硬检查）

不讲的：
- SessionDB mining 和 external importers 的完整实现 → 概念已介绍
- DSPy Signature 的具体 API → 教学版直接用 chat completion
- Benchmark gating（TBLite / YC-Bench） → 需要完整运行环境

## 这一章和其他章节的关系

- **s25** 是总览 → 本章是步骤 2-4 的具体实现
- **s27** 是步骤 5-7 → 它消费本章产出的 FitnessScore 和 ConstraintResult
- **s23** 的 `extract_tool_stats()` → 可以作为评估信号的来源之一（哪些工具成功/失败）

## 学完这章后，你应该能回答

- 为什么 expected_behavior 用 rubric 而不是精确文本？
- train/val/holdout 三份数据各有什么用？少了哪一份会怎样？
- FitnessScore 的 feedback 字段给谁用？为什么比分数更重要？
- 约束门控解决什么问题？为什么 size_limit 是硬门控？
- 快速启发式评分和 LLM-as-judge 各用在什么场景？

---

**一句话记住：度量三件套——数据集告诉你测什么，适应度函数告诉你好不好，约束门控告诉你能不能上线。**
