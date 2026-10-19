# s06: Error Recovery

`s00 > s01 > s02 > s03 > s04 > s05 > [ s06 ] > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *Errors are not exceptions -- they are a normal branch that the main loop must account for.*

## What problem does this chapter solve

By `s05`, the agent has a full tool system, persistence, prompt assembly, and context compression.

At this point the system is no longer a demo but a program that actually does things. Problems come with it:

- The model's output gets cut off mid-stream (`finish_reason: length`)
- The context is too long and the API returns a 400
- Network timeouts, rate limits, service flaps
- API key expired or quota exhausted
- Model does not exist or has been retired

Without a recovery mechanism, the main loop crashes on the first error.

But many failures do not mean "the task has truly failed." They only mean:

**This turn needs a different way to continue.**

Hermes Agent does not use a simple try/except + retry. It first classifies the error, then selects a recovery strategy based on the classification. And because it supports 200+ models across multiple providers, the error landscape is far wider than a single-provider agent.

![Error Classification and Recovery](../../illustrations/en/s06-error-recovery/01-flowchart-error-classification.png)

## Key terms explained

### What is error classification

Different errors require different handling.

Rate limiting (429) should back off and retry. Context overflow (400) should trigger compression. Auth failure (401) should rotate credentials. Model not found (404) should fall back to a backup model.

Without classifying first, every error goes down the same path -- something that should retry gets compressed, something that should give up enters an infinite loop.

### What is failover

When the current model or provider has an unrecoverable problem, automatically switch to a backup model.

For example: the primary model is rate-limited, so the system automatically switches to a backup model and continues working. No manual intervention needed.

### What is backoff retry

Instead of retrying immediately after an error, wait for a period of time.

How long? Exponential increase plus random jitter. First wait 5 seconds, second wait 10 seconds, third wait 20 seconds... plus a random offset to prevent multiple Gateway sessions from retrying at the same instant.

### What is continuation

Model output was truncated (`finish_reason: length`). This does not mean the model cannot do it -- it means there was not enough output space in this turn.

Continuation means appending a message telling the model "continue exactly from where you stopped, do not start over," then making another API call.

## Minimal mental model

The teaching version only needs to distinguish 4 categories of problems:

```text
1. Output truncated (finish_reason: length)
   -> Inject a continuation prompt and retry

2. Context too long (400 / context overflow)
   -> Trigger compression (s05) and retry

3. Transient failure (429 rate limit / 503 overloaded / timeout)
   -> Back off and retry

4. Unrecoverable (401 auth failure / 404 model not found / quota exhausted)
   -> Attempt failover to a backup model, or give up
```

```text
API call
  |
  +-- Success, finish_reason: stop
  |      -> Normal completion
  |
  +-- Success, finish_reason: tool_calls
  |      -> Execute tools, continue loop
  |
  +-- Success, finish_reason: length
  |      -> Continuation (up to 3 times)
  |
  +-- Failure, recoverable
  |      -> Classify -> backoff / compress / rotate credentials
  |
  +-- Failure, unrecoverable
         -> Failover / give up
```

## Key data structures

### 1. Error classification result

```python
classified = {
    "reason": "rate_limit",        # Why it failed
    "retryable": True,             # Can it be retried
    "should_compress": False,      # Should compression be triggered
    "should_fallback": False,      # Should it fail over to a backup model
}
```

This separates "what the error looks like" from "what to do next." The loop does not need to understand the specifics of the error -- it just reads a few boolean flags from the classification result to know which path to take.

### 2. Failure reasons

Hermes Agent defines over a dozen failure reasons, but for teaching purposes start with these:

```text
rate_limit     -> Back off and retry
overloaded     -> Back off and retry
timeout        -> Rebuild connection + retry
context_overflow -> Trigger compression
billing        -> Rotate credentials or fall back to backup model
auth           -> Rotate credentials or fall back to backup model
model_not_found -> Fall back to backup model
```

Each reason maps to a different recovery action. That is the value of classification.

### 3. Continuation prompt

```python
CONTINUE_MESSAGE = (
    "Your response was cut off. Continue EXACTLY from where you stopped. "
    "Do not restart, do not repeat, do not summarize what came before."
)
```

This prompt is critical. If you just say "continue," the model often restarts with a summary or begins from the top.

## Minimal implementation

### Step 1: Write an error classifier

```python
def classify_error(status_code, error_message):
    if status_code == 429:
        return {"reason": "rate_limit", "retryable": True, "should_compress": False, "should_fallback": False}
    
    if status_code == 400 and "context" in error_message.lower():
        return {"reason": "context_overflow", "retryable": True, "should_compress": True, "should_fallback": False}
    
    if status_code in (500, 502, 503):
        return {"reason": "server_error", "retryable": True, "should_compress": False, "should_fallback": False}
    
    if status_code in (401, 403):
        return {"reason": "auth", "retryable": False, "should_compress": False, "should_fallback": True}
    
    if status_code == 404:
        return {"reason": "model_not_found", "retryable": False, "should_compress": False, "should_fallback": True}
    
    return {"reason": "unknown", "retryable": False, "should_compress": False, "should_fallback": False}
```

The key idea behind this step:

> The classifier translates "HTTP status code + error message" into "should retry / should compress / should fail over / should give up." The loop only reads the translation.

### Step 2: Write backoff retry

```python
def jittered_backoff(attempt, base_delay=5.0, max_delay=120.0):
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    jitter = random.uniform(0, delay * 0.5)
    return delay + jitter
```

The key idea behind this step:

> Exponential increase plus random jitter. The increase gives the server breathing room; the jitter prevents multiple Gateway sessions from retrying at the same instant.

### Step 3: Hook into the main loop

```python
retry_count = 0
continuation_count = 0

while iteration < max_iterations:
    try:
        response = client.chat.completions.create(...)
    except Exception as e:
        classified = classify_error(getattr(e, "status_code", None), str(e))
        
        if classified["should_compress"]:
            messages = compress(messages)
            continue
        
        if classified["should_fallback"] and fallback_model:
            switch_to_fallback_model()
            continue
        
        if classified["retryable"] and retry_count < 3:
            retry_count += 1
            time.sleep(jittered_backoff(retry_count))
            continue
        
        raise  # Unrecoverable, propagate upward
    
    # After getting a response
    finish_reason = response.choices[0].finish_reason
    
    if finish_reason == "length" and continuation_count < 3:
        continuation_count += 1
        messages.append({"role": "user", "content": CONTINUE_MESSAGE})
        continue
    
    # Normal processing of tool_calls or completion
    ...
```

Note the key point here: **classification and recovery are two separate steps.** Classify first, then take the corresponding recovery path. Each path has its own retry budget.

### Step 4: Failover

```python
def switch_to_fallback_model():
    # Switch to the backup model from config
    self.model = fallback_model["model"]
    self.base_url = fallback_model["base_url"]
    self.api_key = fallback_model["api_key"]
    # Rebuild the API client
    self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
```

The key idea behind this step:

> Since Hermes Agent supports any provider via `base_url`, failover is simply "swap in a different set of config values." No code changes needed, no message format changes needed.

## Hermes Agent's unique design choices here

### 1. Multi-provider means more error varieties

A single-provider agent only needs to handle one API's error format. Hermes Agent supports OpenRouter, Anthropic, local endpoints, and more -- each with slightly different error formats and status code semantics.

The classifier must extract a unified failure reason from error messages across different providers. For example, "quota exhausted" is worded differently by different providers, but the classification result is always `billing`.

### 2. Connection health check

Before `run_conversation()` starts, the system checks whether the API client's connection is healthy. If it detects a dead connection left over from a previous round (for example, a TCP connection still hanging after a timeout), it proactively cleans it up.

Do not wait until a new API call gets stuck on a zombie connection.

### 3. Primary model recovery

After failing over to a backup model, the next `run_conversation()` call starts by attempting to switch back to the primary model.

This way failover is temporary. If the primary model has recovered, the next round automatically switches back -- no manual intervention needed.

### 4. Thinking-budget detection

Some models (those supporting reasoning/thinking) may spend all output tokens on thinking, leaving zero for the reply. In this case `finish_reason: length` occurs but continuation is pointless.

Hermes Agent detects this situation and reports an error directly, rather than wasting 3 continuation retries.

## Common beginner mistakes

### 1. Treating all errors as the same error

Something that should be continued gets compressed; something that should wait enters an infinite loop; something that should give up retries forever.

### 2. No retry budget

Every recovery path must have a cap. Continuation up to 3 times, backoff up to 3 times. Without a budget, the loop may never terminate.

### 3. Writing a vague continuation prompt

Just writing "continue" is usually not enough. You need to explicitly tell the model not to repeat, not to re-summarize, and to pick up directly from the cutoff point.

### 4. Backoff without random jitter

Deterministic backoff times (for example, always waiting 10 seconds) cause all retries to collide in a multi-session Gateway scenario (thundering herd). Random jitter spreads them out.

### 5. Not attempting to restore the primary model after failover

If you switch to the backup model and never switch back, the user is stuck on a potentially weaker or more expensive backup model.

## How this chapter fits into the main loop

Starting from this chapter, the main loop is no longer a simple "call model -> execute tool." It becomes:

```text
1. Call the model
2. If the call fails -> classify the error -> choose a recovery path
3. If the output was truncated -> continuation
4. If successful -> execute tools normally
5. If any recovery path fails -> report upward
```

In other words, the main loop now maintains three things simultaneously:

```text
Task progression (calling the model, running tools)
Context budget (compression from s05)
Error recovery (classification, retry, failover)
```

This is the last chapter of Phase 1. By this point, you have a single agent that **can work, can persist, can assemble prompts, can compress context, and can recover from errors.**

Phase 2 adds the intelligence layer: memory, skills, security, delegation, and configuration.

## Teaching boundaries

This chapter needs to cover only 4 recovery paths clearly:

1. Output truncated -> continuation
2. Context too long -> compression
3. Transient failure -> backoff retry
4. Unrecoverable -> failover or give up

Deliberately deferred: the specific error format differences of each provider, credential pool rotation, implementation details of connection health checks.

If the reader can get the agent to "not crash on rate limiting, continue when truncated, and automatically switch to a backup when the primary model is down," this chapter has achieved its goal.

## One line to remember

**Classify errors first, then execute recovery, and only expose failure to the user as a last resort. Because Hermes Agent supports multiple providers, the classifier must extract a unified failure reason from error messages in different formats.**
