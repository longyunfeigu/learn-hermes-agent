# s20: Background Review

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > [ s20 ] > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Users rarely say "remember this for me" on their own. The agent needs to notice what's worth remembering and what can be distilled into a skill -- then quietly handle it in the background without interrupting the user's work.*

![Background Review Process](../../illustrations/en/s20-background-review/01-flowchart-background-review.png)

## What Problem Does This Chapter Solve

s07 covered the memory system. s08 covered the skill system. But both share a prerequisite: **the agent must proactively invoke the memory or skill_manage tool.**

The trouble is: when the agent is busy helping the user solve a problem, it rarely "stops to think" about updating its memory.

**Scenario: A missed preference.**

```text
Turn 1: User: Take a look at this Python project for me
Turn 2: Agent: [reads files, analyzes code]
Turn 3: User: By the way, I don't like semicolons at the end of lines, and I don't like type hints
Turn 4: Agent: Got it. [continues analyzing code]
Turn 5: User: Refactor parser.py for me
Turn 6-10: Agent: [refactors files, occasionally still writes type hints]
```

The user expressed a preference at Turn 3, but the agent was busy analyzing code and didn't think to call `memory_tool` to store it. When the next conversation starts, the agent has no recollection of this at all.

**With background review:**

```text
After Turn 10 completes -> background thread starts
  The review agent reads the entire conversation history
  Discovers the preference information from Turn 3
  Calls memory_tool to write to USER.md:
    "User dislikes semicolons at end of lines and type hints"
  Completes silently, invisible to the user

Next new conversation -> system prompt already contains this memory
```

This is the problem Background Review solves: **letting the agent "look back" after a conversation ends to capture knowledge that was missed during the work.**

## Suggested Reading

- [`s07-memory-system.md`](./s07-memory-system.md) -- The read/write mechanisms for memory, reused directly by the review agent
- [`s08-skill-system.md`](./s08-skill-system.md) -- Skill creation/editing; the review agent can automatically create new skills
- [`s10-subagent-delegation.md`](./s10-subagent-delegation.md) -- Contrast: subagents are synchronous; background review is asynchronous

## Key Concepts

### What Is Background Review

After the main agent finishes a conversation turn, it launches an **independent agent instance** in the background, hands it the full conversation history, and asks it to answer one question:

> "Was there anything in this conversation worth remembering? Anything that could be distilled into a skill?"

If so, the review agent directly invokes memory/skill tools to make updates. If not, it says "Nothing to save" and exits.

### What Are the Dual Counters

Background review uses two independent trigger counters:

- **`_turns_since_memory`** -- Every N user messages (default 10), trigger a memory review
- **`_iters_since_skill`** -- Every N tool call iterations (default 10), trigger a skill review

Why two different units?

- **Memory** focuses on what the user said -> measured by "how many messages the user sent"
- **Skills** focus on what the agent did -> measured by "how many tool calls the agent made"

A user might send 10 messages while the agent only made 2 tool calls (pure chatting), or send 1 message while the agent made 20 tool calls (complex task). The two cases call for different kinds of review.

### How Does the Review Agent Differ from a Subagent

Readers who studied s10's subagent system might ask: isn't this just creating another agent?

| | s10 Subagent | s20 Background Review |
|---|---|---|
| Purpose | Complete a subtask for the user | Self-reflection; update memory/skills |
| Timing | During user task execution | After user task completion |
| Blocking | **Synchronous**, blocks the parent agent | **Asynchronous**, daemon thread |
| Iteration budget | Shared with parent (more used = less for parent) | **Independent budget** (max=8) |
| Result destination | Summary returned to parent -> placed in messages | Writes directly to MEMORY.md / skills/ |
| Failure handling | Reports error to user | **Silently swallowed**, best-effort |

The key difference: a subagent is an extension of work done for the user; a review agent is the agent's own learning process.

## Minimal Mental Model

```text
Main agent conversation loop
  |
  |  After each turn, check two counters:
  |    _turns_since_memory >= 10?
  |    _iters_since_skill >= 10?
  |
  |  If either triggers:
  v
_spawn_background_review()
  |
  |  1. Copy messages (snapshot)
  |  2. Choose review prompt (memory / skill / combined)
  |  3. Create new AIAgent(max_iterations=8, nudge_interval=0)
  |  4. Launch daemon thread
  |
  v
Background thread
  |  review_agent.run_conversation(
  |      prompt = "Review this conversation -- anything worth remembering?"
  |      history = messages_snapshot
  |  )
  |
  |  The review agent can call:
  |    - memory_tool -> writes to MEMORY.md / USER.md
  |    - skill_manage -> creates/edits skill files
  |
  |  Exits silently on completion
  |  (Main agent and user are completely unaffected)
  v
MEMORY.md / skills/ updated
  -> Next conversation's system prompt automatically includes new memories/skills
```

## Key Data Structures

### Review Trigger State

```python
# In AIAgent.__init__
self._turns_since_memory = 0     # User message counter
self._iters_since_skill = 0     # Tool iteration counter
self._memory_nudge_interval = 10 # Trigger threshold (configurable)
self._skill_nudge_interval = 10  # Trigger threshold (configurable)
```

### Review Prompts

```python
_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory "
    "if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves — their persona, "
    "desires, preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave?\n\n"
    "If something stands out, save it using the memory tool. "
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating "
    "a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that "
    "required trial and error, or changing course due to experiential "
    "findings along the way?\n\n"
    "If a relevant skill already exists, update it. Otherwise, create "
    "a new skill if the approach is reusable.\n"
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)
```

Notice the last sentence of each prompt: "If nothing is worth saving, just say 'Nothing to save.' and stop." This is crucial -- without it, the review agent will fabricate findings when there's nothing meaningful to write.

## Minimal Implementation

### Step 1: Dual Counters

Maintain two counters inside the main loop of `run_conversation`:

```python
def run_conversation(self, user_message, ...):
    # User message arrives -> increment memory counter
    self._turns_since_memory += 1

    for iteration in range(MAX_ITERATIONS):
        # ... model call ...

        if assistant_msg.tool_calls:
            # Tool call -> increment skill counter
            self._iters_since_skill += 1

            for tool_call in assistant_msg.tool_calls:
                # User explicitly invoked memory/skill -> reset counters
                if tool_call.function.name in ("memory", "skill_manage"):
                    self._turns_since_memory = 0
                    self._iters_since_skill = 0
```

**Why does an explicit invocation reset the counters?** If the user just said "remember that I don't like type hints" and the agent called memory_tool, there's no need for a background review to cover the same ground. Resetting the counters avoids duplicate work.

### Step 2: Trigger Check

After the conversation ends (before `run_conversation` returns), check whether to trigger:

```python
    # run_conversation is about to return
    should_review_memory = (
        self._memory_nudge_interval > 0
        and self._turns_since_memory >= self._memory_nudge_interval
    )
    should_review_skills = (
        self._skill_nudge_interval > 0
        and self._iters_since_skill >= self._skill_nudge_interval
    )

    if should_review_memory or should_review_skills:
        self._turns_since_memory = 0
        self._iters_since_skill = 0
        self._spawn_background_review(
            messages_snapshot=list(messages),  # snapshot copy
            review_memory=should_review_memory,
            review_skills=should_review_skills,
        )

    return {"final_response": ..., "messages": messages}
```

### Step 3: Background Thread Execution

```python
def _spawn_background_review(self, messages_snapshot, review_memory, review_skills):
    # Choose prompt
    if review_memory and review_skills:
        prompt = _COMBINED_REVIEW_PROMPT
    elif review_memory:
        prompt = _MEMORY_REVIEW_PROMPT
    else:
        prompt = _SKILL_REVIEW_PROMPT

    def _run_review():
        import contextlib

        # Review agent: independent instance, shared MemoryStore
        review_agent = create_review_agent(
            parent=self,
            max_iterations=8,
        )

        # Silent execution: stdout/stderr -> /dev/null
        with open(os.devnull, "w") as devnull, \
             contextlib.redirect_stdout(devnull), \
             contextlib.redirect_stderr(devnull):
            try:
                review_agent.run_conversation(
                    user_message=prompt,
                    history=messages_snapshot,
                )
            except Exception:
                pass  # best-effort: review failure doesn't affect the user

    # daemon=True: thread auto-terminates when main process exits
    thread = threading.Thread(target=_run_review, daemon=True,
                              name="bg-review")
    thread.start()
```

### Step 4: Creating the Review Agent (Sharing vs. Isolation)

```python
def create_review_agent(parent, max_iterations=8):
    """Create an isolated agent instance for background review."""
    agent = AIAgent(
        model=parent.model,
        max_iterations=max_iterations,
    )

    # Shared: MemoryStore is the same Python object
    # Memories written by the review agent are immediately visible
    # to the main agent (on next conversation)
    agent._memory_store = parent._memory_store

    # Isolated: nudge_interval set to 0
    # Prevents the review agent from triggering its own review -> infinite recursion
    agent._memory_nudge_interval = 0
    agent._skill_nudge_interval = 0

    return agent
```

**Why sharing MemoryStore matters:** When the review agent calls `memory_tool` to write, it operates on the exact same MemoryStore object as the main agent. Writes are persisted directly to MEMORY.md. The next time the main agent starts a new conversation, `build_system_prompt()` re-reads MEMORY.md, and the new memories automatically appear in the system prompt.

## Walkthrough: A Complete Background Review

```text
=== Turns 1-10: User and agent discuss a Python project ===

Turn 3: User: "I don't like type hints, and don't use f-strings either"
  -> _turns_since_memory = 3
  -> Agent is busy analyzing code, doesn't call memory_tool

Turn 7: Agent calls terminal, read_file, write_file
  -> _iters_since_skill = 7 (three tool calls)

Turn 10: Conversation ends
  -> _turns_since_memory = 10 -> Triggered!
  -> _iters_since_skill = 7 -> Not triggered (hasn't reached 10)

=== Background review starts (memory review only) ===

1. Main agent returns final reply to user
   (User already sees the reply, unaffected by review)

2. _spawn_background_review(
       messages_snapshot = [complete history of Turns 1-10],
       review_memory = True,
       review_skills = False,
   )

3. Daemon thread starts, creates review_agent:
     model = same as main agent
     max_iterations = 8 (won't run too long)
     _memory_nudge_interval = 0 (prevents cascading)

4. review_agent receives:
     history = complete history of Turns 1-10
     prompt = "Review the conversation... Has the user revealed
               things about themselves...?"

5. review_agent analyzes and finds the user preference at Turn 3
   -> Calls memory_tool:
     save(category="user", content="Dislikes type hints and f-strings")

6. MEMORY.md is updated

7. review_agent says "Saved user preference." then exits
   (This output goes to /dev/null, invisible to the user)

8. Daemon thread ends

=== Next new conversation ===

build_system_prompt() reads MEMORY.md
  -> system prompt now includes:
    "User Profile: Dislikes type hints and f-strings"
  -> Agent won't use type hints when writing code this time
```

## Scenario Two: Why Cascade Protection Is Needed

What happens if the review agent's `_memory_nudge_interval` is not set to 0?

```text
Main agent completes -> triggers review agent A
Review agent A calls memory_tool -> _turns_since_memory++
  -> A triggers review agent B
    Review agent B calls memory_tool -> triggers review agent C
      -> C triggers D -> D triggers E -> ...
```

Each review agent spawns a new thread with a new review agent, recursing infinitely until memory is exhausted.

**Fix: Set `nudge_interval=0` when creating the review agent so it never triggers its own review.**

One line of configuration prevents a system-crashing bug.

## Unique Design Choices in Hermes Agent

### Review Is Not Summarization

Most agent frameworks treat "self-reflection" as generating conversation summaries. Hermes Agent doesn't do summaries -- **it lets the review agent operate tools directly.**

The review agent has the exact same tool access as the main agent. It doesn't "analyze the conversation and output suggestions" -- it "analyzes the conversation and directly writes to MEMORY.md, directly creates skill files."

This is a crucial distinction: summaries are passive (a human has to read the summary and then act), while tool operations are active (the agent handles it all by itself).

### Best-Effort Design

The entire background review system can fail without affecting user experience:

- Daemon thread: automatically cleaned up when the main process exits
- `try/except: pass`: any exception is silently swallowed
- stdout/stderr -> devnull: no strange output printed to the terminal
- max_iterations=8: won't run too long and waste API costs

This isn't laziness -- it's intentional design. Review is icing on the cake, not core functionality. If a review fails, the only consequence is "didn't learn something this time" -- it will try again next time.

## Common Beginner Mistakes

### 1. Forgetting Cascade Protection

Not setting `nudge_interval=0` on the review agent, causing infinite recursion.

**Fix: Set `_memory_nudge_interval = 0` and `_skill_nudge_interval = 0` immediately when creating the review agent.**

### 2. Passing a Message Reference Instead of a Snapshot

```python
# Wrong: passing a reference -- main agent's subsequent modifications affect the review
self._spawn_background_review(messages_snapshot=messages)

# Right: passing a snapshot (shallow copy)
self._spawn_background_review(messages_snapshot=list(messages))
```

The review agent reads messages in a background thread. If you pass a reference and the main agent modifies the messages list during the next conversation turn, the review agent reads corrupted data.

### 3. Writing Review Prompts That Are Too Broad

```text
# Wrong: too broad -- the review agent will try to save every single statement
"Summarize all the key points from this conversation"

# Right: focused -- only save things "worth remembering"
"Has the user revealed things about themselves...
 If nothing is worth saving, just say 'Nothing to save.'"
```

The review prompt must include a clear stopping condition ("Nothing to save"); otherwise, the review agent will fabricate nonexistent "discoveries."

### 4. Setting the Review Agent's Iteration Budget Too High

A review agent with max_iterations=90 might spend several minutes and burn tens of thousands of tokens "thinking." Review should be a quick scan, not deep analysis.

**Fix: max_iterations=8 is sufficient. If 8 iterations aren't enough to complete a review, the prompt needs work.**

### 5. Not Resetting Counters After Explicit Operations

The user says "remember that I don't like type hints," the agent calls memory_tool. But the counter isn't reset, so 10 turns later the review agent writes the same preference again.

**Fix: During tool dispatch, check whether memory or skill_manage was called. If so, reset the corresponding counter.**

## Teaching Boundaries

This chapter covers five things:

1. **Why automatic review is needed** -- The agent is too busy during work to self-reflect
2. **Dual counters** -- turns (memory) vs. iterations (skills), reset on explicit operations
3. **Isolation vs. sharing** -- messages snapshot vs. shared MemoryStore, compared with s10 subagents
4. **Review prompt design** -- Focus on "what's worth saving," must include a stopping condition
5. **Best-effort + cascade protection** -- daemon thread, silent failure, nudge_interval=0

Not covered:

- Gateway callback for review results (`background_review_callback`) -> production detail
- File lock implementation -> MemoryStore internals, covered in s07
- Adaptive review frequency tuning -> advanced optimization
- Deduplication across multiple reviews -> production optimization

## How This Chapter Relates to Others

- **s07**'s memory system -> the review agent calls the same `memory_tool`
- **s08**'s skill system -> the review agent can create new skills via `skill_manage`
- **s10**'s subagent -> contrast: synchronous vs. asynchronous, shared budget vs. independent budget
- **s21**'s skill creation loop -> s20 is "discovering things worth saving," s21 is "turning them into high-quality skills"

**s20 is the starting point of Phase 5.** From here on, Hermes Agent is no longer just a loop that executes tools -- it begins **learning from its own experience.**

## After This Chapter, You Should Be Able to Answer

- Why is memory review triggered by turn count, while skill review is triggered by tool iteration count?
- What is the fundamental difference between the review agent and s10's subagent?
- Why is MemoryStore shared, but messages are snapshotted?
- What does setting the review agent's nudge_interval to 0 prevent?
- If background review fails, what impact does the user experience?

---

**One-liner: Background review is the agent's "post-conversation reflection" -- after a conversation ends, a background thread runs an independent agent instance to revisit the conversation and automatically update memories and skills. A shared MemoryStore makes changes take effect immediately; nudge_interval=0 prevents infinite recursion.**
