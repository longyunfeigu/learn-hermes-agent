# s27: Optimization & Deploy

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > [ s27 ]`

> *s26 taught how to quantify "good or bad." This chapter assembles that measurement capability into an automated optimization loop: collect feedback, mutate, evaluate, select, deploy. A complete pipeline, from inputting a skill name to outputting a better version.*

![Optimization Loop](../../illustrations/en/s27-optimization-deploy/01-flowchart-optimization-loop.png)

## What Problem Does This Chapter Solve

s26 gave you three tools: SyntheticDatasetBuilder (generates test data), evaluate_skill (scores), and ConstraintValidator (gates).

But these three tools are disconnected. You have to wire them up manually: generate data -> run evaluation -> check scores -> manually edit the skill -> run evaluation again -> check constraints -> ...

This chapter automates that manual process -- **one command, input a skill name, output a better version.**

## Suggested Reading

- [`s25-skill-evolution.md`](./s25-skill-evolution.md) -- Skill evolution overview, 7-step pipeline
- [`s26-evaluation-system.md`](./s26-evaluation-system.md) -- The evaluation trio (consumed by this chapter)

## The Optimization Loop: Collect Feedback -> Targeted Rewrite -> Score -> Select the Best

This is the heart of the entire skill evolution pipeline -- step 5 in the pipeline diagram from s25.

```text
                 +------------------+
                 |  current skill   |
                 +--------+---------+
                          |
                 +--------v---------+
          +------| evaluate on      |
          |      | train set,       |
          |      | collect feedback |
          |      +--------+---------+
          |               |
          |      +--------v---------+
          |      | LLM rewrites     |
          |      | skill based on   |
          |      | feedback         |
          |      +--------+---------+
          |               |
          |      +--------v---------+
          |      | evaluate on      |
     repeat N    | val set --       |
     rounds      | new score higher?|
          |      +----+--------+----+
          |           |        |
          |          yes       no
          |           |        |
          |      keep new   revert to current
          |           |        |
          +----------+         |
                               |
                 +-------------v---+
                 |  best version   |
                 |  exits loop     |
                 +-----------------+
```

### Why Use Feedback-Driven Mutation Instead of Random Mutation

Random mutation: hand the skill text to an LLM and say "change it" -- the LLM doesn't know what to change, randomly adds or removes content, and most likely makes things worse.

Feedback-driven mutation: first run evaluation to get specific feedback ("missing error-handling steps," "step 3 is unclear"), then have the LLM revise based on that feedback -- it has direction, and the hit rate is much higher.

This is what distinguishes GEPA from traditional genetic algorithms. Traditional GAs rely on random mutation plus selection pressure to slowly converge; GEPA reads execution traces to understand causes and makes targeted modifications. The teaching version simulates the same idea using the feedback field.

## The Mutation Prompt

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

A few design details worth noting:
- "Keep the same general purpose and structure" -- don't overhaul; make targeted improvements only
- "Return ONLY the improved skill text" -- no explanations, just the new version
- Feedback is truncated to 2000 characters -- prevents the prompt from getting too long

## The Complete Pipeline: evolve_skill()

The 7-step pipeline from s25, now as executable code:

```python
def evolve_skill(skill_name, iterations=5, use_llm=True):
    # 1. Find and load the skill
    skill_file = SKILLS_DIR / skill_name / "SKILL.md"
    raw = skill_file.read_text()
    metadata, body = _parse_frontmatter(raw)

    # 2. Generate eval dataset (s26's SyntheticDatasetBuilder)
    dataset = SyntheticDatasetBuilder().generate(body, num_cases=12)

    # 3. Validate baseline constraints (s26's ConstraintValidator)
    validator = ConstraintValidator()
    validator.validate_all(body)

    # 4. Run the optimizer
    optimizer = SkillOptimizer(use_llm=use_llm)
    result = optimizer.optimize(body, dataset, iterations=iterations)

    # 5. Validate evolved constraints
    evolved_checks = validator.validate_all(result.evolved_text, baseline=body)

    # 6. Evaluate on holdout set (the final exam)
    holdout_score = optimizer._score_on_split(result.evolved_text, dataset.holdout)

    # 7. Back up original + write evolved version
    if result.improvement > 0:
        # Back up to backups/SKILL_<timestamp>.md.bak
        # Write the new version
```

## Walkthrough: Evolving a Skill from the Command Line

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
  -> constraint check failed, not deploying
```

A constraint failure is perfectly normal -- LLMs tend to add content. This is exactly why growth_limit exists.

## Deployment Strategy: Teaching Version vs. Hermes in Practice

| Aspect | Teaching Version | Hermes in Practice |
|--------|-----------------|-------------------|
| Backup | File copy (`backups/SKILL_<ts>.md.bak`) | Git branch (`evolve/<target>-<ts>`) |
| Deploy | Overwrite SKILL.md directly | Create a PR, merge after human review |
| Rollback | Manually restore from backup | `git revert` |
| Approval | None | PR review must pass |

Simplifying in the teaching version makes sense -- the goal is to teach the optimization loop, not git workflows. But in production you **must** use PRs -- automatically generated changes need human review.

## What Hermes Actually Uses: DSPy + GEPA

The teaching version's SkillOptimizer and Hermes' evolve_skill.py have a one-to-one structural correspondence:

```python
# Teaching version
optimizer = SkillOptimizer(use_llm=False)
result = optimizer.optimize(skill_text, dataset, iterations=5)

# Hermes in practice
optimizer = dspy.GEPA(metric=skill_fitness_metric, max_steps=10)
optimized_module = optimizer.compile(baseline_module, trainset=trainset, valset=valset)
```

What does GEPA add?
- **Reflective analysis**: goes beyond scores to read full execution traces and understand failure causes
- **Pareto optimization**: simultaneously optimizes multiple dimensions (correctness vs. conciseness) to find the Pareto front
- **Population management**: maintains multiple candidate versions, not just current vs. best

But the core idea is the same: score -> understand why it's bad -> rewrite with purpose -> keep the best.

## How Phases 2-4 Use the Same Mechanism

This chapter implements Phase 1 (skill evolution). Phases 2-4 use the same "score -> rewrite -> select the best" loop -- they just swap out the evolution target and evaluation method.

### Phase 2: Tool Description Evolution

```python
# Conceptual code (planned in Hermes, not implemented in teaching version)
# Evolution target: tool description text
target_text = registry._tools["search_files"].schema["description"]

# Evaluation method: tool selection accuracy
# "Given a task description, does the agent pick the right tool?"
eval_dataset = generate_tool_selection_dataset()  # (task, correct_tool) pairs

# Constraint: each description <= 500 characters
constraints = ConstraintValidator(max_size=500)
```

### Phase 3: System Prompt Section Evolution

```python
# Evolution target: a section of the prompt (e.g., "memory usage guidelines")
target_text = MEMORY_GUIDANCE_SECTION

# Evaluation method: behavioral tests
# "Does the agent save a memory when it should?"
eval_dataset = generate_behavioral_test_cases()

# Constraint: section must not exceed 120% of original (prevent prompt cache invalidation)
constraints = ConstraintValidator(max_growth=0.2)
```

### Phase 4: Tool Code Evolution

```python
# Evolution target: Python source code (uses Darwinian Evolver, not GEPA)
# Evaluation method: full pytest pass + no benchmark regression
# Strictest constraints: function signatures cannot change, error handling cannot be removed
```

**The core stays the same: score -> rewrite -> select the best. Only "what to evaluate" and "how strict the constraints are" change.**

## Common Beginner Mistakes

### 1. More Iterations Is Always Better

Not necessarily. Three iterations might already find the best version, with iterations 4-10 doing nothing useful. And each iteration costs API calls.

**Fix: Watch the improvement curve. If there is no improvement for 2-3 consecutive iterations, stop early.**

### 2. Using the Evolved Version Without Running Holdout

The optimizer has repeatedly tuned on train + val -- scores may be biased. Holdout contains data the optimizer has never seen; it is the real "exam."

**Fix: Always do the final evaluation on holdout. If the holdout score is worse than baseline, do not deploy.**

### 3. Ignoring Constraint Checks

"Score improved by 0.15, but size exceeded by 20%" -- the score is tempting, but skill bloat will affect every conversation that uses it.

**Fix: Constraints are hard gates. No matter how good the score, if constraints fail, do not deploy.**

## Scope of This Chapter

Covered:
- Full implementation of the optimization loop (collect feedback -> targeted rewrite -> score -> select the best)
- Complete pipeline (evolve_skill, 7 steps)
- Concepts and differences for Phases 2-4
- Comparison with Hermes' actual implementation

Not covered:
- DSPy/GEPA API usage -> external framework
- Darwinian Evolver's git organism mechanism -> Phase 4 specific
- Auto-triggering (Phase 5) -> currently all manual CLI
- PR creation and code review workflow -> git workflow, not evolution itself

## How This Chapter Relates to Others

- **s25** is the map -> this chapter implements steps 5-7
- **s26** provides the measurement tools -> this chapter consumes them (SyntheticDatasetBuilder + evaluate_skill + ConstraintValidator)
- **s08**'s `skill_manage` -> this chapter uses it for final deployment
- **s23** changes the model + this chapter changes the text = two evolutionary paths for the agent

## After This Chapter, You Should Be Able to Answer

- What are the four steps of the optimization loop? Why use feedback instead of random mutation?
- What do the 7 steps of evolve_skill() do? Which steps use components from s26?
- What should you do if constraint checks fail after optimization?
- How does the evaluation method for Phase 2 (tool descriptions) differ from Phase 1 (skills)?
- Do the teaching version and Hermes' GEPA share the same core idea? Where do they differ?

---

**Remember in one sentence: collect feedback -> have the LLM rewrite with purpose -> score -> keep if better, discard otherwise. Repeat N rounds; deploy if constraints pass.**
