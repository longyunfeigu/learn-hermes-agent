# s11: Configuration System (配置系统)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > [ s11 ] > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *一个 agent 系统如果只能通过改代码来调整行为，那它就不是一个真正可部署的系统。*

## 这一章要解决什么问题

到了 `s10`，你已经有了一个功能完整的单 agent：对话循环、工具系统、持久化、记忆、技能、权限、子 agent 委派。

但所有这些机制的参数——用哪个模型、调哪个 API 端点、工具集开哪些、上下文压缩阈值多少、子 agent 用什么凭据——全部是写在代码里或者散落在各处的。

这带来三个真实痛点：

**1. 切换模型需要改代码。** 用户从 OpenRouter 切到 Anthropic，或者从 Claude 切到 Gemini，不应该动任何一行 Python。

**2. 秘密信息和结构化配置混在一起。** API key 不应该出现在 YAML 配置文件里。它们需要单独存放、单独加密、不会被意外 commit。

**3. 同一个人需要不同的运行上下文。** 一个开发者可能有一个"写代码"的 agent 和一个"写文章"的 agent，两者的人设、记忆、工具集、甚至模型都不一样。如果配置不隔离，切换场景就只能手动改文件。

这就是配置系统要解决的问题：

**把"agent 怎么运行"从代码里抽出来，变成可声明、可合并、可隔离的外部配置。**

## 先解释几个名词

### 什么是 HERMES_HOME

整个 agent 系统的主目录。默认是 `~/.hermes`。

所有配置、记忆、会话、技能、日志都存在这个目录下。它是一个完全自包含的运行时根目录。

```python
def get_hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
```

通过设置环境变量 `HERMES_HOME`，可以把整个系统指向任何目录。这在 Docker 和 Profile 场景下特别有用。

### 什么是 config.yaml

结构化配置文件。存在 `HERMES_HOME/config.yaml`。YAML 格式。

它描述了 agent 的全部行为参数：用什么模型、开哪些工具集、压缩阈值多少、终端后端是什么、子 agent 用什么配置。

### 什么是 .env

秘密信息文件。存在 `HERMES_HOME/.env`。标准 dotenv 格式。

所有 API key、token、密码都存在这里，不存在 config.yaml 里。文件权限设为 `0600`（只有所有者可读写）。

### 什么是 Profile

一个完全隔离的 HERMES_HOME 目录。每个 Profile 有自己独立的 config.yaml、.env、记忆、会话、技能。

用途：同一个人可以有一个 `coder` profile 和一个 `writer` profile，两者的人设、模型、工具配置完全不同。

```text
~/.hermes/                    ← 默认 profile
~/.hermes/profiles/coder/     ← coder profile
~/.hermes/profiles/writer/    ← writer profile
```

切换 profile 就是把 `HERMES_HOME` 指向不同的目录。

### 什么是配置合并

最终生效的配置不是来自单一来源，而是多个来源按优先级合并的结果：

```text
命令行参数 > 环境变量 > config.yaml > 默认值
```

优先级高的覆盖低的。这意味着你可以在 config.yaml 里设一个常用配置，然后通过命令行参数临时覆盖某个值。

## 最小心智模型

```text
代码里的 DEFAULT_CONFIG（默认值）
  |
  | 1. 读 config.yaml，深度合并
  v
合并后的 config 字典
  |
  | 2. 读 .env，加载到环境变量
  v
环境变量补充秘密信息
  |
  | 3. 命令行参数覆盖
  v
最终的运行时配置
  |
  | 4. 展开 ${VAR} 引用
  v
传给 AIAgent.__init__()
```

关键点只有一个：

**代码里有一份完整的默认配置。用户只需要覆盖自己关心的字段。没覆盖的字段自动用默认值。**

## 关键数据结构

### 1. 默认配置（DEFAULT_CONFIG）

这是写在代码里的完整默认字典。它定义了系统所有可配置项的默认值：

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

这个字典有两个作用：

1. **提供默认值** — 用户没配的字段自动有值
2. **定义 schema** — 所有合法的配置项都在这里有位置

注意 `_config_version`。这是配置迁移系统用的版本号，后面会讲。

### 2. 用户的 config.yaml

用户只需要写自己关心的部分：

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

用户没有写 `terminal`、`display`、`memory` 等节——它们会自动用 DEFAULT_CONFIG 里的默认值。

### 3. .env 文件

```bash
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
TELEGRAM_BOT_TOKEN=123456:ABC-DEF
TELEGRAM_ALLOWED_USERS=user1,user2
```

纯粹的 key-value，没有嵌套结构。

### 4. 辅助模型配置（auxiliary）

Hermes Agent 不只有一个"主模型"。很多辅助任务——视觉分析、网页提取、上下文压缩、会话搜索、审批判断——可以用更便宜、更快的模型：

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

每个辅助任务可以独立配置 provider、model、base_url、api_key 和 timeout。如果不配，默认走 `"auto"` 模式，系统自动选择最佳可用 provider。

### 5. 委派配置（delegation）

`s10` 提到子 agent 可以用不同的模型和凭据。配置就在这里：

```yaml
delegation:
  model: google/gemini-2.5-flash     # 子 agent 用更便宜的模型
  provider: openrouter                # 子 agent 用不同的 provider
  max_iterations: 50                  # 每个子 agent 独立的迭代上限
  reasoning_effort: medium            # 子 agent 的推理强度
```

如果 `model` 和 `provider` 留空，子 agent 继承父 agent 的模型和凭据。

## 最小实现

### 第一步：定义默认配置和路径

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

### 第二步：深度合并

这是配置系统最核心的函数。用户只覆盖了 `compression.threshold`，其他字段不能丢失：

```python
def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并。override 覆盖 base，但只覆盖它声明了的字段。"""
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

为什么不用简单的 `base.update(override)`？因为 `update` 会把整个子字典覆盖掉：

```python
# 错误：用 update
base = {"compression": {"enabled": True, "threshold": 0.50}}
override = {"compression": {"threshold": 0.65}}
base.update(override)
# base["compression"] = {"threshold": 0.65}  ← enabled 丢了！

# 正确：用 _deep_merge
result = _deep_merge(base, override)
# result["compression"] = {"enabled": True, "threshold": 0.65}  ← 都在
```

### 第三步：加载配置

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

`copy.deepcopy` 很重要——不能直接修改 DEFAULT_CONFIG，否则同一进程内多次 load 会互相污染。

### 第四步：加载 .env

```python
from dotenv import load_dotenv

def load_env():
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
```

`override=True` 意味着 .env 文件的值会覆盖 shell 里已有的环境变量。这是故意的——用户在 `~/.hermes/.env` 里写的值就是当前生效的值。

### 第五步：展开环境变量引用

config.yaml 里可以用 `${VAR}` 引用环境变量：

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

未解析的引用（环境变量不存在）保持原样 `${VAR}`，不会变成空字符串。这让调用方可以检测到"这个值没配好"。

### 第六步：保存配置

```python
def save_config(config: dict):
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    os.chmod(config_path, 0o600)  # 只有所有者可读写
```

这就是最小版本。六步：定义默认值 → 深度合并 → 加载 YAML → 加载 .env → 展开引用 → 保存。

## Hermes Agent 在这里的独特设计

### 1. 两文件分离：config.yaml 和 .env

大多数系统要么全用 YAML，要么全用 .env。Hermes Agent 刻意分成两个文件：

- **config.yaml** — 结构化行为配置（模型、工具集、阈值、终端后端）
- **.env** — 秘密信息（API key、token、密码）

为什么分开？

1. **安全**：.env 文件权限设为 `0600`，不会被其他用户读取。config.yaml 不含秘密，被意外暴露也不会泄露凭据。
2. **版本控制友好**：config.yaml 可以安全地纳入版本控制（不含秘密），.env 放在 .gitignore 里。
3. **团队共享**：团队可以共享 config.yaml（模型选择、工具集配置），每人各自的 .env（各自的 API key）。

### 2. Profile 隔离

Profile 不是"换一套配置文件"。它是"换一个完整的 HERMES_HOME"：

```text
~/.hermes/profiles/coder/
├── config.yaml       ← 独立配置
├── .env              ← 独立凭据
├── SOUL.md           ← 独立人设
├── memories/
│   ├── MEMORY.md     ← 独立记忆
│   └── USER.md       ← 独立用户画像
├── sessions/         ← 独立会话历史
├── skills/           ← 独立技能
├── logs/             ← 独立日志
├── cron/             ← 独立定时任务
├── home/             ← 独立子进程 HOME（隔离 git/ssh/npm 配置）
└── workspace/        ← 独立工作目录
```

创建 profile：

```bash
hermes profile create coder          # 空白 profile
hermes profile create coder --clone  # 复制 config.yaml、.env、SOUL.md、MEMORY.md
```

使用 profile：

```bash
hermes -p coder chat                 # 通过 -p 标志
hermes profile use coder             # 设为默认
```

Profile 的本质是把 `HERMES_HOME` 环境变量指向 `~/.hermes/profiles/coder/`，然后所有代码——`get_hermes_home()`、`get_config_path()`、`get_env_path()`——全部自动指向新目录。

不需要任何条件分支。目录换了，整个世界就换了。

### 3. 配置版本迁移

Hermes Agent 的配置 schema 会随版本演进。新版本可能增加新字段、重命名旧字段、移动字段位置。

迁移系统靠 `_config_version` 字段追踪：

```python
# 每个版本引入了哪些新的环境变量
ENV_VARS_BY_VERSION = {
    3: ["FIRECRAWL_API_KEY", "BROWSERBASE_API_KEY"],
    4: ["VOICE_TOOLS_OPENAI_KEY", "ELEVENLABS_API_KEY"],
    5: ["WHATSAPP_ENABLED", "SLACK_BOT_TOKEN"],
    10: ["TAVILY_API_KEY"],
}
```

加载配置时，如果文件里的 `_config_version` 低于代码里的当前版本，系统会：

1. 提示用户有新的可选环境变量
2. 自动迁移字段位置（比如 `max_turns` 从根级移到 `agent.max_turns`）
3. 更新 `_config_version` 到当前版本

```python
def _normalize_max_turns_config(config: dict) -> dict:
    """把旧的根级 max_turns 迁移到 agent.max_turns。"""
    config = dict(config)
    agent_config = dict(config.get("agent") or {})

    if "max_turns" in config and "max_turns" not in agent_config:
        agent_config["max_turns"] = config["max_turns"]

    config["agent"] = agent_config
    config.pop("max_turns", None)
    return config
```

迁移的设计原则是**无损**：旧配置加载后一定能正常工作，只是某些字段会被自动移到新位置。

### 4. HERMES_HOME 目录安全

目录和文件创建时自动设置权限：

```python
def _secure_dir(path):
    os.chmod(path, 0o700)  # 只有所有者可访问

def _secure_file(path):
    os.chmod(path, 0o600)  # 只有所有者可读写
```

在 NixOS 托管模式下，权限由系统激活脚本管理（`0750`——同组用户可读），代码不主动设置。

### 5. 故障转移模型配置

`s06` 讲了错误恢复。配置系统为故障转移提供声明式支持：

```yaml
# 主模型
model: anthropic/claude-sonnet-4

# 备用模型：主模型不可用时自动切换
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

触发条件：限速（429）、过载（529）、服务错误（503）、连接失败。

这让 `s06` 的故障转移逻辑不需要硬编码任何模型信息——它只需要读配置。

## 它如何接到主循环里

配置不在核心循环的代码里，而是在循环启动之前完成加载，然后作为参数传进去。

```text
启动入口（CLI 或 Gateway）
  |
  | 1. load_config()  → 读 config.yaml + 合并默认值
  | 2. load_env()     → 读 .env 到环境变量
  v
构建 AIAgent 参数
  |
  | config["model"]           → model
  | config["agent"]["max_turns"]  → max_iterations
  | config["terminal"]        → environment 配置
  | os.getenv("OPENROUTER_API_KEY") → api_key
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
核心循环运行（不知道配置来自哪里）
```

核心循环不直接读 config.yaml。它只接收参数。配置的解析和合并全部在入口层完成。

这意味着：
- 核心循环可以被任何入口复用（CLI、Gateway、测试）
- 配置来源可以随时替换（从 YAML 换成数据库也不影响循环代码）

## 初学者最容易犯的错

### 1. 把 API key 写在 config.yaml 里

API key 应该在 .env 里，不在 config.yaml 里。config.yaml 可能会被 git commit、被分享、被日志打印。.env 文件有 `0600` 权限保护，且默认在 .gitignore 里。

如果 config.yaml 里确实需要引用凭据（比如委派配置的 api_key），用 `${VAR}` 引用：

```yaml
delegation:
  api_key: "${DELEGATION_API_KEY}"
```

实际的 key 放在 .env 里。

### 2. 直接修改 DEFAULT_CONFIG

`load_config()` 必须 `copy.deepcopy(DEFAULT_CONFIG)` 再合并。如果直接修改 DEFAULT_CONFIG，同一个进程里第二次调用 `load_config()` 会读到被污染的默认值。

### 3. 用 dict.update() 代替深度合并

`update()` 会丢失嵌套字段。用户只配了 `compression.threshold`，结果 `compression.enabled` 消失了。必须用递归的 `_deep_merge`。

### 4. Profile 之间共享 .env

每个 Profile 应该有自己的 .env。如果多个 profile 共用同一个 .env，切换 profile 时可能使用错误的 API key，甚至把高权限 key 暴露给低权限场景。

`--clone` 参数在创建 profile 时会复制 .env，之后两份独立。

### 5. 忘记处理配置迁移

如果你的系统有版本演进，旧用户的 config.yaml 可能缺少新字段。`_deep_merge` 会用默认值补齐缺失字段，但字段**改名**或**移动位置**需要显式的迁移函数。

## 教学边界

这一章讲透四件事：

1. **两文件分离** — config.yaml 放结构化配置，.env 放秘密信息
2. **深度合并** — 用户只覆盖关心的字段，其余自动用默认值
3. **Profile 隔离** — 切换 HERMES_HOME 就切换整个运行上下文
4. **配置版本迁移** — 旧配置文件在新版本下仍然能正常工作

先不管的：

- NixOS 托管模式的具体细节 → 部署话题
- 凭据池轮换策略的实现 → 生产优化
- Setup wizard 的交互流程 → CLI 章节（`s19`）
- 每个平台适配器的配置字段 → Gateway 章节（`s12`、`s13`）

如果读者能做到"配置文件改了值就能改变 agent 行为，增加 Profile 就能隔离运行上下文，旧配置升级后不丢失"，这一章就达标了。

## 学完这章后，你应该能回答

- 为什么把 API key 和结构化配置分成两个文件？
- `_deep_merge` 和 `dict.update()` 的关键区别是什么？
- Profile 的本质是什么？切换 profile 在技术上做了什么？
- 配置的四层优先级是什么？
- 配置系统和核心循环是什么关系？循环知道配置来自 YAML 吗？

---

**一句话记住：Hermes Agent 的配置系统把"行为参数"存在 config.yaml，"秘密信息"存在 .env，两者都在 HERMES_HOME 目录下。通过 `_deep_merge` 让用户只声明差异，通过 Profile 让同一个人运行多套完全隔离的 agent 环境，通过版本号让旧配置在新代码下无损迁移。**
