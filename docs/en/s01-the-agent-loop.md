# s01: The Agent Loop

`s00 > [ s01 ] > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Without the loop, there is no agent.*  
> This chapter teaches you to build a minimal agent loop and explains why Hermes Agent chose the "synchronous body + async bridge" approach.

## What Problem This Chapter Solves

A language model on its own only "generates the next piece of content." It cannot execute commands, observe results, and reason further based on those results by itself.

Without a layer of code that repeatedly does this, the model is just "a program that can talk" -- not yet "an agent that can act."

But the Hermes Agent loop is more than a `while True`. From the start it faces real-world problems that simple tutorial agents don't:

1. **The same loop must serve two entry points** -- CLI is a user calling directly from the terminal; Gateway is messages arriving simultaneously from multiple platforms. Therefore the loop itself cannot depend on terminal I/O.
2. **Gateway creates a new agent instance for every message** -- there is no single global agent that stays alive. Each incoming message spawns an instance, feeds it the history, runs to completion, and ends.
3. **Some tools are async** -- most tools (file I/O, terminal commands) are synchronous, but network requests and browser operations are async. The loop itself stays synchronous and bridges to async tools.

This chapter covers only the minimal version. The complexities above are expanded in subsequent chapters.

## Key Terms

### run_conversation

The entry method for the Hermes Agent loop.

It takes a user message and an optional list of historical messages, runs the loop until the model stops calling tools, and returns the final reply along with the complete message history.

Key point: it is a plain `def`, not an `async def`. This is a deliberate design choice.

### iteration and iteration budget

One API call counts as one iteration. Hermes Agent defaults to a maximum of 90 iterations.

A **budget** can be thought of as an "allowance" or "credit limit" -- the ceiling on how many API calls this conversation is allowed to make in total. Why "budget" instead of "max_iterations"? Because it is a **resource that can be consumed and shared**, not just a static counter.

Simple example:

```text
budget = 90

User: "Refactor this file for me"
  iter 1: Model says "Let me read the file first" -> calls read_file  (remaining: 89)
  iter 2: Model says "Let me check the tests too"  -> calls read_file  (remaining: 88)
  iter 3: Model says "I'll make the changes"        -> calls edit_file  (remaining: 87)
  iter 4: Model says "Done"                          -> stop             (remaining: 86)
```

What "shared budget" means in a Gateway scenario:

```text
Parent agent budget = 90
  iter 1-10:  Parent agent works on its own               (remaining: 80)
  iter 11:    Parent agent delegates to a sub-agent for search
              +-- Sub-agent uses 15 iterations             (remaining: 65)
  iter 12+:   Parent agent continues, starting from 65
```

The sub-agent doesn't get "another 90." It draws from the parent agent's wallet. That is why it is called a budget.

![Iteration Budget Concept](../../illustrations/en/s01-agent-loop/06-infographic-budget-chalkboard.png)

### finish_reason

The model's answer to "why did I stop?"

- `stop`: finished speaking
- `tool_calls`: wants to call tools
- `length`: output was truncated

The loop uses this to decide what to do next.

### messages and api_messages

Hermes Agent maintains two copies of messages internally:

- `messages`: your internal "complete ledger" that contains everything, including internal state (such as the `reasoning` field)
- `api_messages`: a cleaned copy derived from `messages` right before each API call, containing only fields the model can understand

Simple example:

```python
# messages (full internal version)
messages = [
    {"role": "user", "content": "What's the weather today?"},
    {
        "role": "assistant",
        "content": "Let me check",
        "reasoning": "User asked about weather, I should call a tool",  # <- internal field
        "_internal_token_count": 42,                                     # <- internal field
    },
]

# Clean up before calling the API ->
api_messages = [
    {"role": "system", "content": "You are Hermes..."},   # <- prepended
    {"role": "user", "content": "What's the weather today?"},
    {
        "role": "assistant",
        "content": "Let me check",
        # reasoning and _internal_token_count have been stripped
    },
]

client.chat.completions.create(messages=api_messages, ...)
```

Why maintain two copies?

- `messages` must be persisted and available for debugging -- the more information the better
- `api_messages` must be sent to an OpenAI-compatible API -- extra fields cause errors or waste tokens

In one sentence: **messages is the draft; api_messages is the letter you actually mail out.**

![messages vs api_messages](../../illustrations/en/s01-agent-loop/07-comparison-messages-chalkboard.png)

You can ignore this distinction in the first teaching version, but you should know it exists.

![Agent Loop Core Flow](../../illustrations/en/s01-agent-loop/05-flowchart-chalkboard.png)

## Minimal Mental Model

```text
user message
   |
   v
Assemble system prompt (persona + memory + project config + tool definitions)
   |
   v
 model API (OpenAI-compatible format)
   |
   +-- finish_reason: stop -----> return final reply
   |
   +-- finish_reason: tool_calls --> execute tools
                                       |
                                       v
                                  tool result
                                       |
                                       v
                                  write back to messages
                                       |
                                       v
                                  next iteration
```

What truly matters is not "having a loop."

What truly matters is two things:

1. **Tool results must be written back into the message history** -- otherwise the model cannot see the execution results on its next turn.
2. **The system prompt is reassembled at the front of messages for every API call** -- it is not part of the messages list; it is prepended separately each time.

## Key Data Structures

### Message

An OpenAI-format message. Three roles:

```python
# User message
{"role": "user", "content": "Search for what's new in Python 3.12"}

# Assistant message (with tool calls)
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_abc",
            "function": {
                "name": "web_search",
                "arguments": '{"query": "Python 3.12 new features"}',
            },
        }
    ],
}

# Tool result
{
    "role": "tool",
    "tool_call_id": "call_abc",
    "content": "Python 3.12 introduces...",
}
```

Note `tool_call_id` -- it matches a result to its corresponding call. The model may invoke multiple tools in a single turn, and every result must be matched to the right call.

### System Prompt

Not stored in messages. Prepended as the first system-role message before every API call:

```python
api_messages = [{"role": "system", "content": system_prompt}] + messages
```

The Hermes Agent system prompt is assembled from multiple sources: persona file (SOUL.md), memory (MEMORY.md), project configuration (HERMES.md), tool definitions, and skill index. These are covered in detail in `s04`.

## Minimal Implementation

### Step 1: Create the Client

```python
from openai import OpenAI

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key="...")
```

All model providers are accessed through this single client. Switching models only requires changing `base_url` and `api_key`.

### Step 2: Build the Loop

```python
def run_conversation(user_message, system_prompt, tools, max_iterations=90):
    messages = [{"role": "user", "content": user_message}]
    
    for i in range(max_iterations):
        # Assemble API messages: system prompt + conversation history
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        
        # Call the model
        response = client.chat.completions.create(
            model="anthropic/claude-sonnet-4",
            messages=api_messages,
            tools=tools,
        )
        
        assistant_msg = response.choices[0].message
        
        # Write the assistant reply back into history (whether or not it has tool_calls)
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (assistant_msg.tool_calls or [])
            ] or None,
        })
        
        # No tool_calls -> done
        if not assistant_msg.tool_calls:
            return {"final_response": assistant_msg.content, "messages": messages}
        
        # Execute each tool and write results back
        for tool_call in assistant_msg.tool_calls:
            output = run_tool(tool_call.function.name, tool_call.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output,
            })
    
    return {"final_response": "Reached maximum iteration count", "messages": messages}
```

This is the minimal Hermes Agent loop.

### How It Relates to the Real Code

The real `AIAgent.run_conversation()` is far more complex, but the core skeleton is exactly the same:

1. Assemble messages
2. Call the API
3. Write back the assistant message
4. If there are tool_calls, execute them and write back results
5. Continue

On top of this skeleton, the real code adds: preflight compression checks, plugin hooks, memory injection, reasoning-field handling, interrupt support, streaming output, and error retries. All of these are expanded in later chapters.

## Three Unique Designs in the Hermes Agent Loop

### 1. Instance Management in Gateway: Cache and Reuse, Not Recreate

In CLI mode a single AIAgent instance runs from start to finish.

The **simplified teaching explanation** for Gateway mode is "a new instance is created for every message." The actual implementation is smarter -- Gateway maintains an instance cache:

```python
# gateway/run.py
self._agent_cache: Dict[str, tuple] = {}  # session_key -> (AIAgent, config_signature)
```

The flow:

```text
Message arrives -> compute config signature (model + api_key + provider + toolsets)
               -> check cache
                  +-- hit  -> reuse existing instance (system prompt and tool defs unchanged)
                  +-- miss -> create new instance, store in cache
               -> update lightweight per-message fields (callbacks, reasoning_config)
               -> call run_conversation()
```

The cache is only invalidated when a user runs `/new` (reset session), `/model` (switch model), or a fallback is triggered.

The most important reason for reusing instances is **prompt caching** -- the Anthropic API requires the system prompt to stay the same across turns to get a cache hit. Reusing the instance = saving money and time.

But the core principle holds: **do not store cross-message state in instance variables.** Conversation history is passed in from SQLite every time; it is not stored in instance memory. Agent instances can be evicted and rebuilt at any moment, and code must not rely on them "staying alive."

### 2. System Prompt Caching

On the first call the system prompt is assembled from multiple sources and cached. Subsequent calls reuse the cached version without reassembling.

This is not just a performance optimization. Anthropic's prompt caching mechanism requires the system prompt to remain unchanged across turns. If it is reassembled every turn (for example, because a memory file was modified), the cache is invalidated.

So when Hermes Agent continues a session, it reads back the previously stored system prompt from SQLite rather than reassembling it.

### 3. Synchronous Loop + Async Bridge

The loop itself is a synchronous `def`. But some tools (network requests, browser operations) require async.

**The core problem**: Most tools in the agent loop are synchronous (read files, write files, run commands), but a few are async (HTTP requests, browser automation). How do you support both in one loop?

Two approaches:

**Approach A: Make the entire loop `async def`**

```python
async def run_conversation(...):
    ...
    result = await run_tool(...)  # await every tool
```

Looks uniform, but the cost is: all synchronous tools need an async wrapper, error stack traces get more complex, debugging gets harder.

**Approach B (Hermes's choice): The loop is synchronous; async tools are bridged on demand**

```python
def run_conversation(...):          # plain def, not async
    ...
    if tool_is_async:
        result = event_loop.run(async_tool(...))  # bridge to the event loop
    else:
        result = sync_tool(...)     # call directly
```

**What is a "persistent event loop"?**

`asyncio.run()` creates a new event loop on every call and destroys it afterward. Hermes Agent does not use this pattern. Instead, it creates one event loop at startup and keeps it alive for reuse:

```python
# Created once at startup
loop = asyncio.new_event_loop()

# Reused every time an async tool needs to run
def bridge_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
```

Why persistent? Because some async resources (such as browser sessions and WebSocket connections) live across multiple tool calls. If a new event loop were created each time, those connections would break.

**One-sentence summary**: The main loop stays synchronous for simplicity. Only when it encounters an async tool does it hand the task to a resident event loop for execution, then takes the result back and continues the synchronous flow.

## Most Common Beginner Mistakes

### 1. Not Writing Back the Assistant Message

Tool results are written back, but the assistant message is not. On the next API call the model cannot see what it said in the previous turn.

### 2. Not Binding tool_call_id

The model called two tools in one turn, but neither result carries an id. The model cannot tell which result corresponds to which call.

### 3. Putting the System Prompt Inside the Messages List

The system prompt should be prepended at the time of each API call, not stored as part of the messages list. Otherwise it gets persisted, compressed, and duplicated.

### 4. Not Setting an Iteration Limit

A loop without `max_iterations` will run forever if the model keeps calling tools. Hermes Agent defaults to 90.

### 5. Assuming Agent Instances Are Long-Lived

In Gateway mode every message gets a new instance. Do not store cross-message state in instance variables.

## Teaching Boundary

This chapter only needs to drive home one thing:

**messages -> model -> tool_calls -> tool_result -> next turn**

This loop is the foundation for every mechanism that follows.

What is deliberately left out:

- How tools are registered and dispatched -> `s02`
- How conversations are persisted -> `s03`
- How the system prompt is assembled -> `s04`
- What to do when context gets too long -> `s05`
- What to do when the API errors out -> `s06`

If you can write the minimal loop above from memory, you have completed this chapter.

## One Sentence to Remember

**The Hermes Agent loop is synchronous, calls any model through an OpenAI-compatible interface, is shared by Gateway and CLI, and tool results must be written back into messages for the model to keep working.**
