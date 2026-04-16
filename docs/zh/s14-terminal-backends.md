# s14: Terminal Backends (终端后端抽象)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > [ s14 ] > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *工具调 terminal 执行命令。但命令在哪里跑——本地、Docker、还是 SSH 远程机器——工具不需要知道。*

![终端后端抽象](../../illustrations/s14-terminal-backends/01-framework-backend-abstraction.png)

## 这一章要解决什么问题

s01-s11 里 terminal 工具的实现是四行代码：

```python
def run_terminal(args, **kwargs):
    result = subprocess.run(
        args["command"], shell=True,
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout + result.stderr
```

直接在本机跑。现在产品说："能不能让 agent 在 Docker 容器里跑命令？"

最直接的想法是在工具函数里加 if-else。但你马上会撞到两个问题。

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — terminal 工具是怎么注册和分发的
- [`s00-architecture-overview.md`](./s00-architecture-overview.md) — 执行环境层在五层架构中的位置

## 先解释几个名词

### 什么是 snapshot

agent 执行 `cd /tmp` 再执行 `pwd`，期望输出 `/tmp`。但 `subprocess.run` 每次都启动新 bash，前一个 bash 的目录和变量随着进程结束就丢了。

snapshot 解决这个问题：**每条命令执行完后，把当前的环境变量和工作目录存到一个文件里；下一条命令执行前，先从这个文件恢复。** 这样每条命令虽然在新 bash 里跑，但状态是连续的。

snapshot 由两个文件组成，路径在 BaseEnvironment 创建时生成：

```python
self._session_id = uuid.uuid4().hex[:12]   # 随机 12 位，如 "a1b2c3d4e5f6"
self._snapshot_path = f"/tmp/hermes-snap-{self._session_id}.sh"   # 环境变量
self._cwd_file = f"/tmp/hermes-cwd-{self._session_id}.txt"        # 工作目录
```

同一个 BaseEnvironment 实例的所有命令共用这两个文件。文件内容长这样：

```bash
# /tmp/hermes-snap-a1b2c3.sh
export PATH="/usr/local/bin:/usr/bin:/bin"
export MY_VAR="hello"
```

```text
# /tmp/hermes-cwd-a1b2c3.txt
/workspace/myproject
```

### 什么是 BaseEnvironment

所有终端后端的抽象基类。创建时生成 session_id 和 snapshot 路径，子类只需实现两个方法：

- `_run_bash(cmd_string)` — 怎么启动 bash（subprocess / docker exec / ssh）
- `cleanup()` — 怎么释放资源（删文件 / 停容器 / 断连接）

命令包装、snapshot 恢复/保存、超时处理——全在基类里，所有后端共用。

## 从最笨的实现开始

在 terminal 工具里加 if-else：

```python
if backend == "local":
    result = subprocess.run(command, shell=True, ...)
elif backend == "docker":
    result = subprocess.run(["docker", "exec", container, "bash", "-c", command], ...)
elif backend == "ssh":
    result = subprocess.run(["ssh", f"{user}@{host}", "bash", "-c", command], ...)
```

能跑，但有两个问题。

### 问题一：状态不连续

agent 连续执行三条命令：

```text
命令 1: cd /workspace/myproject
命令 2: export MY_VAR=hello
命令 3: echo $MY_VAR && pwd
```

每条命令启动一个新 bash 进程：

```text
命令 1 → 进程 #1 → cd 成功 → 进程结束，目录丢了
命令 2 → 进程 #2 → export 成功 → 进程结束，变量丢了
命令 3 → 进程 #3 → $MY_VAR 不存在，pwd 输出初始目录
```

你可能会想："维护一个长驻 bash 进程，往 stdin 写命令，状态自然连续了。"

这条路走不通，有三个坑：

- **输出边界。** 你写了 `ls`，怎么知道 `ls` 的输出读完了？没有分隔符。你得在每条命令后偷偷塞一个 `echo __MARKER__`，从 stdout 里找标记，非常脆弱。
- **卡死传染。** agent 执行了 `cat`（没给文件名，死等输入）。你没法单独杀它——要么杀整个 bash（状态全丢），要么干等超时。
- **多行命令。** agent 写了 `for i in 1 2 3; do ... done`。bash 在收到 `done` 之前不会执行。你得理解 bash 语法才知道什么时候该读输出——等于重写 shell parser。

**Hermes Agent 的方案：每条命令仍然启动新 bash，但通过 snapshot 文件传递状态。**

### 问题二：if-else 爆炸

加了 Docker 和 SSH 之后，如果还要加 Modal、Daytona、Singularity，就是六个分支。这和 s12 遇到的问题一样——解法也一样：**抽出公共接口，让每个后端自己实现。**

## 用三条命令走一遍完整流程

看 snapshot 怎么让状态在新 bash 进程之间延续。

每条命令在发给后端之前，基类会把它包装成五行脚本：

```text
source snapshot.sh       ← 恢复上次保存的环境变量
cd {上次的工作目录}       ← 恢复上次的目录
{用户的命令}             ← 真正要执行的
export -p > snapshot.sh  ← 保存新的环境变量
pwd -P > cwd.txt         ← 保存新的工作目录
```

三条命令的完整过程：

```text
=== 命令 1: cd /workspace/myproject ===

包装成：
  source snapshot.sh          ← 首次为空，跳过
  cd /home/user               ← 初始目录
  cd /workspace/myproject     ← 用户的命令
  export -p > snapshot.sh     ← 保存环境
  pwd -P > cwd.txt            ← 保存 /workspace/myproject

→ bash 进程 #1 执行完，退出
→ 基类读 cwd.txt → 记住目录是 /workspace/myproject

=== 命令 2: export MY_VAR=hello ===

包装成：
  source snapshot.sh          ← 恢复命令 1 的环境
  cd /workspace/myproject     ← 恢复命令 1 结束时的目录
  export MY_VAR=hello         ← 用户的命令
  export -p > snapshot.sh     ← 保存（现在多了 MY_VAR=hello）
  pwd -P > cwd.txt

→ bash 进程 #2 执行完，退出

=== 命令 3: echo $MY_VAR && pwd ===

包装成：
  source snapshot.sh          ← 恢复，里面有 MY_VAR=hello
  cd /workspace/myproject     ← 正确的目录
  echo $MY_VAR && pwd         ← 用户的命令

输出：
  hello
  /workspace/myproject         ✓
```

三个不同的 bash 进程，但 agent 看到的是连续的状态。

**核心就是这五行包装脚本。** 每种后端（本地、Docker、SSH）都用同一套包装逻辑，区别只是"这五行在哪里执行"。

## 最小心智模型

```text
terminal 工具
    │
    │  execute("pip install numpy")
    v
BaseEnvironment（基类）
    │
    │  1. 包装：source snap → cd → 用户命令 → export -p → pwd
    │  2. 交给子类：_run_bash(包装后的命令)
    │  3. 等输出，读 cwd.txt 更新目录
    │
    ├── LocalBackend:   subprocess.Popen(["bash", "-c", ...])
    ├── DockerBackend:  subprocess.Popen(["docker", "exec", ..., "bash", "-c", ...])
    └── SSHBackend:     subprocess.Popen(["ssh", ..., "bash", "-c", ...])
```

基类做步骤 1 和 3（所有后端共用），子类只做步骤 2（各不相同）。

## 最小实现

### 命令包装（基类，所有后端共用）

```python
def _wrap_command(self, command: str) -> str:
    parts = []
    if self._snapshot_ready:
        parts.append(f"source {self._snapshot_path} 2>/dev/null")
    parts.append(f"cd {shlex.quote(self.cwd)} 2>/dev/null")
    parts.append(command)
    # 先存退出码，保存完 snapshot 再用它退出
    # 否则 export -p 的退出码（永远是 0）会覆盖用户命令的退出码
    parts.append(f"_exit=$?; export -p > {self._snapshot_path} 2>/dev/null; "
                  f"pwd -P > {self._cwd_file} 2>/dev/null; exit $_exit")
    return "; ".join(parts)
```

### 本地后端

最简单——直接调 subprocess：

```python
class LocalBackend(BaseEnvironment):

    def _run_bash(self, cmd_string, *, timeout):
        # 过滤 API key，防止 agent 执行的命令读到 OPENAI_API_KEY 等密钥
        env = {k: v for k, v in os.environ.items()
               if k not in _SECRET_BLOCKLIST}
        return subprocess.Popen(
            ["bash", "-c", cmd_string],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env,
        )

    def cleanup(self):
        for f in [self._snapshot_path, self._cwd_file]:
            try: os.unlink(f)
            except FileNotFoundError: pass
```

为什么要过滤环境变量？因为本地后端的子进程继承宿主机的全部环境变量。不过滤的话，agent 执行 `env | grep KEY` 就能拿到你的 API key。Docker 和 SSH 后端不需要——容器和远程机器天然没有这些变量。

### Docker 后端

关键区别：先启动一个长驻容器，每条命令用 `docker exec` 送进去。

```python
class DockerBackend(BaseEnvironment):

    def __init__(self, image="python:3.11-slim", **kwargs):
        super().__init__(**kwargs)
        self._image = image
        self._container_id = None

    def _ensure_container(self):
        """第一条命令前启动容器，之后复用。"""
        if self._container_id:
            return
        result = subprocess.run([
            "docker", "run", "-d",
            "--name", f"hermes-{self._session_id}",
            "--cap-drop", "ALL",                    # 删除所有 capabilities
            "--security-opt", "no-new-privileges",  # 禁止提权
            "--pids-limit", "256",                   # 防 fork 炸弹
            "--memory", "512m",                      # 内存上限
            self._image, "sleep", "infinity",        # 容器不退出
        ], capture_output=True, text=True)
        self._container_id = result.stdout.strip()

    def _run_bash(self, cmd_string, *, timeout):
        self._ensure_container()
        return subprocess.Popen(
            ["docker", "exec", "-i", self._container_id,
             "bash", "-c", cmd_string],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def cleanup(self):
        if self._container_id:
            subprocess.run(["docker", "rm", "-f", self._container_id],
                           capture_output=True)
```

为什么用长驻容器而不是每条命令都 `docker run`？因为 snapshot 文件在容器的文件系统里。容器销毁了 snapshot 就丢了，状态就断了。

安全参数解释：

| 参数 | 防什么 |
|------|--------|
| `--cap-drop ALL` | agent 不能 mount 文件系统、不能改网络规则 |
| `--no-new-privileges` | 容器里的 setuid 程序不能提权 |
| `--pids-limit 256` | fork 炸弹只能炸 256 个进程 |
| `--memory 512m` | 吃满内存只影响容器，不影响宿主机 |

### SSH 后端

```python
class SSHBackend(BaseEnvironment):

    def __init__(self, host, user, key_path=None, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._user = user
        self._key_path = key_path
        self._control_socket = f"/tmp/hermes-ssh/{user}@{host}.sock"

    def _ssh_args(self):
        args = [
            "ssh",
            "-o", "ControlMaster=auto",           # 连接复用
            "-o", f"ControlPath={self._control_socket}",
            "-o", "ControlPersist=300",            # 空闲 5 分钟后断开
            "-o", "BatchMode=yes",                 # 不弹交互提示
        ]
        if self._key_path:
            args += ["-i", self._key_path]
        args.append(f"{self._user}@{self._host}")
        return args

    def _run_bash(self, cmd_string, *, timeout):
        return subprocess.Popen(
            self._ssh_args() + ["bash", "-c", shlex.quote(cmd_string)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    def cleanup(self):
        subprocess.run(
            ["ssh", "-O", "exit",
             "-o", f"ControlPath={self._control_socket}",
             f"{self._user}@{self._host}"],
            capture_output=True)
```

`ControlMaster` 是 SSH 的连接复用。第一条命令建立 TCP 连接和认证，后续命令复用同一条连接。不用它的话 30 条命令 = 30 次握手 + 认证。

### 后端选择

config.yaml 里一行配置切后端，工具代码不用改：

```yaml
terminal:
  backend: docker    # "local" | "docker" | "ssh"
  docker_image: python:3.11-slim
```

```python
def create_backend(config):
    backend_type = config.get("terminal", {}).get("backend", "local")
    if backend_type == "docker":
        return DockerBackend(image=..., cwd="/workspace")
    elif backend_type == "ssh":
        return SSHBackend(host=..., user=..., cwd="~")
    else:
        return LocalBackend(cwd=os.getcwd())
```

### 远程后端怎么读 cwd 文件

本地后端的 snapshot 和 cwd 文件在本机 `/tmp`，直接读。Docker 和 SSH 后端的文件在容器/远程机器上，需要多一步：

```text
本地后端：   直接读 /tmp/hermes-cwd-xxx.txt
Docker 后端：docker exec cat /tmp/hermes-cwd-xxx.txt
SSH 后端：   ssh cat /tmp/hermes-cwd-xxx.txt（复用 ControlMaster，几乎没开销）
```

对上层透明——`execute()` 返回后 `self.cwd` 就是最新的。

## 如何接到主循环里

```text
核心循环
  │  tool_call: terminal("pip install numpy")
  v
terminal 工具
  │  → 权限检查（s09）
  │  → backend.execute("pip install numpy")
  v
BaseEnvironment（当前是 DockerBackend）
  │  包装：source snap → cd → pip install numpy → export -p → pwd
  │  执行：docker exec hermes-a1b2c3 bash -c "..."
  v
Docker 容器
  │  输出 + 返回码
  v
terminal 工具
  │  tool_result: "Successfully installed numpy-1.26.4"
  v
核心循环（继续下一轮）
```

核心循环只看到 terminal 工具返回了一段文本。它不知道这条命令在 Docker 里跑。

## 初学者最容易犯的错

### 1. 忘了过滤 API key

本地后端直接把全部环境变量传给子进程，agent 执行 `env | grep KEY` 就能看到密钥。

**修：子进程环境变量过滤密钥列表。Docker 和 SSH 不需要——容器/远程机器天然没有这些变量。**

### 2. Docker 不加资源限制

agent 跑了吃光内存的脚本，宿主机跟着挂。

**修：`--memory`、`--pids-limit` 必须配。**

### 3. SSH 每条命令都建新连接

30 条命令 = 30 次 TCP 连接 + 认证。

**修：ControlMaster 复用连接。**

### 4. 命令包装用 `&&` 串联

`source snap && cd ... && 用户命令 && export -p`——用户命令返回非零时 `export -p` 不执行，snapshot 断了，后面所有命令的环境都丢。

**修：用 `;` 分隔，或者先存退出码再 export（参考实现里的 `_exit=$?` 写法）。**

## 教学边界

这一章只讲 **terminal 工具**的后端抽象。`read_file`、`write_file` 等工具不走这层——它们是 Python 代码直接操作文件系统，不需要 snapshot 机制。

为什么 terminal 需要而 read_file 不需要？因为 terminal 有**跨命令的状态**——agent 的 `cd`、`export` 必须在后续命令中生效。这是 snapshot 解决的核心问题。`read_file` 是无状态的：给路径，返回内容，不需要记住上次读了什么。Docker 下把 `open(path)` 改成 `docker exec cat path` 就够了，一行改动。

讲三件事：

1. **为什么需要后端抽象** — 从 if-else 的痛苦推出
2. **snapshot 怎么让状态跨命令延续** — 三条命令走一遍
3. **三种后端的实现** — 本地（密钥过滤）、Docker（长驻容器 + 安全参数）、SSH（ControlMaster）

不讲的：

- Modal / Daytona / Singularity → 模式和 Docker 相同
- 后台进程管理 → 终端工具的功能，不是后端的职责
- 文件同步（SSH 怎么把本地文件传到远程） → SSH 后端的增强功能
- 环境空闲回收 → 生产优化

## 这一章和后续章节的关系

- **s02** 注册了 terminal 工具 → 本章定义它背后的执行环境
- **s09** 的权限系统拦截危险命令 → 在命令到达后端之前
- **s13** 的适配器抽象和本章的后端抽象是同一种思路 — 把差异封装，上层不关心
- **s15** 的定时任务也执行命令 → 复用同一个后端

## 学完这章后，你应该能回答

- agent 执行了 `cd /tmp` 再执行 `pwd`，为什么能输出 `/tmp`？不是每条命令都在新 bash 里跑的吗？
- 为什么不维护一个长驻 bash 进程？
- 本地后端需要过滤 API key，Docker 后端需要吗？为什么？
- Docker 后端为什么用长驻容器而不是每条命令都 `docker run`？
- 在 config.yaml 里从 `local` 切到 `docker`，需要改几行工具代码？

---

**一句话记住：后端只需实现"怎么启动 bash"和"怎么清理"。snapshot 让环境变量和工作目录在新 bash 进程之间无缝延续。**
