# s11: Configuration System

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > [ s11 ] > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24 > s25 > s26 > s27`

> *If the only way to adjust an agent system's behavior is by changing code, it's not a truly deployable system.*

## What problem does this chapter solve

By `s10`, you already have a fully functional single agent: conversation loop, tool system, persistence, memory, skills, permissions, and subagent delegation.

But all the parameters governing these mechanisms -- which model to use, which API endpoint to call, which toolsets to enable, what the compression threshold is, what credentials the subagent uses -- are either hardcoded or scattered across the codebase.

This creates three real pain points:

**1. Switching models requires code changes.** Going from OpenRouter to Anthropic, or from Claude to Gemini, should not require touching a single line of Python.

**2. Secrets and structured config are mixed together.** API keys should not appear in YAML config files. They need to be stored separately, encrypted separately, and never accidentally committed.

**3. The same person needs different runtime contexts.** A developer might have one "coding" agent and one "writing" agent, with different personas, memory, toolsets, and even models. Without configuration isolation, switching contexts means manually editing files.

This is the problem the configuration system solves:

**Extract "how the agent runs" from the code into external configuration that is declarative, mergeable, and isolatable.**

![Configuration Sources and Priority](../../illustrations/en/s11-configuration-system/01-framework-config-sources.png)

## Key terminology

### What is HERMES_HOME

The root directory for the entire agent system. Defaults to `~/.hermes`.

All configuration, memory, sessions, skills, and logs live under this directory. It is a fully self-contained runtime root.

```python
def get_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
```

By setting the `HERMES_HOME` environment variable, you can point the entire system to any directory. This is especially useful in Docker and Profile scenarios.

### What is config.yaml

The structured configuration file. Located at `HERMES_HOME/config.yaml`. YAML format.

It describes all behavioral parameters of the agent: which model to use, which toolsets to enable, compression thresholds, terminal backend, subagent configuration, and more.

### What is .env

The secrets file. Located at `HERMES_HOME/.env`. Standard dotenv format.

All API keys, tokens, and passwords go here -- never in config.yaml. File permissions are set to `0600` (owner read/write only).

### What is a Profile

A fully isolated HERMES_HOME directory. Each Profile has its own independent config.yaml, .env, memory, sessions, and skills.

Use case: the same person can have a `coder` profile and a `writer` profile, with completely different personas, models, and tool configurations.

```text
~/.hermes/                    <-- default profile
~/.hermes/profiles/coder/     <-- coder profile
~/.hermes/profiles/writer/    <-- writer profile
```

Switching profiles simply means pointing `HERMES_HOME` to a different directory.

### What is configuration merging

The final effective configuration doesn't come from a single source. It's the result of merging multiple sources by priority:

```text
CLI arguments > environment variables > config.yaml > defaults
```

Higher priority overrides lower. This means you can set a baseline in config.yaml, then temporarily override a specific value via CLI arguments.

## Minimal mental model

```text
DEFAULT_CONFIG in code (defaults)
  |
  | 1. Read config.yaml, deep merge
  v
Merged config dict
  |
  | 2. Read .env, load into environment variables
  v
Environment variables provide secrets
  |
  | 3. CLI arguments override
  v
Final runtime configuration
  |
  | 4. Expand ${VAR} references
  v
Passed to AIAgent.__init__()
```

There is only one key point:

**The code contains a complete set of defaults. The user only needs to override the fields they care about. Fields not overridden automatically use default values.**

## Key data structures

### 1. Default configuration (DEFAULT_CONFIG)

This is the complete default dictionary defined in code. It establishes the default value for every configurable option:

```python
DEFAULT_CONFIG = {
    "model": "",
    "providers": {},
    "fallback_providers": [],
    "credential_pool_strategies": {},
    "toolsets": ["hermes-cli"],

    "agent": {
        "max_turns": 90,
        "gateway_timeout": 1800,
        "tool_use_enforcement": "auto",
    },

    "terminal": {
        "backend": "local",
        "timeout": 180,
        "docker_image": "nikolaik/python-nodejs:python3.11-nodejs20",
        "persistent_shell": True,
    },

    "compression": {
        "enabled": True,
        "threshold": 0.50,
        "target_ratio": 0.20,
        "protect_last_n": 20,
    },

    "delegation": {
        "model": "",
        "provider": "",
        "base_url": "",
        "api_key": "",
        "max_iterations": 50,
        "reasoning_effort": "",
    },

    "memory": {
        "memory_enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 2200,
        "user_char_limit": 1375,
    },

    "display": {
        "compact": False,
        "personality": "kawaii",
        "streaming": False,
        "show_cost": False,
    },

    "approvals": {
        "mode": "manual",
        "timeout": 60,
    },

    "command_allowlist": [],

    "tts": {
        "provider": "edge",
    },

    "auxiliary": {
        "vision":         {"provider": "auto", "model": ""},
        "web_extract":    {"provider": "auto", "model": ""},
        "compression":    {"provider": "auto", "model": ""},
        "session_search": {"provider": "auto", "model": ""},
        "approval":       {"provider": "auto", "model": ""},
    },

    "_config_version": 17,
}
```

This dictionary serves two purposes:

1. **Provides defaults** -- Fields not configured by the user automatically have values
2. **Defines the schema** -- Every valid configuration field has a place here

Note `_config_version`. This is the version number used by the configuration migration system, explained later.

### 2. User's config.yaml

Users only need to write the parts they care about:

```yaml
model: anthropic/claude-sonnet-4
toolsets:
  - hermes-cli
  - web
  - code-execution

agent:
  max_turns: 150

compression:
  threshold: 0.65

delegation:
  model: google/gemini-2.5-flash
  provider: openrouter
```

The user didn't write `terminal`, `display`, `memory`, etc. -- those automatically use the defaults from DEFAULT_CONFIG.

### 3. .env file

```bash
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_ALLOWED_USERS=user1,user2
```

Pure key-value pairs, no nesting.

### 4. Auxiliary model configuration (auxiliary)

Hermes Agent doesn't rely on just one "main model." Many auxiliary tasks -- vision analysis, web extraction, context compression, session search, approval decisions -- can use cheaper, faster models:

```yaml
auxiliary:
  vision:
    provider: openrouter
    model: google/gemini-2.5-flash
  compression:
    provider: openrouter
    model: google/gemini-2.5-flash
  approval:
    provider: openrouter
    model: google/gemini-2.5-flash
```

Each auxiliary task can independently configure provider, model, base_url, api_key, and timeout. If left unconfigured, the default `"auto"` mode lets the system automatically select the best available provider.

### 5. Delegation configuration (delegation)

`s10` mentioned that subagents can use different models and credentials. The configuration lives here:

```yaml
delegation:
  model: google/gemini-2.5-flash     # Subagent uses a cheaper model
  provider: openrouter                # Subagent uses a different provider
  max_iterations: 50                  # Independent iteration limit per subagent
  reasoning_effort: medium            # Subagent reasoning intensity
```

If `model` and `provider` are left empty, the subagent inherits the parent agent's model and credentials.

## Minimal implementation

### Step 1: Define defaults and paths

```python
import os
import yaml
from pathlib import Path

def get_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))

def get_config_path() -> Path:
    return get_hermes_home() / "config.yaml"

def get_env_path() -> Path:
    return get_hermes_home() / ".env"

DEFAULT_CONFIG = {
    "model": "",
    "toolsets": ["hermes-cli"],
    "agent": {"max_turns": 90},
    "terminal": {"backend": "local", "timeout": 180},
    "compression": {"enabled": True, "threshold": 0.50},
    "delegation": {"model": "", "provider": ""},
}
```

### Step 2: Deep merge

This is the most critical function in the configuration system. If the user only overrode `compression.threshold`, the other fields must not be lost:

```python
def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge. override replaces base, but only for fields it declares."""
    result = base.copy()
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

Why not just use `base.update(override)`? Because `update` replaces entire sub-dictionaries:

```python
# Wrong: using update
base = {"compression": {"enabled": True, "threshold": 0.50}}
override = {"compression": {"threshold": 0.65}}
base.update(override)
# base["compression"] = {"threshold": 0.65}  <-- enabled is gone!

# Correct: using _deep_merge
result = _deep_merge(base, override)
# result["compression"] = {"enabled": True, "threshold": 0.65}  <-- both preserved
```

### Step 3: Load configuration

```python
import copy

def load_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
    
    return config
```

`copy.deepcopy` is critical -- you must not modify DEFAULT_CONFIG directly, or multiple `load_config()` calls within the same process will contaminate each other.

### Step 4: Load .env

```python
from dotenv import load_dotenv

def load_env():
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
```

`override=True` means values in the .env file will override existing shell environment variables. This is intentional -- values the user writes in `~/.hermes/.env` are the values that take effect.

### Step 5: Expand environment variable references

config.yaml can reference environment variables with `${VAR}`:

```yaml
delegation:
  api_key: "${OPENROUTER_API_KEY}"
```

```python
import re

def _expand_env_vars(obj):
    if isinstance(obj, str):
        return re.sub(
            r"\${([^}]+)}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj
```

Unresolved references (when the environment variable doesn't exist) remain as `${VAR}` rather than becoming empty strings. This lets callers detect "this value isn't properly configured."

### Step 6: Save configuration

```python
def save_config(config: dict):
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    os.chmod(config_path, 0o600)  # Owner read/write only
```

That's the minimal version. Six steps: define defaults -> deep merge -> load YAML -> load .env -> expand references -> save.

## Hermes Agent's unique design choices

### 1. Two-file separation: config.yaml and .env

Most systems use either all YAML or all .env. Hermes Agent deliberately splits them into two files:

- **config.yaml** -- Structured behavioral configuration (models, toolsets, thresholds, terminal backend)
- **.env** -- Secrets (API keys, tokens, passwords)

Why separate them?

1. **Security**: The .env file permissions are set to `0600`, unreadable by other users. config.yaml contains no secrets, so accidental exposure won't leak credentials.
2. **Version control friendly**: config.yaml can safely be checked into version control (no secrets); .env goes in .gitignore.
3. **Team sharing**: A team can share config.yaml (model choices, toolset configurations) while each member maintains their own .env (their own API keys).

### 2. Profile isolation

A Profile isn't just "swapping config files." It's "swapping the entire HERMES_HOME":

```text
~/.hermes/profiles/coder/
+-- config.yaml       <-- independent configuration
+-- .env              <-- independent credentials
+-- SOUL.md           <-- independent persona
+-- memories/
|   +-- MEMORY.md     <-- independent memory
|   +-- USER.md       <-- independent user profile
+-- sessions/         <-- independent session history
+-- skills/           <-- independent skills
+-- logs/             <-- independent logs
+-- cron/             <-- independent scheduled tasks
+-- home/             <-- independent subprocess HOME (isolates git/ssh/npm config)
+-- workspace/        <-- independent working directory
```

Creating a profile:

```bash
hermes profile create coder          # Blank profile
hermes profile create coder --clone  # Copies config.yaml, .env, SOUL.md, MEMORY.md
```

Using a profile:

```bash
hermes -p coder chat                 # Via the -p flag
hermes profile use coder             # Set as default
```

The essence of a Profile is pointing the `HERMES_HOME` environment variable to `~/.hermes/profiles/coder/`. Then all code -- `get_hermes_home()`, `get_config_path()`, `get_env_path()` -- automatically points to the new directory.

No conditional branches needed. When the directory changes, the entire world changes.

### 3. Configuration version migration

Hermes Agent's configuration schema evolves over time. New versions may add fields, rename old fields, or move fields to different locations.

The migration system tracks versions via the `_config_version` field:

```python
# Which new environment variables each version introduced
ENV_VARS_BY_VERSION = {
    3: ["FIRECRAWL_API_KEY", "BROWSERBASE_API_KEY"],
    4: ["VOICE_TOOLS_OPENAI_KEY", "ELEVENLABS_API_KEY"],
    5: ["WHATSAPP_ENABLED", "SLACK_BOT_TOKEN"],
    10: ["TAVILY_API_KEY"],
}
```

When loading configuration, if the file's `_config_version` is lower than the current version in code, the system will:

1. Inform the user about new optional environment variables
2. Automatically migrate field locations (e.g., `max_turns` moved from root level to `agent.max_turns`)
3. Update `_config_version` to the current version

```python
def _normalize_max_turns_config(config: dict) -> dict:
    """Migrate the old root-level max_turns to agent.max_turns."""
    config = dict(config)
    agent_config = dict(config.get("agent") or {})

    if "max_turns" in config and "max_turns" not in agent_config:
        agent_config["max_turns"] = config["max_turns"]

    config["agent"] = agent_config
    config.pop("max_turns", None)
    return config
```

The migration design principle is **lossless**: old configuration files always work correctly after loading; some fields are simply auto-moved to their new locations.

### 4. HERMES_HOME directory security

Permissions are automatically set when creating directories and files:

```python
def _secure_dir(path):
    os.chmod(path, 0o700)  # Owner access only

def _secure_file(path):
    os.chmod(path, 0o600)  # Owner read/write only
```

In NixOS managed mode, permissions are handled by the system activation script (`0750` -- group members can read), and the code does not set them proactively.

### 5. Fallback model configuration

`s06` covered error recovery. The configuration system provides declarative support for failover:

```yaml
# Primary model
model: anthropic/claude-sonnet-4

# Fallback model: auto-switch when the primary is unavailable
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

Trigger conditions: rate limiting (429), overload (529), service error (503), connection failure.

This means the failover logic from `s06` doesn't need to hardcode any model information -- it just reads the configuration.

## How it connects to the main loop

Configuration is not in the core loop's code. It's loaded before the loop starts and passed in as parameters.

```text
Entry point (CLI or Gateway)
  |
  | 1. load_config()  -> read config.yaml + merge with defaults
  | 2. load_env()     -> read .env into environment variables
  v
Build AIAgent parameters
  |
  | config["model"]                -> model
  | config["agent"]["max_turns"]   -> max_iterations
  | config["terminal"]             -> environment configuration
  | os.getenv("OPENROUTER_API_KEY") -> api_key
  v
AIAgent(
    model=model,
    api_key=api_key,
    base_url=base_url,
    max_iterations=max_iterations,
    enabled_toolsets=toolsets,
    ...
)
  |
  v
Core loop runs (doesn't know where configuration came from)
```

The core loop does not read config.yaml directly. It only receives parameters. All configuration parsing and merging is done at the entry layer.

This means:
- The core loop can be reused by any entry point (CLI, Gateway, tests)
- The configuration source can be swapped at any time (switching from YAML to a database doesn't affect loop code)

## Most common beginner mistakes

### 1. Putting API keys in config.yaml

API keys belong in .env, not config.yaml. config.yaml might get git committed, shared, or printed in logs. The .env file has `0600` permission protection and is in .gitignore by default.

If config.yaml genuinely needs to reference credentials (e.g., the delegation config's api_key), use `${VAR}` references:

```yaml
delegation:
  api_key: "${DELEGATION_API_KEY}"
```

The actual key goes in .env.

### 2. Mutating DEFAULT_CONFIG directly

`load_config()` must `copy.deepcopy(DEFAULT_CONFIG)` before merging. If you mutate DEFAULT_CONFIG directly, a second call to `load_config()` within the same process will read contaminated defaults.

### 3. Using dict.update() instead of deep merge

`update()` loses nested fields. The user only configured `compression.threshold`, but `compression.enabled` disappears. You must use the recursive `_deep_merge`.

### 4. Sharing .env between Profiles

Each Profile should have its own .env. If multiple profiles share the same .env, switching profiles might use the wrong API key, or even expose a high-privilege key to a low-privilege context.

The `--clone` flag copies .env when creating a profile; after that, the two copies are independent.

### 5. Forgetting to handle configuration migration

If your system evolves over time, existing users' config.yaml files may lack new fields. `_deep_merge` fills in missing fields with defaults, but field **renames** or **relocations** require explicit migration functions.

## Scope of this chapter

This chapter thoroughly covers four things:

1. **Two-file separation** -- config.yaml holds structured config, .env holds secrets
2. **Deep merge** -- Users override only what they care about; everything else uses defaults
3. **Profile isolation** -- Switching HERMES_HOME switches the entire runtime context
4. **Configuration version migration** -- Old config files still work correctly under new versions

Deferred topics:

- NixOS managed mode specifics -> deployment topic
- Credential pool rotation strategies -> production optimization
- Setup wizard interaction flow -> CLI chapter (`s19`)
- Platform adapter configuration fields -> Gateway chapters (`s12`, `s13`)

If the reader can achieve "changing a config file value changes agent behavior, adding a Profile isolates the runtime context, and old configs survive upgrades without data loss," this chapter has served its purpose.

## After this chapter, you should be able to answer

- Why split API keys and structured configuration into two files?
- What is the critical difference between `_deep_merge` and `dict.update()`?
- What is the essence of a Profile? What happens technically when you switch profiles?
- What are the four priority levels of configuration?
- What is the relationship between the configuration system and the core loop? Does the loop know its config came from YAML?

---

**In one sentence: Hermes Agent's configuration system stores "behavioral parameters" in config.yaml and "secrets" in .env, both under the HERMES_HOME directory. It uses `_deep_merge` so users only declare differences, Profiles to run multiple fully isolated agent environments for the same person, and version numbers to losslessly migrate old configs under new code.**
