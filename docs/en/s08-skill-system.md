# s08: Skill System

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > [ s08 ] > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Tools are capabilities hard-coded in source; skills are experience the agent manages on its own.*

## What problem does this chapter solve

By `s07`, the agent has cross-session memory. But memory stores **declarative knowledge** (facts, preferences, conventions).

There is another kind of knowledge it cannot capture:

> "When tackling this type of task, what steps should I follow? What pitfalls should I watch out for?"

For example:

- What items to check during a code review
- How to handle missing values during data analysis
- What the standard directory structure is when building an MCP server

These are **procedural knowledge** -- not a single fact, but an entire methodology.

If you stuff them into the system prompt, it quickly becomes bloated and unmaintainable. If you do not save them, the agent has to figure things out from scratch every time it encounters the same type of task.

That is why a skill system is needed:

**Let the agent codify successful approaches into files and load them on demand the next time it encounters a similar task.**

![Tool vs Skill vs MCP](../../illustrations/s08-skill-system/01-comparison-tool-skill-mcp.png)

## Key terms explained

### What is a skill

A reusable instruction sheet organized around a type of task. Stored as a `SKILL.md` file.

It typically tells the agent:

- When to use it
- What steps to follow for this type of task
- What pitfalls to watch out for
- What templates or examples to reference

### Difference between skill and tool

- `tool`: A capability hard-coded in Python. Written by the developer. Adding a new tool requires writing code.
- `skill`: A markdown file. The agent can create, edit, and delete them on its own. No code changes needed.

Skills are executed through existing tools. For instance, a "data analysis" skill might say "run a pandas script via the terminal" -- the skill describes the approach, the tool provides the means.

### Difference between skill and memory

- `memory`: Declarative knowledge. "User prefers tabs." "Project uses pytest."
- `skill`: Procedural knowledge. "When doing a code review, follow this checklist."

A simple litmus test:

- A fact -> memory
- A methodology -> skill

### What is progressive disclosure

The skill system uses three layers of exposure:

1. **Index layer**: Shows only names and descriptions (dozens of skills take up just a few hundred tokens)
2. **Body layer**: The model loads the full SKILL.md content when it decides it is needed
3. **Attachment layer**: Reference files, templates, and scripts in the skill directory, loaded only when needed

Normally the system prompt contains only the index layer. The body and attachments are loaded into the conversation through tool calls only when needed.

## Minimal mental model

```text
system prompt
  |
  +-- Skills available:
      - code-review: Code review checklist
      - data-analysis: CSV/DataFrame analysis workflow
      - mcp-builder: Build an MCP server

When the model decides it needs a skill:

skill_view("code-review")
   |
   v
tool_result: full SKILL.md body
   |
   v
Agent follows the skill content to execute the task
```

But Hermes Agent goes one step further: **the agent can not only read skills, it can also create and edit them.**

```text
Agent completes a data analysis task
   |
   v
Agent judges this approach is worth reusing
   |
   v
skill_manage(action="create", name="data-analysis", content="...")
   |
   v
~/.hermes/skills/data-analysis/SKILL.md is created

Next time a similar task comes up:

skill_view("data-analysis") -> load the approach -> follow the steps directly
```

This is where Hermes Agent differs from most agent frameworks: **skills are not all predefined -- some are distilled from the agent's own experience.**

## Key data structures

### 1. SKILL.md format

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

The frontmatter (between `---`) is structured metadata. The body is free-form markdown.

### 2. Skill directory structure

```text
~/.hermes/skills/
+-- code-review/
|   +-- SKILL.md
+-- data-analysis/
|   +-- SKILL.md
|   +-- references/
|   |   +-- pandas-cheatsheet.md
|   +-- templates/
|       +-- report-template.md
+-- software-development/
    +-- git-workflow/
        +-- SKILL.md
```

Each skill is a directory that must contain a `SKILL.md`. It may have `references/`, `templates/`, `scripts/`, and `assets/` subdirectories for attachments.

### 3. Skill availability status

```text
available     -- Can be used directly
setup_needed  -- Missing dependencies (e.g. an environment variable is not set)
unsupported   -- Not supported on the current platform
```

Skills can declare dependencies (environment variables, command-line tools) and platform restrictions (macOS only). Skills that do not meet the requirements do not appear in the index.

## Minimal implementation

### Step 1: Scan the skills directory

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

### Step 2: Put the skill index into the system prompt

```python
# Only names and descriptions -- not the full body
skills_index = "\n".join(
    f"- {s['name']}: {s['description']}"
    for s in skills.values()
)
prompt_parts.append(f"# Available Skills\n{skills_index}")
```

The key idea behind this step:

> The index is cheap (a few hundred tokens); the body is expensive (potentially thousands of tokens). Only include the index by default.

### Step 3: Provide a viewing tool

```python
def skill_view(name, file=None):
    skill = skills.get(name)
    if not skill:
        return f"Skill '{name}' not found"
    if file:
        # Load an attachment
        return (skill["path"] / file).read_text()
    return skill["body"]
```

### Step 4: Provide a management tool

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

This step is what makes Hermes Agent unique: the agent is not just a consumer of skills but also a creator.

## How it fits into the main loop

After this chapter, the system prompt no longer contains just identity, memory, and project rules.

It grows a new section: **the available skills index.**

And the message stream gains a new kind of on-demand injection: **the full body of a given skill.**

In other words, system input is now split into two tiers:

```text
Stable tier (present every turn):
  Identity, memory, project rules, tool definitions, skills index

On-demand tier (loaded only when needed):
  A skill's SKILL.md body
  A skill's attachment files
```

This "stable tier + on-demand tier" split matters because the stable tier determines the prompt cache hit rate -- the more stable it is, the more effective the cache. On-demand content enters through tool_result and does not affect the system prompt.

This is also why skill bodies should not be stuffed into the system prompt: they would make the stable tier unstable.

## Hermes Agent's unique design choices here

### 1. The agent creates and edits skills itself

Most agent frameworks treat skills as read-only (predefined by the developer). Hermes Agent lets the agent create, edit, and delete skills through the `skill_manage` tool.

This means the agent can learn from experience: "that approach worked well last time -> save it as a skill -> use it directly next time."

### 2. Security scanning

Skills created by the agent undergo the same security scanning as skills installed from the Hub. The system checks whether the SKILL.md contains suspicious command injection or malicious instructions.

### 3. Multi-source skills

Skills come from multiple sources:

- **Built-in skills**: The project's own `skills/` directory
- **User skills**: Created by the agent or user under `~/.hermes/skills/`
- **Hub installs**: Installed from agentskills.io, GitHub, and other sources
- **External directories**: Additional skill directories configured in the config

GitHub-installed skills are best for narrow workflows that would bloat the core
agent if they were built in. For example, a team can install Hermes Tweet from
`Xquik-dev/hermes-tweet` when the agent needs a Hermes Agent X/Twitter plugin
for scrape/search tweets, search Twitter/X, read tweet replies, look up users,
monitor tweets, export followers, and confirmation-gated post tweets/replies,
send DMs, and automate X actions. Its index description should stay explicit,
for example: `hermes-tweet: Hermes Agent X/Twitter plugin for read-first tweet
research and gated account actions`.

When there are name collisions across sources, user skills take priority.

### 4. Skill improvement nudge

Every certain number of tool-call turns, the agent is reminded to "consider whether any skills are worth creating or improving." This is a nudge, not an automatic action.

### 5. Two-tier caching

The system prompt fragment for the skills index has two layers of caching: in-process LRU cache plus a disk snapshot. This avoids re-scanning the filesystem on every API call.

## Boundaries between skill, memory, SOUL.md, and HERMES.md

| | skill | memory | SOUL.md | HERMES.md |
|---|---|---|---|---|
| What it is | A methodology for a type of task | Cross-session facts | Persona | Project rules |
| Example | "Code review checklist" | "User prefers tabs" | "You are a concise assistant" | "Run tests with pytest" |
| Who writes it | Agent or developer | Agent | User | Developer |
| Where in the prompt | Index in system prompt; body loaded on demand | Frozen in the system prompt | Very beginning of system prompt | In the system prompt |
| Size | Hundreds to thousands of characters each | Character-limited | Usually short | Varies by project |

## Common beginner mistakes

### 1. Stuffing all skill bodies into the system prompt permanently

The full body of 20 skills could be tens of thousands of tokens. Include only the index; load bodies on demand.

### 2. Conflating skill and memory

A skill is "how to do it"; memory is "what you know." One is a procedure, the other is a fact.

### 3. Letting agent-created skills bypass security checks

Agent-generated SKILL.md files may contain dangerous instructions. They need the same security scanning as externally installed skills.

### 4. Writing weak skill index entries

A name without a description leaves the model unable to judge when to load it. The description must tell the model clearly "what scenario this skill applies to."

### 5. Treating skills as absolute rules

Skills are more like "recommended practices," not rigid mandates for every situation. The model should be able to adapt flexibly based on actual circumstances.

## Teaching boundaries

This chapter should hold three things firm:

1. **Progressive disclosure**: The index lives in the prompt; the body is loaded on demand
2. **Agent-writable**: The agent is not just a consumer but also a creator
3. **Boundary with memory**: Facts versus methodology

Deliberately deferred: the full Hub installation workflow, multi-source priority merging, specific security scanning rules, cache invalidation strategies.

If the reader can get the agent to "save a successful approach as a skill file and load it the next time a similar task comes up," this chapter has achieved its goal.

## After finishing this chapter, you should be able to answer

- What is the difference between a skill and a tool?
- What is the difference between a skill and memory?
- Why should skill bodies not be permanently placed in the system prompt?
- What extra security considerations apply to agent-created skills?
- What are the three layers of progressive disclosure?

---

**One line to remember: Skills are the agent's procedural memory -- not "what it knows" but "how it does things." In Hermes Agent, the agent does not just use skills; it creates and improves them from experience.**
