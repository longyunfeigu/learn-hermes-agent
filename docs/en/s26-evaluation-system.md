# s26: Evaluation System

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > [ s26 ] > s27`

> *Before improving anything, learn to measure it. This chapter builds the evaluation infrastructure: how to generate test data, how to score agent output, and how to use hard constraints to block bad changes.*

![Evaluation System Components](../../illustrations/en/s26-evaluation-system/01-framework-evaluation-components.png)

## What Problem Does This Chapter Solve

s25 laid out the full picture of skill evolution and its pipeline. But the pipeline has a prerequisite: **you need a way to quantify "good or bad."**

After manually editing a SKILL.md, how do you know it got better or worse? By gut feeling? By running one or two examples?

What skill evolution requires is **repeatable, quantifiable, automatable** evaluation -- run the same skill against the same set of test cases and get a score. Edit it, run again, compare scores. That is the evaluation system.

Three components:

1. **Eval dataset** -- What to test? (SyntheticDatasetBuilder)
2. **Fitness function** -- How to score? (FitnessScore + LLM-as-judge)
3. **Constraint gating** -- When to reject outright? (ConstraintValidator)

## Suggested Reading

- [`s25-skill-evolution.md`](./s25-skill-evolution.md) -- Skill evolution overview; this chapter covers steps 2-4 of the pipeline
- [`s08-skill-system.md`](./s08-skill-system.md) -- Skill file format (the object being evaluated)

## Key Design Decisions

### Why expected_behavior Is a Rubric, Not Exact Text

```python
# Bad: exact matching
expected_behavior = "pip install -e '.[dev]'"

# Good: rubric description
expected_behavior = "Should use editable install instead of requirements.txt"
```

Exact text is too brittle -- "use `pip install -e .[dev]`" and "run editable install via pip" mean the same thing, but exact matching would mark it as a failure. A rubric lets LLM-as-judge do semantic understanding, which is much closer to human evaluation.

### Why Split into train/val/holdout

| Dataset | Used By | Purpose |
|---------|---------|---------|
| **train** | Optimizer sees it every round | Collect feedback, guide mutation direction |
| **val** | Optimizer picks the best version | Prevent overfitting to train |
| **holdout** | Used only during final evaluation | The real "exam" -- never used during optimization |

If you use only one dataset, the optimizer will "memorize the answers" -- it keeps tuning to ace those specific test cases but falls apart on new tasks. The three-way split prevents this kind of overfitting.

### Why Feedback Matters More Than Scores

```python
@dataclass
class FitnessScore:
    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    feedback: str = ""          # <- this field drives the entire optimization
```

Scores tell you "good or bad." Feedback tells you **"why it's bad and how to fix it."**

In s27, the optimizer collects feedback each round and feeds it to the LLM for targeted mutation. Without feedback, mutation is blind -- random edits, hoping for the best. With feedback, mutation has direction -- "missing error handling" leads to adding error handling; "steps are unclear" leads to rewriting for clarity.

This is the core idea behind GEPA: **read the trace -> understand why -> mutate with purpose.** The teaching version simulates the same idea using the feedback field.

## Component 1: SyntheticDatasetBuilder

### What It Does

Reads a skill text and asks an LLM to generate a set of test cases. Each case is a `(task_input, expected_behavior)` pair.

### Where the Data Comes From

Hermes supports three data sources:

| Source | Implementation | Quality | Teaching Version |
|--------|---------------|---------|-----------------|
| **Synthetic** | LLM reads skill -> generates cases | Medium | Implemented |
| **SessionDB** | Mine from real conversation history + LLM scoring | High | Concept only |
| **Golden** | Manually written test sets | Highest | Concept only |

Hermes' `external_importers.py` (~500 lines) can also mine data from Claude Code, Copilot, and Hermes' own conversation history -- solving the cold-start problem of "new users don't have a golden dataset." It performs secret detection (preventing API keys from leaking into datasets), relevance filtering (LLM judges whether a conversation relates to the target skill), and automatic scoring.

The teaching version only implements synthetic generation -- the core idea is the same and no external data source is needed.

### Minimal Implementation

```python
class SyntheticDatasetBuilder:
    def generate(self, skill_text: str, num_cases: int = 15) -> EvalDataset:
        prompt = f"Read this skill and generate {num_cases} test cases..."
        response = client.chat.completions.create(model=MODEL, messages=[...])
        # Parse JSON -> create EvalExample list
        # Shuffle -> split 60/20/20 into train/val/holdout
```

## Component 2: evaluate_skill() + FitnessScore

### What It Does

Given a skill text and a test case, answers "how well does this skill perform on this task?"

### Two-Step Process

```text
Step 1: Have the agent process the task using the skill
  system prompt = skill text
  user message = task_input
  -> produces agent_output

Step 2: LLM-as-judge scores the output
  input = skill + task + rubric + agent_output
  -> produces correctness / procedure_following / conciseness / feedback
```

Two API calls. The first one does the work; the second one evaluates it.

### Fast Heuristic Mode

LLM-as-judge is accurate but slow. During optimization, each round needs to run N test cases x M iterations -- using LLM for all of them is too expensive.

Hermes' `skill_fitness_metric()` uses keyword overlap as a fast proxy score:

```python
expected_words = set(expected_behavior.lower().split())
skill_words = set(skill_text.lower().split())
overlap = len(expected_words & skill_words) / len(expected_words)
score = 0.3 + 0.7 * overlap
```

Not precise, but good enough -- use it to speed up the optimization loop, then switch back to LLM-as-judge for the final evaluation.

## Component 3: ConstraintValidator

### What It Does

Evolved text must pass four hard checks. **If any single check fails, the change is rejected** -- no matter how high the score.

### The Four Constraints

| Constraint | Rule | Rationale |
|-----------|------|-----------|
| `size_limit` | <= 15KB | Prevent skill bloat -- LLMs tend to "add more instructions" to boost scores |
| `growth_limit` | <= 120% of original size | Prevent a single evolution round from exploding in size |
| `non_empty` | Must not be empty | Mutation can produce empty text |
| `skill_structure` | Must start with `#` or `---` | Ensure valid markdown format |

These four constraints map directly to Hermes' `evolution/core/constraints.py`.

Hermes also has additional constraints not implemented in the teaching version:
- Full pytest suite must pass (for code evolution)
- Benchmark regression check (TBLite score must not drop more than 2%)
- Semantic fidelity (must not drift from the original purpose)
- Cache compatibility (must not invalidate mid-conversation caches)

## Walkthrough: Evaluating a Skill

```text
=== Input ===
skill_text: "# GitHub Actions CI\n1. Create .github/workflows/ci.yml\n2. Use pip install..."
test_case: EvalExample(
    task_input="Help me set up CI for a Python project",
    expected_behavior="Should use pip install -e instead of pip install -r, mention Codecov token"
)

=== Step 1: Agent Execution ===
system: "Follow these instructions:\n# GitHub Actions CI\n1. Create..."
user: "Help me set up CI for a Python project"
-> agent_output: "Sure, I'll help you configure...\n1. Create ci.yml...\nUse pip install -r requirements.txt..."

=== Step 2: LLM-as-judge Scoring ===
input: skill + task + rubric + agent_output
-> {
    "correctness": 0.4,       // used pip install -r, not -e
    "procedure_following": 0.7, // followed most steps
    "conciseness": 0.8,       // response was concise
    "feedback": "Skill does not explicitly say not to use pip install -r; should add a warning at step 2"
  }
-> composite = 0.5*0.4 + 0.3*0.7 + 0.2*0.8 = 0.57

=== Constraint Check ===
size_limit: 800/15000 chars -> OK
non_empty: OK
skill_structure: starts with # -> OK
```

Note the content of the feedback: "Skill does not explicitly say not to use pip install -r" -- this is not feedback for the agent; it is an improvement suggestion for **the skill text itself**. The optimizer in s27 will use this feedback to rewrite the skill.

## Common Beginner Mistakes

### 1. Using Exact Matching for Evaluation

"Output must contain `pip install -e`" -> the agent says something semantically equivalent but not an exact match -> marked as failure.

**Fix: Use rubric descriptions + LLM-as-judge so that evaluation performs semantic understanding.**

### 2. Running Constraint Gating After Evaluation

Run the full evaluation first (expensive), then discover the evolved skill exceeds 15KB (constraint fails). You just wasted those evaluation API calls.

**Fix: Run constraint checks before evaluation. Hermes checks baseline constraints first, then runs optimization, then checks evolved constraints.**

### 3. Eval Dataset Too Small

3 test cases -> the optimizer easily "memorizes the answers" and overfits.

**Fix: Use at least 12-15 cases, split 60/20/20 into three parts. GEPA can work with as few as 3 examples, but more is better.**

## Scope of This Chapter

This chapter covers the three components of the evaluation system.

Covered:
- How to generate eval datasets (synthetic)
- How the fitness function scores (LLM-as-judge + heuristic)
- How constraint gating rejects bad changes (four hard checks)

Not covered:
- Full implementation of SessionDB mining and external importers -> concept introduced
- DSPy Signature's specific API -> teaching version uses chat completions directly
- Benchmark gating (TBLite / YC-Bench) -> requires full runtime environment

## How This Chapter Relates to Others

- **s25** is the overview -> this chapter implements steps 2-4
- **s27** is steps 5-7 -> it consumes the FitnessScore and ConstraintResult produced here
- **s23**'s `extract_tool_stats()` -> can serve as one source of evaluation signals (which tools succeeded/failed)

## After This Chapter, You Should Be Able to Answer

- Why does expected_behavior use a rubric instead of exact text?
- What is each of the three dataset splits (train/val/holdout) used for? What happens if you drop one?
- Who consumes the feedback field in FitnessScore? Why is it more important than scores?
- What problem does constraint gating solve? Why is size_limit a hard gate?
- When do you use the fast heuristic scoring vs. LLM-as-judge?

---

**Remember in one sentence: the evaluation trio -- the dataset tells you what to test, the fitness function tells you how good it is, and the constraint gate tells you whether it can ship.**
