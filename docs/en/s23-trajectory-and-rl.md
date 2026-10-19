# s23: Trajectory & RL Training

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > [ s23 ] > s24 > s25 > s26 > s27`

> *s20-s22 enabled the agent to learn at runtime -- updating memory, creating skills, attaching hooks. This chapter enables the agent to evolve offline -- turning conversation trajectories into training data and using reinforcement learning to train the next generation of models.*

![Trajectory and RL Pipeline](../../illustrations/en/s23-trajectory-rl/01-flowchart-rl-pipeline.png)

## What Problem Does This Chapter Solve

The background review from s20 and the skill creation from s21 represent **runtime learning** -- knowledge the agent discovers during a conversation is passed to its future self through files (MEMORY.md, skills/).

But this has a ceiling: files store "knowledge," not "capability." The agent may know that "the user dislikes type hints" (knowledge), but its ability to write code doesn't improve just because of that memory.

**To improve capability itself, you need to train the model.**

The full pipeline:

```text
Conversation -> trajectory collection -> trajectory compression -> reward scoring -> RL training -> better model
```

**Scenario: From 1,000 conversations to a stronger model.**

```text
1. batch_runner runs the agent on 500 prompts, 2 runs per prompt
   -> 1,000 conversation trajectories, stored as JSONL

2. trajectory_compressor compresses long trajectories to under 15K tokens
   -> Preserves key information at head and tail, replaces middle with summaries

3. Environment scoring: each trajectory receives 0-2 points based on task completion
   -> Complete = 2.0, partial = 1.0, failure = 0.0

4. GRPO training: fine-tune the model using reward signals
   -> 2,500 steps, LoRA rank 32, lr 4e-5

5. The new model performs better on the same prompts
```

This isn't theoretical -- Hermes Agent's model is iterated exactly this way.

## Suggested Reading

- [`s01-the-agent-loop.md`](./s01-the-agent-loop.md) -- Each trajectory is essentially a complete record of one `run_conversation` call
- [`s20-background-review.md`](./s20-background-review.md) -- Runtime learning vs. offline training comparison
- [`s05-context-compression.md`](./s05-context-compression.md) -- Trajectory compression reuses the ideas from context compression

## Key Concepts

### What Is a Trajectory

A record of one complete conversation, formatted in ShareGPT format:

```json
[
  {"from": "system", "value": "You are a helpful assistant..."},
  {"from": "human",  "value": "Write me a Python script"},
  {"from": "gpt",    "value": "<think>Let me analyze the requirements first...</think>Sure, I'll write..."},
  {"from": "gpt",    "value": "<tool_call>{\"name\": \"write_file\", ...}</tool_call>"},
  {"from": "tool",   "value": "<tool_response>{\"content\": \"Written 50 chars\"}</tool_response>"},
  {"from": "gpt",    "value": "The file is ready. You can try running it."}
]
```

Nearly identical to the session messages in SQLite, but with two key transformations:
- Reasoning (the model's thought process) is uniformly wrapped in `<think>` tags
- Tool calls are uniformly wrapped in `<tool_call>` / `<tool_response>` tags

### What Is batch_runner

A tool for running the agent in bulk. It takes a list of prompts (JSONL), launches an agent instance for each prompt, and collects trajectories and statistics.

Supports parallelism, checkpoint resumption, and automatic filtering of low-quality samples.

### What Is trajectory_compressor

A trajectory compressor. Many conversation trajectories are very long (tens of thousands of tokens), making direct training inefficient. The compressor preserves key content at the head and tail, replaces the middle section with an LLM-generated summary, and brings the trajectory down to a target length (default 15,250 tokens).

### What Is GRPO

Group Relative Policy Optimization. A reinforcement learning algorithm better suited for language models than PPO. Core idea: generate multiple trajectories for the same prompt, use reward signals to tell the model "which one is better," and update the model toward the better outcomes.

## Minimal Mental Model

```text
Phase 1: Collection
  prompts.jsonl -> batch_runner -> trajectory_samples.jsonl
                                  + tool_stats
                                  + reasoning_stats

Phase 2: Compression
  trajectory_samples.jsonl -> trajectory_compressor -> compressed.jsonl
    (50K tokens)              (preserve head/tail,     (15K tokens)
                               compress middle)

Phase 3: Scoring
  compressed.jsonl -> environment scoring function -> scored.jsonl
    each trajectory + original prompt                (trajectory + reward)

Phase 4: Training
  scored.jsonl -> GRPO trainer -> new model weights
    multiple trajectories per prompt     LoRA adapters
    reinforce high-reward, weaken low-reward
```

## Key Data Structures

### Trajectory Record (batch_runner output)

```json
{
  "trajectory": [
    {"from": "system", "value": "..."},
    {"from": "human", "value": "..."},
    {"from": "gpt", "value": "<think>...</think>..."}
  ],
  "tool_stats": {
    "terminal": {"count": 5, "success": 4, "failure": 1},
    "read_file": {"count": 3, "success": 3, "failure": 0}
  },
  "reasoning_stats": {
    "total_assistant_turns": 8,
    "turns_with_reasoning": 6,
    "turns_without_reasoning": 2,
    "has_any_reasoning": true
  },
  "completed": true,
  "api_calls": 12,
  "toolsets_used": ["terminal", "file"]
}
```

### Compression Configuration

```yaml
tokenizer_name: "moonshotai/Kimi-K2-Thinking"
target_max_tokens: 15250
summary_target_tokens: 750

# Protection policy: don't compress head or tail
protect_first_system: true
protect_first_human: true
protect_first_gpt: true
protect_last_n_turns: 4

# Summarization model
summarization_model: "google/gemini-3-flash-preview"
summarization_temperature: 0.3
```

### Reward Functions

```python
def correctness_reward(prompts, completions, answer):
    """2.0 points if fully correct, 0.0 if wrong."""
    rewards = []
    for completion, expected in zip(completions, answer):
        if expected in completion:
            rewards.append(2.0)
        else:
            rewards.append(0.0)
    return rewards

def format_reward(completions):
    """0.5 points if format is correct (has <think> and <tool_call> tags)."""
    rewards = []
    for c in completions:
        score = 0.0
        if "<think>" in c and "</think>" in c:
            score += 0.25
        if "<tool_call>" in c:
            score += 0.25
        rewards.append(score)
    return rewards
```

Reward functions are composable -- correctness provides the highest score (2.0), while format serves as an auxiliary signal (0.5). GRPO uses a weighted sum as the final reward.

## Minimal Implementation

### Step 1: Trajectory Format Conversion

Convert the messages from `run_conversation` into ShareGPT format:

```python
def convert_to_trajectory(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to ShareGPT trajectory format."""
    trajectory = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Role mapping
        if role == "system":
            from_field = "system"
        elif role == "user":
            from_field = "human"
        elif role == "assistant":
            from_field = "gpt"
            # Tool calls: wrap in <tool_call> tags
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tc_text = json.dumps({
                        "name": fn.get("name", ""),
                        "arguments": json.loads(fn.get("arguments", "{}")),
                    }, ensure_ascii=False)
                    content += f"\n<tool_call>\n{tc_text}\n</tool_call>"
        elif role == "tool":
            from_field = "tool"
            # Wrap in <tool_response> tags
            tool_id = msg.get("tool_call_id", "")
            content = (f"<tool_response>\n"
                       f'{{"tool_call_id": "{tool_id}", '
                       f'"content": {json.dumps(content, ensure_ascii=False)}}}\n'
                       f"</tool_response>")
        else:
            continue

        trajectory.append({"from": from_field, "value": content})

    return trajectory
```

### Step 2: Tool Statistics Extraction

```python
def extract_tool_stats(messages: list[dict]) -> dict:
    """Count tool usage: how many calls, successes, failures per tool."""
    stats: dict[str, dict] = {}
    # Find all tool_call -> tool pairs
    tool_calls = {}
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                tool_calls[tc["id"]] = fn.get("name", "unknown")
        elif msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            tool_name = tool_calls.get(tc_id, "unknown")
            if tool_name not in stats:
                stats[tool_name] = {"count": 0, "success": 0, "failure": 0}
            stats[tool_name]["count"] += 1
            content = msg.get("content", "")
            if "error" in content.lower()[:100]:
                stats[tool_name]["failure"] += 1
            else:
                stats[tool_name]["success"] += 1
    return stats
```

### Step 3: Batch Collection (Simplified batch_runner)

```python
def run_batch(prompts: list[str], output_path: str):
    """Run agent on each prompt, collect trajectories."""
    results = []
    for i, prompt in enumerate(prompts):
        conn = init_db(":memory:")
        session_id = create_session(conn)
        cached_prompt = build_system_prompt(os.getcwd())

        try:
            result = run_conversation(prompt, conn, session_id, cached_prompt)
            messages = result["messages"]
            trajectory = convert_to_trajectory(messages)
            tool_stats = extract_tool_stats(messages)

            results.append({
                "prompt_index": i,
                "trajectory": trajectory,
                "tool_stats": tool_stats,
                "completed": result.get("final_response") is not None,
                "api_calls": len([m for m in messages if m.get("role") == "assistant"]),
            })
        except Exception as e:
            results.append({
                "prompt_index": i,
                "trajectory": [],
                "completed": False,
                "error": str(e),
            })
        finally:
            conn.close()

        print(f"  [{i+1}/{len(prompts)}] {'OK' if results[-1].get('completed') else 'FAIL'}")

    # Write to JSONL
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = sum(1 for r in results if r.get("completed"))
    print(f"\nBatch complete: {ok}/{len(prompts)} succeeded -> {output_path}")
    return results
```

### Step 4: Trajectory Compression (Simplified)

```python
def compress_trajectory(
    trajectory: list[dict],
    target_tokens: int = 15250,
    protect_last_n: int = 4,
) -> tuple[list[dict], dict]:
    """
    Compress a trajectory to fit within target token budget.

    Strategy: protect head (system + first human + first gpt) and
    tail (last N turns). Compress middle into a summary.

    Returns (compressed_trajectory, metrics).
    """
    original_tokens = estimate_tokens_trajectory(trajectory)
    if original_tokens <= target_tokens:
        return trajectory, {
            "was_compressed": False,
            "original_tokens": original_tokens,
            "compressed_tokens": original_tokens,
        }

    # Protect head: system + first human + first gpt/tool
    head = []
    rest = list(trajectory)
    for role in ["system", "human", "gpt"]:
        for i, turn in enumerate(rest):
            if turn["from"] == role:
                head.append(rest.pop(i))
                break

    # Protect tail
    tail = rest[-protect_last_n:] if len(rest) > protect_last_n else []
    middle = rest[:-protect_last_n] if tail else rest

    # Compress middle section into a summary
    if middle:
        summary_text = _summarize_middle(middle)
        compressed_middle = [{"from": "system", "value": f"[Summary of {len(middle)} turns]\n{summary_text}"}]
    else:
        compressed_middle = []

    compressed = head + compressed_middle + tail
    compressed_tokens = estimate_tokens_trajectory(compressed)

    return compressed, {
        "was_compressed": True,
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "turns_removed": len(middle),
    }


def _summarize_middle(turns: list[dict]) -> str:
    """Generate a concise summary of the middle turns."""
    # Teaching version uses rule-based summary; production version uses LLM
    tools_used = set()
    errors = 0
    for t in turns:
        if "<tool_call>" in t.get("value", ""):
            import re as _re
            names = _re.findall(r'"name":\s*"(\w+)"', t["value"])
            tools_used.update(names)
        if t["from"] == "tool" and "error" in t.get("value", "").lower():
            errors += 1

    parts = [f"Agent executed {len(turns)} turns."]
    if tools_used:
        parts.append(f"Tools used: {', '.join(sorted(tools_used))}.")
    if errors:
        parts.append(f"Encountered {errors} error(s) and recovered.")
    return " ".join(parts)


def estimate_tokens_trajectory(trajectory: list[dict]) -> int:
    """Rough token estimate for a trajectory."""
    total_chars = sum(len(t.get("value", "")) for t in trajectory)
    return total_chars // 4  # rough estimate
```

## Walkthrough: The Full Lifecycle of a Trajectory

```text
=== Phase 1: Collection ===

prompt: "Write a Python script to convert Markdown to HTML"

Agent executes:
  Turn 1: [gpt] <think>I should use the markdown library...</think> I'll write a script.
  Turn 2: [gpt] <tool_call>{"name": "terminal", "arguments": {"command": "pip install markdown"}}</tool_call>
  Turn 3: [tool] <tool_response>{"content": "Successfully installed markdown-3.6"}</tool_response>
  Turn 4: [gpt] <tool_call>{"name": "write_file", ...}</tool_call>
  Turn 5: [tool] <tool_response>{"content": "Written 120 chars"}</tool_response>
  Turn 6: [gpt] <tool_call>{"name": "terminal", "arguments": {"command": "python convert.py test.md"}}</tool_call>
  Turn 7: [tool] <tool_response>{"content": "<h1>Hello</h1>"}</tool_response>
  Turn 8: [gpt] Script is ready and tests pass.

tool_stats: terminal(2/2), write_file(1/1)
reasoning_stats: 1/4 turns with <think>
completed: true

=== Phase 2: Compression ===

Original: 8 turns, ~3,000 tokens -> no compression needed (< 15,250)
(For a complex conversation with 50K tokens, Turns 3-5 would be compressed into a summary)

=== Phase 3: Scoring ===

correctness_reward: script runs and output is correct -> 2.0
format_reward: has <think> and <tool_call> -> 0.5
total_reward: 2.5

=== Phase 4: Training ===

GRPO receives multiple trajectories for the same prompt (e.g., 4):
  Trajectory A: reward 2.5 (success + good format)
  Trajectory B: reward 2.0 (success but no think)
  Trajectory C: reward 0.5 (failure but correct format)
  Trajectory D: reward 0.0 (failure + bad format)

Model update direction: reinforce behavior patterns from A and B, weaken C and D
```

## Why Not Just Use SFT (Supervised Fine-Tuning)

SFT only learns from "correct answers." But agent conversations contain a large amount of **exploratory behavior** -- trial and error, backtracking, switching approaches -- behaviors that don't have a "correct answer," only degrees of "how good or bad."

RL's advantage: **it can learn the difference between "almost right" and "completely wrong."** SFT only has two states: "learned" and "didn't learn."

| | SFT | RL (GRPO) |
|---|---|---|
| Signal | Binary: right/wrong | Continuous: reward score |
| What it learns | Imitate correct trajectories | Learn from good/bad comparisons |
| Attitude toward exploration | Ignores it | Failed exploration also has learning value |
| Data efficiency | Requires high-quality correct answers | Any trajectory is usable (as long as there's a reward) |

## Common Beginner Mistakes

### 1. Not Filtering Out Zero-Reasoning Samples

If the agent produces a trajectory with no `<think>` reasoning at all, that trajectory teaches the model "you can act without thinking."

**Fix: batch_runner automatically discards samples where `has_any_reasoning=false`.**

### 2. Compressing Away the Head or Tail

The head (system prompt + user question) defines what the task is. The tail (last few turns) contains the final result. Compress away either one, and the model learns "a middle process with no goal."

**Fix: protect_first_system/human/gpt + protect_last_n_turns are never compressed.**

### 3. Reward Function That Only Checks Correctness

Scoring only by "was the final result correct." The model learns that "guessing right is all that matters" -- it will skip reasoning and jump straight to guessing answers.

**Fix: Stack format_reward on top, rewarding good reasoning format and penalizing trajectories without `<think>`.**

### 4. Running Each Prompt Only Once

GRPO needs to compare multiple trajectories for the same prompt. Running once gives nothing to compare against.

**Fix: Run each prompt at least 2 times (configurable in batch_runner).**

## Teaching Boundaries

This chapter covers four things:

1. **Trajectory format** -- ShareGPT format, reasoning tags, tool_call/tool_response tags
2. **Batch collection** -- batch_runner's prompt-to-trajectory pipeline
3. **Trajectory compression** -- Protect head and tail, compress the middle, token budget
4. **RL training basics** -- Reward functions, GRPO approach, why SFT alone isn't enough

Not covered:

- Mathematical derivation of GRPO -> RL theory course
- Specific APIs for Atropos / Tinker -> platform integration
- WandB configuration and metric interpretation -> MLOps details
- Multi-GPU training and distributed scheduling -> infrastructure
- Specific data sources and cleaning -> data engineering

## How This Chapter Relates to Others

- **s01**'s core loop -> each trajectory is a complete record of one `run_conversation` call
- **s05**'s context compression -> trajectory compression reuses the same "protect head and tail, compress middle" strategy
- **s20**'s background review -> runtime learning (modifying files); s23 is offline learning (modifying the model)
- **s21**'s skill creation -> runtime evolution; s23 is genetic-level evolution
- **s24**'s plugin architecture -> RL environments can be extended as plugins

**s20-s21 represent the agent's "learning"; s23 represents the agent's "evolution."** Learning changes knowledge; evolution changes capability itself.

## After This Chapter, You Should Be Able to Answer

- Why is reasoning wrapped in `<think>` tags in the trajectory format?
- Why can't the head and tail be compressed during trajectory compression?
- Why does GRPO need multiple trajectories for the same prompt?
- What goes wrong if the reward function only measures correctness?
- What level of problem does runtime learning (s20-s21) solve versus offline training (s23)?

---

**One-liner: Conversation trajectories are the agent's experience records. batch_runner collects them, trajectory_compressor compresses them, and GRPO learns from them -- making the next generation model's capability itself stronger, not just more knowledgeable.**
