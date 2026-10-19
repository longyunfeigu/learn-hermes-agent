# s10: Subagent Delegation

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > [ s10 ] > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *A big task doesn't have to be crammed into a single context. Hand subtasks off to isolated contexts, and bring back only the results when they're done.*

## What problem does this chapter solve

By `s09`, the agent already has tools, persistence, memory, skills, and permissions. It can truly work independently.

But as tasks grow more complex, a problem starts to surface:

A user might say just one thing:

> "Research the new features in Python 3.12, then update the README."

To complete this, the agent might need to:

- Search through 10 articles
- Read 5 files
- Write files 3 times
- Run tests twice

All of these intermediate steps pile up in the same `messages` list, causing the context to balloon rapidly. If the user later asks a completely unrelated question, the model has to sift through a mountain of "search results" and "file contents" noise to find useful information.

More critically: if two subtasks are unrelated (e.g., "research new features" and "check test coverage"), their intermediate steps pollute each other, actually degrading the model's reasoning quality.

This is the problem subagents solve:

**Run localized tasks in isolated contexts, and bring back only the essential results. Keep the parent agent's context clean.**

![Parent-Child Agent Delegation](../../illustrations/en/s10-subagent-delegation/01-framework-parent-child.png)

## Key terminology

### What is a parent agent

The agent instance currently in conversation with the user, holding the main `messages`.

### What is a subagent

An agent instance temporarily created by the parent agent with its own independent `messages`. It returns a result after completing the subtask, then gets destroyed.

The subagent and parent agent share the same code path (both use `AIAgent.run_conversation()`). The only differences are:

- The subagent has its own `messages` (context isolation)
- The subagent's toolset is restricted (no delegation, no memory modification)
- The subagent consumes from the parent agent's iteration budget

### What is iteration budget sharing

The subagent doesn't get "a separate 90 API calls." It draws from the parent agent's budget:

```text
Parent agent budget = 90
  iter 1-10: Parent agent does its own work          (80 remaining)
  iter 11:   Parent agent dispatches subagent to search
             +-- Subagent uses 15 iters              (65 remaining)
  iter 12+:  Parent agent continues, starting from 65
```

This prevents subagents from consuming resources out of control.

### What is delegation depth limiting

Hermes Agent limits delegation depth to 2 levels: parent -> child. A subagent cannot spawn another subagent.

Why? Because recursive delegation spirals out of control easily. One level of delegation already covers the vast majority of scenarios.

## Minimal mental model

```text
Parent agent
  |
  | 1. Model calls the delegate_task tool
  |    passing goal + context + toolsets
  v
Subagent (independent messages, restricted toolset)
  |
  | 2. Reads files / searches / executes commands in its own context
  |    All intermediate steps stay in the subagent's messages
  v
Subagent returns final reply
  |
  | 3. Parent agent receives just a tool_result
  |    containing the subagent's final reply text
  v
Parent agent continues (context still clean)
```

There is only one key point:

**None of the subagent's intermediate steps flow back into the parent agent's messages. The parent agent receives only the final result.**

## Key data structures

### 1. delegate_task tool schema

```python
{
    "name": "delegate_task",
    "description": "Delegate a task to a subagent with isolated context",
    "parameters": {
        "goal": "str -- goal description for the subtask",
        "context": "str -- context information for the subagent (optional)",
        "toolsets": "list -- available toolsets for the subagent (optional)",
    },
}
```

The model initiates delegation by calling this tool.

### 2. Tools blocked for the subagent

```python
DELEGATE_BLOCKED_TOOLS = [
    "delegate_task",    # No recursive delegation
    "clarify",          # Cannot ask user questions (subagent has no user interaction channel)
    "memory",           # Cannot modify memory (prevent subtask side effects)
    "send_message",     # Cannot send messages to user
    "execute_code",     # Security restriction
]
```

Why restrict these?

- `delegate_task`: Prevents recursion
- `clarify`: The subagent has no user interaction channel; it cannot pause to ask the user
- `memory`: Subtasks are one-off; they should not produce persistent side effects
- `send_message`: The subagent should not bypass the parent agent to talk directly to the user

### 3. Default toolset for the subagent

```python
DEFAULT_TOOLSETS = ["terminal", "file", "web"]
```

Only the most basic capabilities: run commands, read/write files, search. Sufficient, but no overstepping.

### 4. Batch delegation

Hermes Agent supports dispatching up to 3 subagents in parallel:

```python
# Single task
delegate_task(goal="Research Python 3.12 new features")

# Batch tasks (up to 3 in parallel)
delegate_task(tasks=[
    {"goal": "Research Python 3.12 new features"},
    {"goal": "Check current test coverage"},
    {"goal": "Read the last 10 entries from CHANGELOG"},
])
```

Batch mode uses `ThreadPoolExecutor` for parallel execution, returning results in input order.

## Minimal implementation

### Step 1: Register the delegate_task tool

```python
from tools.registry import registry

def handle_delegate(args, **kwargs):
    goal = args["goal"]
    context = args.get("context", "")
    toolsets = args.get("toolsets", ["terminal", "file", "web"])
    
    # Build the subagent
    child = build_child_agent(goal, context, toolsets, kwargs)
    
    # Execute
    result = child.run_conversation(goal)
    
    return result["final_response"]

registry.register(
    name="delegate_task",
    toolset="agent",
    schema={...},
    handler=handle_delegate,
)
```

### Step 2: Build the subagent

```python
def build_child_agent(goal, context, toolsets, parent_kwargs):
    # Subagent system prompt: only includes task goal and context
    child_system_prompt = f"""You are an assistant focused on a single task.

Task goal: {goal}

Context: {context}

Return the result directly when done. Do not ask the user questions."""
    
    # Reuse the parent agent's API configuration
    child = AIAgent(
        base_url=parent_kwargs["base_url"],
        api_key=parent_kwargs["api_key"],
        model=parent_kwargs.get("delegation_model", parent_kwargs["model"]),
        system_prompt=child_system_prompt,
        enabled_toolsets=toolsets,
        disabled_tools=DELEGATE_BLOCKED_TOOLS,
        max_iterations=30,  # Subagent gets a smaller budget
        iteration_budget=parent_kwargs["iteration_budget"],  # Shares parent budget
    )
    
    return child
```

### Step 3: Handle budget deduction

```python
# After the subagent finishes
result = child.run_conversation(goal)

# The iterations consumed by the subagent have already been deducted from the shared budget
# When the parent agent continues, the budget automatically reflects the deduction
```

This is the minimal version. The subagent's `messages` are discarded once the function returns -- and that's exactly the point.

## Hermes Agent's unique design choices

### 1. The delegation model can differ

The subagent can use a cheaper model:

```yaml
# config.yaml
delegation:
  model: anthropic/claude-haiku
  provider: openrouter
```

The parent agent uses Claude Sonnet for main reasoning while the subagent uses Haiku for searching and file reading. This can significantly reduce costs.

### 2. Progress reporting

While the subagent executes, the parent agent can see what it's doing in real time:

```text
+-- [1] web_search "Python 3.12 features"
+-- [1] read_file "requirements.txt"
+-- [1] web_search "Python 3.12 type hints"
```

This is implemented via `tool_progress_callback`: each time the subagent executes a tool, it calls back to update the parent agent's progress display.

**Core mechanism:** The parent agent does not poll for the subagent's progress in a loop. Instead, every time the subagent executes a tool, it *pushes* progress to the parent agent's display layer through a callback function injected at creation time. This is the classic observer pattern / event callback pattern -- no polling needed.

Here's a minimal example illustrating the entire flow:

```python
# 1. Define "what to do when progress arrives"
def on_progress(event_type, tool_name, preview, args):
    print(f"Subagent is using: {tool_name} -- {preview}")

# 2. Inject this function when creating the subagent
child = AIAgent(
    tool_progress_callback=on_progress,   # <-- inject callback
)

# 3. Internally, the subagent calls this callback before each tool execution
#    (This code lives in AIAgent._handle_tool_calls -- you don't write it)
#    Pseudocode:
for tool in tools_to_run:
    self.tool_progress_callback("tool.started", tool.name, tool.preview, tool.args)
    result = self.execute(tool)          # Actually execute the tool
    self.tool_progress_callback("tool.completed", tool.name, ...)
```

The whole process is three steps: **define callback -> inject into subagent -> subagent triggers it automatically during execution**. The parent agent doesn't need to poll, and the subagent doesn't need to know who sees the progress -- it just calls the callback. Whether that prints to a terminal or sends to Telegram is determined by the callback's implementation.

**But why can the callback function display things on the parent agent's interface?** The answer is closures. The callback function *captures* the parent agent's display object at creation time. No matter who calls it later, it operates on the same object:

```python
# Parent agent side: create the callback
def make_callback(parent_spinner):
    """spinner is captured by the closure -- the function remembers its creation environment"""
    
    def callback(tool_name):
        # Even though this function will be called inside the subagent,
        # parent_spinner is the parent agent's object, captured at creation time
        parent_spinner.print_above(f"+-- {tool_name}")
    
    return callback
```

Timeline:

```text
1. Parent agent creates spinner (displayed on parent's terminal)
   spinner = KawaiiSpinner("Subagent working...")

2. Parent agent creates callback, wrapping its own spinner inside
   cb = make_callback(spinner)    # <-- spinner captured by closure

3. Parent agent injects the callback into the subagent
   child = AIAgent(tool_progress_callback=cb)

4. Subagent calls cb("web_search") when executing a tool
   -> cb internally runs spinner.print_above("+-- web_search")
   -> spinner belongs to the parent agent! So it prints on the parent's terminal
```

The subagent calls a function, but that function operates on the parent agent's object. Parent and child agents run in the same process, sharing memory, so the `spinner` captured by the closure is the very same spinner the parent agent is displaying. No cross-process communication needed.

### 3. Heartbeat mechanism

The heartbeat mechanism solves a very specific problem: **The Gateway has an "inactivity timeout" (default 30 minutes). If the parent agent shows no activity for too long, the Gateway considers it stuck and kills it.**

During normal operation, the parent agent updates its activity timestamp (`_last_activity_ts`) every time it calls the API or executes a tool. But after it dispatches a subagent, **the parent agent itself stops and waits for the result** -- it no longer calls any tools. From the Gateway's perspective, the parent agent "has no activity."

By the time the subagent finishes (which might take several minutes), the Gateway may have already killed the parent agent.

The solution is a heartbeat -- a background thread that says "I'm still alive" on behalf of the parent agent every 30 seconds:

```python
# Essentially a loop that updates the parent agent's activity timestamp every 30 seconds
def _heartbeat_loop():
    while not stop_event.wait(30):            # Wake up every 30 seconds
        parent_agent._touch_activity("subagent still working")
        #           ^ This updates _last_activity_ts = time.time()
        #             Gateway sees the timestamp updating and won't kill the parent

# Start the background thread
heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
heartbeat_thread.start()

# Subagent starts working
result = child.run_conversation(goal)

# Subagent is done, stop the heartbeat
stop_event.set()
```

That's all there is to it. Heartbeat = **a background thread that runs `_last_activity_ts = time.time()` every 30 seconds**, designed to fool the Gateway's inactivity detection so it knows "the parent agent isn't stuck, it's just waiting for the subagent."

### 4. Credential isolation

The subagent can use different API credentials:

```python
_resolve_delegation_credentials()  # Check delegation config
# If delegation config has its own provider/api_key, use those
# Otherwise fall back to the parent agent's credentials
```

This is useful in enterprise scenarios: the main agent uses a premium API key while subagents use rate-limited keys.

## How it connects to the main loop

The delegation logic is **not inside the core loop**. It's registered as a regular tool in the tool system.

```text
Core loop
  |
  | Model decides to call delegate_task
  v
dispatch("delegate_task", args)
  |
  v
delegate_task handler
  |
  | Creates child AIAgent
  | Calls child.run_conversation()
  | Subagent runs its own loop internally
  | Returns the final result
  v
tool_result written back to parent agent's messages
  |
  v
Core loop continues
```

From the loop's perspective, `delegate_task` is no different from `web_search` -- both are tool calls. The only difference is that it takes longer to execute and is more complex internally.

## Most common beginner mistakes

### 1. Letting the subagent delegate too

Recursive delegation = loss of control. Hermes Agent limits depth to 2 (MAX_DEPTH = 2); subagents cannot spawn further subagents.

### 2. Bringing the subagent's full messages back to the parent

The subagent's intermediate steps should not flow back to the parent agent. Returning only the final reply text is enough. Otherwise you defeat the purpose of context isolation.

### 3. Giving the subagent its own separate budget

The subagent should share the parent agent's budget. If each subagent independently gets 90 calls, 3 running in parallel means 270 calls -- costs and time spiral out of control.

### 4. Letting the subagent modify memory

Subagents are disposable. If one can modify MEMORY.md, two parallel subagents might write to the same file simultaneously -- causing conflicts. Memory modification should only be done by the parent agent.

### 5. Not reporting progress

The user waits 30 seconds with no feedback on screen and assumes the system is broken. Even when a subagent is busy, you need to show the user what's happening.

## Scope of this chapter

This chapter thoroughly covers three things:

1. **Context isolation** -- The subagent has independent messages; intermediate steps don't flow back to the parent agent
2. **Tool restrictions** -- The subagent cannot delegate, modify memory, or ask the user questions
3. **Budget sharing** -- The subagent consumes from the parent agent's budget, not a separate one

Deferred topics:

- Thread pool details for batch delegation -> production optimization
- Specifics of the heartbeat implementation -> Gateway chapter (`s12`)
- Complete credential routing logic -> Configuration chapter (`s11`)

If the reader can achieve "parent agent calls delegate_task, subagent completes the task in an isolated context, and only the result text flows back to the parent agent," this chapter has served its purpose.

## After this chapter, you should be able to answer

- Why do we need subagents instead of having the parent agent do everything directly?
- What is the relationship between the subagent's messages and the parent agent's messages?
- Why can't the subagent use the delegate_task and memory tools?
- What does iteration budget sharing mean?
- At which layer of the system architecture does the delegation mechanism live? Does it modify the core loop?

---

**In one sentence: A Hermes Agent subagent is a temporary AIAgent instance with its own independent messages. It shares the parent agent's API configuration and iteration budget. After completing its task, it returns only the result text -- none of its intermediate steps pollute the parent agent's context.**
