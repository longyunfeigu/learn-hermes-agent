# s25: Skill Evolution Overview

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > [ s25 ] > s26 > s27`

> *s23 improves the model itself through training. s25-s27 take a different approach -- they leave the model untouched and only change the text it receives. Skill instructions, tool descriptions, system prompts, even tool code -- all of it is text, and all of it can be systematically optimized.*

![Self-Evolution Formula](../../illustrations/en/s25-skill-evolution/01-infographic-evolution-formula.png)

## What Problem Does This Chapter Solve

Let's step back and look at the big picture.

**Everything** the agent receives at runtime -- system prompts, skill instructions, tool descriptions -- is text. The agent's performance is determined by two factors:

```text
agent performance = model capability x context text quality
```

s23 addressed the left side of this equation: **model capability** (RL training, requires GPUs, high cost).

But what about the right side -- **context text quality**? Skills auto-generated in s21 might be rough; tool descriptions written by humans might use imprecise wording that causes the model to pick the wrong tool; behavioral guidelines in the system prompt might be unclear.

These texts directly affect agent performance, yet they have never been systematically tested or improved.

This is exactly what Hermes Agent's skill evolution solves: **a "score -> rewrite -> select the best" loop that systematically optimizes all the text the agent receives.**

Key properties:
- No model training required, no GPUs needed
- Extremely low cost: ~$2-10 per optimization run
- Takes effect immediately: after the text is updated, the next conversation uses the new version

## Suggested Reading

- [`s08-skill-system.md`](./s08-skill-system.md) -- Skill fundamentals: format, discovery, loading
- [`s21-skill-creation-loop.md`](./s21-skill-creation-loop.md) -- How skills are created
- [`s23-trajectory-and-rl.md`](./s23-trajectory-and-rl.md) -- Offline training vs. text optimization comparison

## Key Terms

### What Is Text Optimization

Instead of changing model weights, you only change the **text** the model receives. By systematically trying different versions of the text, evaluating results, and keeping the better versions, you improve the agent's performance.

An analogy: you don't replace the chef (the model) -- you replace the recipe (the skill text). A better recipe lets the same chef produce better dishes.

### What Is GEPA

**Genetic-Pareto Prompt Evolution**, a paper from ICLR 2026, integrated into the DSPy framework. The core idea: read execution traces to understand **why** something failed (not just "it failed"), then make targeted text mutations.

Hermes Agent actually uses `dspy.GEPA()`. The teaching implementations in the following chapters simulate the same idea in the simplest way possible -- without depending on DSPy.

### What Is Darwinian Evolver

A framework specifically for evolving code (AGPL v3) that uses git to manage code variants. Hermes uses it in Phase 4 (code evolution). Unlike GEPA, it operates on Python source code rather than prompts.

## Four Layers of Evolution Targets

Skill evolution is not a small feature limited to skills. It is a general-purpose text optimization pipeline covering four types of targets. All four layers share the same optimization loop (score -> rewrite -> select the best); the difference lies in what is being evolved and the risk level.

### Phase 1: Skill Files (Highest Value, Lowest Risk)

Skills are plain-text task instructions -- "Step one: do X. Watch out for Y. If Z, then..."

Why start here? Easy to mutate (edit a block of markdown), easy to evaluate (have the agent use it on a task and see how it goes), and if something goes wrong, only one skill is affected.

Engine: DSPy + GEPA. Status: **Implemented**.

### Phase 2: Tool Descriptions (Medium Value, Low Risk)

Tool descriptions determine "when the model picks which tool." For example, if the description of `search_files` is not clear enough, the model might incorrectly choose `terminal(grep)` when it should have used `search_files`.

Optimization approach: generate a test set of "task -> which tool should be used" pairs, use GEPA to mutate description text, and evaluate whether the model selects the correct tool.

Constraint: each tool description must not exceed 500 characters (the full tool schema is sent on every API call).

Engine: DSPy + GEPA. Status: Planned.

### Phase 3: System Prompt Sections (High Value, High Risk)

Behavioral guidelines in the system prompt -- "when to save a memory," "when to search conversation history." Improve these and the agent's overall behavior gets better; get them wrong and every conversation is affected.

The strictest constraints: each section must not exceed 120% of the original size (to prevent prompt bloat from breaking cache boundaries), and benchmark regression checks are required.

Engine: DSPy + GEPA. Status: Planned.

### Phase 4: Tool Implementation Code (High Value, Highest Risk)

Actual Python code. Unlike the first three layers -- which modify natural language text -- this layer modifies code.

The hardest constraints: the full test suite must pass at 100%, function signatures cannot change, and `registry.register()` calls must not be touched.

Engine: Darwinian Evolver (external CLI). Status: Planned.

## The Complete Pipeline: 7 Steps

Regardless of which layer is being evolved, the pipeline has the same structure:

```text
+--------------------------------------------------+
|  1. SELECT TARGET                                |
|     Pick a skill / tool desc / prompt to improve |
|                                                  |
|  2. BUILD EVAL DATASET           <- s26 details  |
|     Generate test cases, split train/val/holdout |
|                                                  |
|  3. EVALUATE BASELINE            <- s26 details  |
|     Score the current version with fitness func  |
|                                                  |
|  4. CHECK CONSTRAINTS            <- s26 details  |
|     Does the current version pass constraints?   |
|                                                  |
|  5. OPTIMIZE (repeat N times)    <- s27 details  |
|     Collect feedback -> rewrite -> score -> keep  |
|                                                  |
|  6. VALIDATE EVOLVED             <- s27 details  |
|     Does evolved pass constraints? Holdout score?|
|                                                  |
|  7. DEPLOY                       <- s27 details  |
|     Backup -> write -> auto-active next session  |
|                                                  |
|  Steps 2-4 = "Evaluation System" (s26)           |
|  Steps 5-7 = "Optimization & Deploy" (s27)       |
+--------------------------------------------------+
```

These 7 steps map directly to Hermes' `evolve_skill.py`.

## Hermes Architecture: Separate Repo, Acting on the Agent

An important architectural decision: **the skill evolution system does not live inside the hermes-agent repo. It is a separate repository** (`NousResearch/hermes-agent-self-evolution`) that acts on hermes-agent.

```text
hermes-agent-self-evolution/        <- separate repo
├── evolution/
│   ├── core/
│   │   ├── config.py               <- configuration + hermes-agent path discovery
│   │   ├── dataset_builder.py      <- eval dataset generation
│   │   ├── external_importers.py   <- mine data from Claude Code/Copilot/Hermes
│   │   ├── fitness.py              <- fitness function (LLM-as-judge)
│   │   └── constraints.py          <- constraint gating
│   ├── skills/
│   │   ├── skill_module.py         <- wraps SKILL.md as a DSPy module
│   │   └── evolve_skill.py         <- Phase 1 main pipeline
│   ├── tools/                      <- Phase 2 (planned)
│   ├── prompts/                    <- Phase 3 (planned)
│   ├── code/                       <- Phase 4 (planned)
│   └── monitor/                    <- Phase 5 auto-trigger (planned)
├── datasets/                       <- generated eval datasets
└── tests/
```

Why a separate repo? Because skill evolution is a **development-time tool**, not a runtime feature. It reads hermes-agent's code and data, outputs improved files, and submits them via git PR -- it never runs during a user conversation.

## Starting from the Simplest Implementation

A human manually editing a skill:

```text
You: [open SKILL.md, read through it]
You: Oh, step 3 is missing error-handling instructions
You: [manually edit SKILL.md]
You: [run a few tests to see if it improved]
```

This works. But there are two problems:

### Problem 1: No Quantitative Evaluation Criteria

"Is this skill good?" is a vague judgment. After editing SKILL.md, how do you know it got better rather than worse? You need quantitative evaluation, not gut feeling.

-> **s26 solves this**: build an eval dataset + fitness function + constraint gating.

### Problem 2: No Systematic Improvement Strategy

Even if you know the score is low, how do you improve it? Tweak one thing by intuition? Should you roll back? How many rounds of edits?

-> **s27 solves this**: a collect feedback -> targeted rewrite -> score -> select the best loop + complete pipeline.

## Scope of This Chapter

This chapter only covers "what skill evolution is, why we do it, and the big picture."

It does **not** cover specific implementations -- that is the job of s26 (evaluation system) and s27 (optimization & deploy).

This chapter is the map; the next two chapters are the actual journey.

## Preview of the Next Two Chapters

| Chapter | Core Question | What You Get |
|---------|--------------|--------------|
| **s26** | How do we know if it's good? | EvalDataset + FitnessScore + ConstraintValidator + where data comes from |
| **s27** | How do we improve and ship? | SkillOptimizer + complete evolve_skill() pipeline + Phase 2-4 applications |

## After This Chapter, You Should Be Able to Answer

- What determines an agent's capability? What roles do the model and text each play?
- Why doesn't text optimization require GPUs? How does it complement RL training?
- What are the four layers of evolution targets? How are they ranked by risk?
- What are the 7 steps of the complete pipeline? Which steps belong to "evaluation" and which to "optimization"?
- Why is the skill evolution repo separate from hermes-agent? Is it a runtime feature or a development-time tool?

---

**Remember in one sentence: don't change the model -- change the text. Four layers of targets, one unified pipeline.**
