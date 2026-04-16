# s09: Permission System (权限系统)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > [ s09 ] > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *模型可以提出行动建议，但真正执行之前，必须先过安全关。*

## 这一章的核心目标

到了 `s08`，agent 已经有了工具、持久化、记忆、技能。它真的在做事了。

问题也随之出现：

- 模型可能会执行 `rm -rf /`
- 模型可能会 `DROP TABLE` 你的数据库
- 模型可能会格式化磁盘、杀掉系统进程、往 /etc/ 里写文件

如果每次工具调用都直接执行，一次判断失误就可能造成不可逆的损害。

所以从这一章开始：

**"模型想做什么"不能直接变成"系统真的做了"，中间必须经过安全检查。**

但 Hermes Agent 的权限系统和大多数 agent 框架不一样。它没有通用的 `deny / allow / ask` 三步管道。它专门针对**终端命令**做模式匹配 — 因为在所有工具里，终端是最危险的那个。

![危险命令检测与审批流程](../../illustrations/s09-permission-system/01-flowchart-permission-check.png)

## 先解释几个名词

### 什么是危险命令检测

系统维护一张正则表达式列表。每次执行终端命令前，先拿命令字符串去匹配。命中了就拦下来。

这不是通用的工具权限系统，而是专门针对 shell 命令的安全网。

### 什么是审批

命令被拦下来以后，不是直接拒绝，而是问用户：

- CLI 模式：在终端里弹出确认提示
- Gateway 模式：发送审批按钮给用户

用户可以选择：

- `once` — 这次放行
- `session` — 整个 session 内同类操作都放行
- `always` — 永久放行（写入配置文件）
- `deny` — 拒绝

### 什么是 YOLO 模式

用户可以对当前 session 开启 YOLO 模式（`/yolo`）— 跳过所有危险命令检测，直接执行。

这是给明确知道自己在做什么的用户用的。系统默认关闭。

### 什么是 smart approval

当命令被拦下来时，除了直接问用户，还可以先问一个辅助 LLM："这条命令真的危险吗？"

如果辅助 LLM 判断低风险，可以自动放行，不打扰用户。这减少了频繁弹确认的烦躁感。

## 最小心智模型

```text
terminal 工具收到命令
   |
   v
YOLO 模式开着？ ──是──> 直接执行
   |
   否
   |
   v
命令匹配 DANGEROUS_PATTERNS？
   |
   +── 没命中 ──> 直接执行
   |
   +── 命中了
         |
         v
   session 里之前已经审批过同类？ ──是──> 直接执行
         |
         否
         |
         v
   永久 allowlist 里有？ ──是──> 直接执行
         |
         否
         |
         v
   [CLI] 弹确认提示  /  [Gateway] 发审批按钮
         |
         +── once / session / always ──> 执行，记住审批结果
         +── deny ──> 返回 "Permission denied"
         +── 超时 ──> 返回 "Permission denied"
```

关键点：**这不是通用的工具权限系统。它只管终端命令。** `read_file`、`web_search` 这些工具不经过这个流程。

## 关键数据结构

### 1. 危险模式列表

```python
DANGEROUS_PATTERNS = [
    (r'\brm\s+-[^\s]*r',                    "recursive delete"),
    (r'\bmkfs\b',                            "format filesystem"),
    (r'\bDROP\s+(TABLE|DATABASE)\b',         "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?!.*\bWHERE\b)',   "SQL DELETE without WHERE"),
    (r'\bkill\s+-9\s+-1\b',                  "kill all processes"),
    (r'\b(curl|wget)\b.*\|\s*(ba)?sh\b',     "pipe remote content to shell"),
    (r'\bgit\s+reset\s+--hard\b',            "git reset --hard"),
    # ... 30+ 条
]
```

每条是一个正则表达式 + 一句人类可读描述。

Hermes Agent 有 30 多条模式，覆盖了：文件删除、磁盘操作、SQL 破坏、系统服务、进程管理、fork bomb、远程脚本执行、系统配置覆写、Git 破坏性操作等。

### 2. 审批结果缓存

```python
# 按 session 缓存：同类操作审批一次就够了
_session_approved = {"sess_abc": {"recursive delete", "SQL DROP"}}

# 永久 allowlist：写入 config.yaml
_permanent_approved = {"recursive delete"}
```

### 3. 审批选项

```text
once    → 只放行这一次
session → 整个 session 内同类操作都放行
always  → 永久放行，写入配置文件
deny    → 拒绝执行
```

## 最小实现

### 第一步：定义危险模式

```python
DANGEROUS_PATTERNS = [
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bmkfs\b', "format filesystem"),
]
```

教学版先放几条最常见的就够了。生产系统慢慢补全。

### 第二步：检测函数

```python
def detect_dangerous_command(command):
    command_lower = command.lower()
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower, re.IGNORECASE):
            return (True, description)
    return (False, None)
```

这一步的关键思想是：

> 不需要理解 shell 语法，只需要用正则匹配已知危险模式。覆盖 80% 的高危操作。

### 第三步：审批流程

```python
def approve_command(command, description, session_key):
    # 已经审批过？
    if description in session_approved.get(session_key, set()):
        return True
    if description in permanent_approved:
        return True
    
    # 问用户
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

### 第四步：接进终端工具

```python
def run_terminal(command, session_key):
    is_dangerous, description = detect_dangerous_command(command)
    
    if is_dangerous and not yolo_enabled(session_key):
        if not approve_command(command, description, session_key):
            return "Permission denied: " + description
    
    return execute(command)
```

注意：这段逻辑只在终端工具里，不在核心循环里。其他工具不走这个流程。

## Hermes Agent 在这里的独特设计

### 1. 只管终端命令，不是通用权限

大多数 agent 框架的权限系统是通用的 — 每个工具调用都过权限检查。Hermes Agent 不这样。它只对终端命令做危险模式匹配。

为什么？因为 `read_file` 读一个文件不会造成不可逆损害，但 `rm -rf /` 会。把所有工具都拦下来会让系统变得很烦，把真正危险的拦下来才有意义。

### 2. Unicode 和 ANSI 反绕过

攻击者（或意外的输入）可能用 Unicode 全角字符或 ANSI 转义序列绕过正则匹配。Hermes Agent 在匹配前先做规范化：去掉 ANSI 序列，把全角字符转成半角。

### 3. CLI 和 Gateway 两种审批 UI

CLI 模式下是终端里的 `[o]nce / [s]ession / [a]lways / [d]eny` 提示。  
Gateway 模式下是发送平台的按钮（Telegram 内联键盘、Slack 按钮等）。

两种 UI 复用同一套审批逻辑，只是展示层不同。

### 4. Smart approval（辅助 LLM 判断）

被拦下来的命令可以先发给辅助 LLM 评估风险。如果判断低风险，自动放行。

这减少了"每次 `pip install` 都要手动确认"的烦躁感，同时保持对真正危险命令的拦截。

### 5. 审批超时

如果用户在一定时间内没有响应审批请求，默认拒绝。不让 agent 无限等。

## 它如何接到主循环里

这一章的审批逻辑**不在核心循环里**，而是在终端工具的 handler 里。

也就是说，核心循环没有任何变化。变的是终端工具在执行命令前多了一道检查：

```text
核心循环 → dispatch("run_terminal", args) → 终端工具 handler
                                               |
                                               v
                                           检测危险模式
                                               |
                                               +── 安全 → 直接执行
                                               +── 危险 → 审批 → 执行或拒绝
```

这也是为什么这章在 `s09` 而不是 `s02`：它不改工具系统的架构，只是在一个特定工具里加了安全检查。

## 初学者最容易犯的错

### 1. 想做通用权限系统

不需要每个工具都过权限检查。先把最危险的（终端命令）管住就够了。

### 2. 只检测 `rm`

危险命令远不只 `rm`。SQL DROP、格式化磁盘、kill -9 -1、curl | sh、fork bomb 都要拦。

### 3. 不做 session 级缓存

每次执行 `pip install` 都弹确认，用户很快就会关掉整个审批系统。同类操作 session 内只问一次。

### 4. 不处理 Unicode 绕过

用全角字符 `ｒｍ` 绕过 `rm` 的匹配。需要先规范化再匹配。

### 5. 把审批逻辑放在核心循环里

审批逻辑应该在工具 handler 里，不在循环里。循环不需要知道哪些命令危险。

## 教学边界

这章先讲透一条线就够了：

1. **模式匹配** — 用正则检测已知危险命令
2. **审批流程** — 命中后问用户，结果可缓存
3. **只管终端** — 不是通用权限系统

刻意停住的：smart approval 的完整实现、tirith 安全策略引擎、企业级策略源、Gateway 平台审批按钮的具体实现。

如果读者能做到"agent 要执行 `rm -rf` 时弹出确认，用户同意后才执行"，这一章就达标了。

## 学完这章后，你应该能回答

- 为什么 Hermes Agent 的权限只管终端命令？
- 危险命令检测的核心机制是什么？
- 审批结果的四个选项分别是什么？
- session 级缓存解决什么问题？
- 为什么审批逻辑在工具 handler 里而不在核心循环里？

---

**一句话记住：Hermes Agent 的权限系统不是通用的 allow/deny 管道，而是专门针对终端命令的危险模式匹配 + 审批流程。因为在所有工具里，终端是唯一能造成不可逆损害的那个。**
