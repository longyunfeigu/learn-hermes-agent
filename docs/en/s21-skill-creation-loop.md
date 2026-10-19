# s21: Skill Creation Loop

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > [ s21 ] > s22 > s23 > s24 > s25 > s26 > s27`

> *The agent doesn't just execute tasks -- it extracts patterns from experience, turning "one-off solutions" into "reusable skills for next time." This is the most distinctive mechanism that sets Hermes Agent apart from other agent frameworks.*

![Skill Creation Loop](../../illustrations/en/s21-skill-creation/01-flowchart-creation-loop.png)

## What Problem Does This Chapter Solve

s08 introduced the skill system basics -- the agent can read and use skill files. But those skills were written by humans ahead of time.

Now consider a scenario: the agent helps you configure a complex CI pipeline, hits three pitfalls along the way, changes approach twice, and finally gets it working. Next week you ask a colleague's agent to do the same thing -- it will hit the exact same three pitfalls all over again.

**Experience wasn't retained.** Every time the same problem comes up, the agent has to fumble through it from scratch.

What if the agent could automatically look back after completing a task: "What pitfalls did I hit this time? Which steps are generalizable?" -- and then write the answers into a skill file that's used directly the next time a similar task comes up.

This is the problem the skill creation loop solves: **enabling the agent to learn from experience by turning one-off solutions into reusable skills.**

## Suggested Reading

- [`s08-skill-system.md`](./s08-skill-system.md) -- Skill fundamentals: format, discovery, loading, usage
- [`s10-subagent-delegation.md`](./s10-subagent-delegation.md) -- Background review is implemented using subagents
- [`s04-prompt-builder.md`](./s04-prompt-builder.md) -- How the skill index is injected into the system prompt

## Key Concepts

### What Is Background Review

After the agent finishes a conversation, it **forks a copy** that reviews the conversation in the background. The copy runs independently without blocking the user's next question. It analyzes whether the conversation contained any experience worth saving -- if so, it calls `skill_manage` to create or update a skill.

### What Is the Skill Creation Loop

A complete cycle:

```text
Use -> encounter a problem, figure out a solution -> background review extracts patterns -> create skill
  -> next time a similar task comes up -> load skill, use it directly -> skip the fumbling
```

The key is "next time" -- pitfalls hit today won't be hit again tomorrow.

### What Is skill_manage

The tool the agent uses to create, edit, and delete skills. It's registered in the registry just like `terminal` and `read_file`, and the agent can invoke it at any point during a conversation.

## Starting from the Simplest Approach

Have the user manually tell the agent "save this solution as a skill":

```text
User: Set up GitHub Actions CI for me
Agent: [after considerable effort, succeeds]
User: Save what you just did as a skill
Agent: Sure -> calls skill_manage(action="create", name="github-actions-ci", content="...")
```

It works. But there are two problems:

### Problem 1: The User Has to Remember to Say "Save as a Skill"

Most of the time, the user finishes the task and moves on without reminding the agent to summarize the experience. Valuable knowledge is lost.

### Problem 2: The Agent Doesn't Know What's Worth Saving

When the user says "save as a skill," the agent dumps every step from the entire conversation -- including wrong turns and irrelevant trial-and-error. The resulting skill file is long and messy, and actually misleads the agent the next time it's used.

**What's needed is an automatic mechanism: one that doesn't depend on user prompting and can identify "non-trivial experience worth preserving."**

## Minimal Mental Model

```text
Agent working normally...
    |
    |  Every 10 tool calls, check once
    |
    v
Trigger condition met?
    |
    Yes
    |
    v
Fork a copy (background review agent)
    |  Input: full message history from this conversation
    |  Prompt: analyze the conversation, find non-trivial, reusable patterns
    |  Limit: at most 8 tool call iterations
    |
    v
Background review agent decides:
    |
    |-- Discovers a new pattern -> skill_manage(action="create", ...)
    |-- Existing skill needs updating -> skill_manage(action="patch", ...)
    '-- Nothing worth saving -> "Nothing to save." -> exit
    |
    v
User sees notification: "Skill 'github-ci-setup' created"
    |
    v
Next conversation: the new skill appears in the available list
```

**The background review agent and the main agent are completely independent.** It runs in a background thread without blocking the user's next question. It can call skill_manage to write skills, but it cannot modify the main conversation's message history.

## Background Review Trigger Logic

Not every conversation turn triggers a review. Hermes Agent uses a **tool call counter** to control this:

```python
# After each tool call
self._iters_since_skill += 1

# Check when conversation ends
if self._iters_since_skill >= 10:  # Default: trigger every 10 tool calls
    spawn_background_review(messages_snapshot, review_skills=True)
    self._iters_since_skill = 0
```

Why use tool call count instead of conversation turns? Because tool calls represent the agent "doing work" -- a conversation that's purely casual chat doesn't need review. Ten consecutive tool calls indicate the agent was handling a task of some complexity, worth looking back on.

The frequency can be adjusted or disabled in config.yaml:

```yaml
skills:
  creation_nudge_interval: 10  # Trigger every 10 tool calls. Set to 0 to disable.
```

## The Prompt Sent to the Background Review Agent

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

Key terms: **non-trivial**, **trial and error**, **changing course**. These filter conditions exclude simple tasks ("translate this sentence for me" won't trigger skill creation). Only experiences that involved hitting pitfalls and changing approach are worth saving.

## What a Skill File Looks Like

A skill file created via `skill_manage(action="create")`:

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

Notice the **Pitfalls** section -- this is the "hard-won experience" extracted by the background review agent from the conversation. The next time a similar task comes up, the agent loads this skill and skips right past those pitfalls.

## How Skills Are Used in the Next Conversation

After a skill is created, the next time a conversation starts:

A skill's directory structure isn't just a single SKILL.md -- it can include reference files:

```text
~/.hermes/skills/github-actions-python-ci/
├── SKILL.md                       <- Main file: steps + pitfalls
├── references/
│   ├── codecov-setup.md           <- Reference: detailed Codecov configuration
│   └── matrix-strategy.md         <- Reference: matrix strategy best practices
└── templates/
    └── ci.yml.template            <- Template: YAML ready to copy
```

Loading is **three-tier progressive**, where the model actively decides at each tier whether to go deeper:

```text
Layer 1: Index in system prompt (all skill names + one-line descriptions)
  ┌─────────────────────────────────────────────────────────┐
  │ <available_skills>                                       │
  │   github:                                                │
  │     - github-actions-python-ci: Set up GitHub Actions CI │
  │ </available_skills>                                      │
  └─────────────────────────────────────────────────────────┘
  -> Model sees the index, decides "github-actions-python-ci is relevant to the current task"

Layer 2: skill_view("github-actions-python-ci")
  -> Loads the full content of SKILL.md
  -> SKILL.md says "See references/codecov-setup.md for detailed Codecov configuration"

Layer 3: skill_view("github-actions-python-ci", file_path="references/codecov-setup.md")
  -> Model reads the reference in SKILL.md, decides it needs detailed configuration
  -> Loads the reference file on demand
```

Each step from Layer 1 to Layer 2 to Layer 3 is the model's own decision -- the same mechanism as when the model sees an image path in s18 and decides to call vision_analyze. No special logic is needed; `skill_view` is in the tool list and the model decides on its own when more information is needed.

### Post-Loading Actions Depend on File Type

The loading mechanism is uniform across all three tiers -- always `skill_view(name, file_path=...)`. But **what happens after reading** depends on the file type:

| File Type | How It's Loaded | What Happens After Loading |
|----------|----------|-------------|
| `references/*.md` | `skill_view(name, file_path="references/...")` | Understand content, guide actions |
| `templates/*.yml` | `skill_view(name, file_path="templates/...")` | Copy content to target file |
| `scripts/*.sh` | `skill_view(name, file_path="scripts/...")` | Execute via the `terminal` tool |

Full flow for scripts:

```text
SKILL.md says:
  "Step 3: Run scripts/setup.sh to configure the environment"

Model's behavior:
  1. skill_view("my-skill", file_path="scripts/setup.sh")  <- read the script first
  2. Understand what the script does (is it safe? does it need parameter changes?)
  3. terminal("bash ~/.hermes/skills/my-skill/scripts/setup.sh")  <- execute via terminal
```

**There is no "auto-execute" mechanism.** The model reads the script content first, evaluates safety, then executes through the terminal tool. The permission system from s09 works as usual -- dangerous commands in the script will be blocked.

### Why There's No Layer 4 or Layer 5

Because starting from Layer 3, it's flat -- always the same `skill_view(name, file_path="...")` call. If `references/api-guide.md` mentions "see references/advanced/deep-dive.md for details," the model simply makes another `skill_view` call. No new mechanism is needed.

```text
Layer 1: Index         -> Fixed mechanism (auto-injected in prompt)
Layer 2: SKILL.md      -> skill_view(name)
Layer 3+: Any file     -> skill_view(name, file_path="...")  <- same call from here on
```

In practice, however, if a skill requires layers upon layers of nested references to explain itself, it usually means **it should be split into multiple skills**:

```text
Bad (one giant skill with nested references):
  mega-deploy/
    SKILL.md -> references/docker.md -> references/docker/advanced.md -> ...
    Model needs 5 skill_view calls to get all the information

Good (split into independent skills, each needing only 2-3 layers):
  deploy-docker/SKILL.md
  deploy-kubernetes/SKILL.md
  deploy-ci-pipeline/SKILL.md  <- says "if using Docker, load deploy-docker first"
```

Cross-references between skills rely on textual guidance in SKILL.md. When the model reads "load deploy-docker first," it calls `skill_view("deploy-docker")` on its own -- the same decision mechanism as loading references.

**Why not load everything at once?** Token savings. If there are 100 skills, each with 3 reference files and scripts, putting them all in the prompt would consume hundreds of thousands of tokens. Progressive loading lets the model load only the parts actually needed for the current task.

## Full Scenario Walkthrough

```text
=== Day 1 ===

User: Set up GitHub Actions CI for this project
Agent: Sure, I'll configure it...
  -> First version used pip install -r requirements.txt -> tests failed
  -> Discovered need for pip install -e ".[dev]" -> fixed
  -> Codecov upload failed -> discovered CODECOV_TOKEN is required -> fixed
  -> Finally passing
Agent: CI is set up.
User: Thanks

  [When conversation ends, tool call count >= 10 -> background review triggered]

Background review agent:
  "In this conversation the agent hit two pitfalls (requirements install method,
  Codecov token) and ultimately succeeded. This is a non-trivial, reusable pattern."
  -> skill_manage(action="create", name="github-actions-python-ci", content="...")

User sees: "Skill 'github-actions-python-ci' created"

=== Day 2 ===

Colleague: Set up CI for another project too
Agent: [system prompt contains github-actions-python-ci]
  -> skill_view("github-actions-python-ci") -> loads full content
  -> Uses pip install -e ".[dev]" directly (won't make the requirements.txt mistake again)
  -> Proactively reminds user to add CODECOV_TOKEN
  -> Passes on the first try
```

Pitfalls hit on Day 1 won't be hit again on Day 2. That's the value of the skill creation loop.

## How It Plugs into the Main Loop

Background review triggers after the conversation ends, not inside the core loop.

```text
Core loop runs normally
  |  Each tool call -> _iters_since_skill += 1
  v
Conversation ends (model returns final reply)
  |
  |  _iters_since_skill >= 10?
  |
  Yes -> fork background review agent (daemon thread)
  |    '- analyze message snapshot -> skill_manage -> create/update skill
  |
  v
Return reply to user (don't wait for background review to finish)
```

## Common Beginner Mistakes

### 1. Triggering Review on Every Turn

If nudge_interval is set too low (e.g., 1), every tool call triggers a background review, wasting API calls. Simple tasks get reviewed too -- producing a pile of useless skills.

**Fix: Default to triggering once every 10 tool calls. Simple tasks usually finish in fewer than 10 tool calls.**

### 2. Assuming the Background Review Agent Can Modify the Main Conversation

The background review agent receives a message **snapshot** (copy), not a reference. Its operations (creating skills, updating memory) write to shared directories on disk, but it cannot modify the main conversation's message list.

### 3. Skill Files That Only List Steps Without Pitfalls

The most valuable part isn't "how to do it" (the user could search for that themselves), but **"where things go wrong."** The background review prompt specifically emphasizes "trial and error" and "changing course" -- this is designed to guide extraction of hard-won lessons.

### 4. Stuffing All Skill Content into the System Prompt

100 skills x 2,000 words each = 200,000 words in the prompt. The model can't handle it, and token costs explode.

**Fix: Put only the skill index (name + description) in the prompt. After the model determines relevance, it uses `skill_view` to load content on demand.**

## Teaching Boundaries

This chapter covers the complete mechanism of the skill creation loop.

Three things covered:

1. **How background review is triggered** -- Tool call counting + check at conversation end
2. **How the review agent decides to create/update/skip** -- Prompt guidance + "non-trivial" filter
3. **How new skills are used next time** -- Three-tier progressive loading (index -> SKILL.md -> reference files)

Not covered:

- Specific rules for skill security scanning -> security mechanism
- Community skill sharing (Skills Hub) -> product feature
- Skill version management and rollback -> current version overwrites directly, no history
- Cross-machine skill synchronization -> skills are stored locally at ~/.hermes/skills

## How This Chapter Relates to Others

- **s08** defined the basic skill format and usage -> this chapter adds automatic creation on top
- **s10**'s subagent mechanism -> background review is implemented using subagents
- **s07**'s memory system -> background review updates both memory and skills simultaneously (complementary: memory stores facts, skills store methods)
- **s20**'s Background Review -> provides the infrastructure for this chapter; this chapter is its "skill creation" application

## After This Chapter, You Should Be Able to Answer

- When does background review trigger? Does it run on every conversation turn?
- Are the background review agent and the main agent in the same process? Can the review agent modify the main conversation?
- What is the most valuable part of a skill file? The steps or the hard-won lessons?
- Why aren't all skills loaded into the system prompt instead of being loaded on demand?
- Can a skill created by one user today be used by another user tomorrow?

---

**One-liner: After the agent completes a task, a background copy automatically reviews the conversation, extracts non-trivial experience, and creates a skill. The next time a similar task comes up, the skill is loaded directly, skipping the trial-and-error phase.**
