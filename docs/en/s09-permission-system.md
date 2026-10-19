# s09: Permission System

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > [ s09 ] > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *The model may propose an action, but before it is actually executed, it must pass a safety gate.*

## Core goal of this chapter

By `s08`, the agent has tools, persistence, memory, and skills. It is genuinely doing real work.

The problems that come with it:

- The model might execute `rm -rf /`
- The model might `DROP TABLE` your database
- The model might format a disk, kill system processes, or write to /etc/

If every tool call is executed directly, a single misjudgment can cause irreversible damage.

So starting from this chapter:

**"What the model wants to do" must not directly become "what the system actually did" -- a safety check must stand between the two.**

But the Hermes Agent permission system is unlike most agent frameworks. It does not have a generic `deny / allow / ask` pipeline. Instead, it performs pattern matching specifically on **terminal commands** -- because among all tools, the terminal is the most dangerous one.

![Dangerous Command Detection](../../illustrations/en/s09-permission-system/01-flowchart-permission-check.png)

## Key terms explained

### What is dangerous command detection

The system maintains a list of regular expressions. Before every terminal command is executed, the command string is matched against this list. A match triggers interception.

This is not a generic tool permission system but a safety net specifically for shell commands.

### What is approval

After a command is intercepted, it is not rejected outright. Instead, the user is asked:

- CLI mode: A confirmation prompt appears in the terminal
- Gateway mode: Approval buttons are sent to the user

The user can choose:

- `once` -- Allow this one time
- `session` -- Allow this type of operation for the entire session
- `always` -- Allow permanently (written to the config file)
- `deny` -- Reject

### What is YOLO mode

The user can enable YOLO mode for the current session (`/yolo`) -- this skips all dangerous command detection and executes commands directly.

This is intended for users who know exactly what they are doing. It is off by default.

### What is smart approval

When a command is intercepted, instead of immediately prompting the user, the system can first ask an auxiliary LLM: "Is this command actually dangerous?"

If the auxiliary LLM judges the risk as low, the command can be auto-approved without disturbing the user. This reduces the annoyance of frequent confirmation prompts.

## Minimal mental model

```text
Terminal tool receives a command
   |
   v
YOLO mode enabled? --yes--> Execute directly
   |
   no
   |
   v
Does the command match DANGEROUS_PATTERNS?
   |
   +-- No match --> Execute directly
   |
   +-- Match found
         |
         v
   Already approved for this type in this session? --yes--> Execute directly
         |
         no
         |
         v
   In the permanent allowlist? --yes--> Execute directly
         |
         no
         |
         v
   [CLI] Show confirmation prompt  /  [Gateway] Send approval buttons
         |
         +-- once / session / always --> Execute, remember the approval
         +-- deny --> Return "Permission denied"
         +-- timeout --> Return "Permission denied"
```

Key point: **This is not a generic tool permission system. It only governs terminal commands.** `read_file`, `web_search`, and other tools do not go through this flow.

## Key data structures

### 1. Dangerous pattern list

```python
DANGEROUS_PATTERNS = [
    (r'\brm\s+-[^\s]*r',                    "recursive delete"),
    (r'\bmkfs\b',                            "format filesystem"),
    (r'\bDROP\s+(TABLE|DATABASE)\b',         "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?!.*\bWHERE\b)',   "SQL DELETE without WHERE"),
    (r'\bkill\s+-9\s+-1\b',                  "kill all processes"),
    (r'\b(curl|wget)\b.*\|\s*(ba)?sh\b',     "pipe remote content to shell"),
    (r'\bgit\s+reset\s+--hard\b',            "git reset --hard"),
    # ... 30+ patterns
]
```

Each entry is a regular expression paired with a human-readable description.

Hermes Agent has over 30 patterns covering: file deletion, disk operations, destructive SQL, system services, process management, fork bombs, remote script execution, system config overwrites, destructive Git operations, and more.

### 2. Approval result cache

```python
# Per-session cache: same type of operation only needs approval once
_session_approved = {"sess_abc": {"recursive delete", "SQL DROP"}}

# Permanent allowlist: written to config.yaml
_permanent_approved = {"recursive delete"}
```

### 3. Approval options

```text
once    -> Allow this one time only
session -> Allow this type of operation for the entire session
always  -> Allow permanently, written to the config file
deny    -> Reject execution
```

## Minimal implementation

### Step 1: Define dangerous patterns

```python
DANGEROUS_PATTERNS = [
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bmkfs\b', "format filesystem"),
]
```

The teaching version needs just a few of the most common patterns. A production system can be built up over time.

### Step 2: Detection function

```python
def detect_dangerous_command(command):
    command_lower = command.lower()
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower, re.IGNORECASE):
            return (True, description)
    return (False, None)
```

The key idea behind this step:

> No need to understand shell syntax -- just use regex to match known dangerous patterns. This covers 80% of high-risk operations.

### Step 3: Approval flow

```python
def approve_command(command, description, session_key):
    # Already approved?
    if description in session_approved.get(session_key, set()):
        return True
    if description in permanent_approved:
        return True
    
    # Ask the user
    choice = prompt_user(command, description)  # once / session / always / deny
    
    if choice == "once":
        return True
    if choice == "session":
        session_approved.setdefault(session_key, set()).add(description)
        return True
    if choice == "always":
        permanent_approved.add(description)
        save_to_config(permanent_approved)
        return True
    return False
```

### Step 4: Hook into the terminal tool

```python
def run_terminal(command, session_key):
    is_dangerous, description = detect_dangerous_command(command)
    
    if is_dangerous and not yolo_enabled(session_key):
        if not approve_command(command, description, session_key):
            return "Permission denied: " + description
    
    return execute(command)
```

Note: this logic lives inside the terminal tool handler, not in the core loop. Other tools do not go through this flow.

## Hermes Agent's unique design choices here

### 1. Only governs terminal commands, not a generic permission system

Most agent frameworks have a generic permission system -- every tool call goes through a permission check. Hermes Agent does not do this. It only performs dangerous pattern matching on terminal commands.

Why? Because `read_file` reading a file does not cause irreversible damage, but `rm -rf /` does. Intercepting every tool makes the system annoying; intercepting only the truly dangerous ones is what matters.

### 2. Unicode and ANSI bypass prevention

Attackers (or accidental input) may use Unicode fullwidth characters or ANSI escape sequences to bypass regex matching. Hermes Agent normalizes the input before matching: stripping ANSI sequences and converting fullwidth characters to halfwidth.

### 3. Two approval UIs for CLI and Gateway

In CLI mode, it is a terminal prompt: `[o]nce / [s]ession / [a]lways / [d]eny`.  
In Gateway mode, it is platform buttons (Telegram inline keyboards, Slack buttons, etc.).

Both UIs share the same underlying approval logic -- only the presentation layer differs.

### 4. Smart approval (auxiliary LLM judgment)

Intercepted commands can be sent to an auxiliary LLM for risk assessment first. If the risk is judged as low, the command is auto-approved.

This reduces the annoyance of "having to manually confirm every `pip install`" while still intercepting genuinely dangerous commands.

### 5. Approval timeout

If the user does not respond to an approval request within a set time, the default is to deny. The agent is not left waiting indefinitely.

## How it fits into the main loop

This chapter's approval logic **is not in the core loop** -- it lives inside the terminal tool's handler.

In other words, the core loop does not change at all. What changes is that the terminal tool has an extra check before executing a command:

```text
Core loop -> dispatch("run_terminal", args) -> terminal tool handler
                                               |
                                               v
                                           Detect dangerous patterns
                                               |
                                               +-- Safe -> Execute directly
                                               +-- Dangerous -> Approval -> Execute or deny
```

This is also why this chapter is at `s09` rather than `s02`: it does not change the tool system's architecture; it only adds a safety check inside one specific tool.

## Common beginner mistakes

### 1. Trying to build a generic permission system

There is no need to run a permission check on every tool. Start by locking down the most dangerous one (terminal commands) and that is sufficient.

### 2. Only checking for `rm`

Dangerous commands extend far beyond `rm`. SQL DROP, disk formatting, kill -9 -1, curl | sh, fork bombs -- all need to be intercepted.

### 3. Not caching at the session level

If every `pip install` triggers a confirmation prompt, the user will soon disable the entire approval system. Ask once per type of operation per session.

### 4. Not handling Unicode bypass

Fullwidth characters like `rm` can bypass a pattern matching `rm`. Normalize first, then match.

### 5. Putting approval logic in the core loop

Approval logic belongs in the tool handler, not in the loop. The loop does not need to know which commands are dangerous.

## Teaching boundaries

This chapter needs to cover just one clear line:

1. **Pattern matching** -- Use regex to detect known dangerous commands
2. **Approval flow** -- After a match, ask the user; results can be cached
3. **Terminal-only** -- Not a generic permission system

Deliberately deferred: the full smart approval implementation, the tirith security policy engine, enterprise-grade policy sources, specific implementations of Gateway platform approval buttons.

If the reader can get the agent to "pop up a confirmation when about to execute `rm -rf`, and only execute after the user approves," this chapter has achieved its goal.

## After finishing this chapter, you should be able to answer

- Why does the Hermes Agent permission system only govern terminal commands?
- What is the core mechanism of dangerous command detection?
- What are the four approval options?
- What problem does session-level caching solve?
- Why does the approval logic live in the tool handler rather than the core loop?

---

**One line to remember: The Hermes Agent permission system is not a generic allow/deny pipeline. It is dangerous pattern matching plus an approval flow, targeted specifically at terminal commands -- because among all tools, the terminal is the only one that can cause irreversible damage.**
