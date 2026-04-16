# s15: Scheduled Tasks (定时任务)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > [ s15 ] > s16 > s17 > s18 > s19 > s20 > s21 > s22 > s23 > s24`

> *s01-s14 的 agent 只能被动响应——用户发消息它才做事。这一章让 agent 学会"记住未来该做什么"，到时间自己动手。*

![定时任务生命周期](../../illustrations/s15-scheduled-tasks/01-flowchart-task-lifecycle.png)

## 这一章要解决什么问题

到 s14 为止，agent 的工作方式是：用户说一句话 → agent 做事 → 回复。用户不说话，agent 就闲着。

但真实场景里用户会说这些话：

> "**30 分钟后**帮我看看刚才的部署有没有成功。"

> "**每 2 小时**查一次服务器磁盘使用率，超过 80% 就告诉我。"

> "**每个工作日早上 9 点**给我总结一下昨天的 git log。"

三个需求，一个共同点：**用户想让 agent 在未来某个时间主动做事。**

没有定时任务系统，agent 只能说"好的，请你到时候再提醒我"——这和闹钟有什么区别？

## 场景走读：一个定时任务的完整生命周期

用户在 Telegram 上对 agent 说："30分钟后帮我检查部署状态"。

```text
1. agent 理解意图，调用 cron_tool：
   create_job(schedule="30m", prompt="检查部署状态，运行 kubectl get pods")

2. cron_tool 解析 "30m"：
   - 当前时间 14:00
   - next_fire = 14:30
   - one_shot = true（执行一次就删）

3. JobStore 把这个 job 写入 jobs.json

4. agent 回复用户："好的，30分钟后我会检查部署状态。"

5. 后台的 JobScheduler 每 30 秒扫一次 jobs.json……
   - 14:00:30 — 没到时间，跳过
   - 14:01:00 — 没到时间，跳过
   - ...
   - 14:30:00 — 到了！

6. JobScheduler 构造一条 MessageEvent：
   text = "检查部署状态，运行 kubectl get pods"
   source.platform = "cron"
   source.chat_id = 原来那个 Telegram 用户的 chat_id

7. 这条 MessageEvent 送进 GatewayRunner._handle_message()
   → 和真实用户消息走完全一样的路

8. agent 执行 kubectl get pods，拿到结果，回复到 Telegram

9. 因为 one_shot=true，JobStore 自动删除这个 job
```

关键洞察：**定时任务不是一个新的执行路径。它只是一个会在未来某个时间"假装用户说了句话"的机制。** 从 GatewayRunner 往下，所有逻辑完全复用。

## 建议联读

- [`s02-tool-system.md`](./s02-tool-system.md) — cron_tool 通过自注册接入
- [`s12-gateway-architecture.md`](./s12-gateway-architecture.md) — job 触发时走 Gateway 的 `_handle_message`
- [`s14-terminal-backends.md`](./s14-terminal-backends.md) — job 触发的命令复用同一个后端

## 先解释几个名词

### 什么是 CronJob

一个定时任务的完整描述。包含：什么时候触发、触发时给 agent 发什么消息、属于哪个会话。

```python
@dataclass
class CronJob:
    job_id: str           # 唯一标识
    schedule: str         # 原始调度表达式："30m" / "every 2h" / "0 9 * * 1-5"
    prompt: str           # 触发时发给 agent 的消息
    session_key: str      # 属于哪个会话
    created_at: str       # 创建时间
    next_fire: float      # 下次触发的 unix timestamp
    one_shot: bool        # True = 执行一次就删，False = 循环执行
```

### 三种调度格式

| 格式 | 示例 | 含义 | one_shot |
|------|------|------|----------|
| 延时 | `30m` | 30 分钟后执行一次 | True |
| 间隔 | `every 2h` | 每 2 小时循环执行 | False |
| Cron | `0 9 * * 1-5` | 每个工作日早上 9 点 | False |

为什么不只用 cron 表达式？因为用户说"30分钟后提醒我"的频率远高于"帮我设个 cron"。延时格式让最常见的场景最简单。

### 什么是 JobStore

定时任务的持久化层。负责增删改查和写盘。

为什么用 `jobs.json` 而不是 SQLite？

- 任务数量少——一个用户通常不超过 20 个活跃任务
- 人可读——调试时直接打开看
- 不需要全文搜索或并发写入

SQLite 是给海量会话消息设计的。用它存 20 个 job 是杀鸡用牛刀。

### 什么是 JobScheduler

后台线程，每 30 秒醒一次，扫描所有 job，触发到期的。

为什么是线程不是 asyncio？因为调度器需要在 CLI 模式（同步）和 Gateway 模式（异步）下都能跑。线程是两种模式的最大公约数。

## 最小心智模型

```text
用户（或 agent 自己）
    │
    │  cron_tool: create_job(schedule="every 2h", prompt="检查磁盘")
    v
JobStore
    │  写入 jobs.json
    │
    │  ┌─────────────── 后台 ──────────────────┐
    │  │  JobScheduler（线程，每 30 秒扫一次）     │
    │  │                                        │
    │  │  for job in jobs:                      │
    │  │      if now >= job.next_fire:           │
    │  │          fire(job)                     │
    │  └────────────────────────────────────────┘
    │
    │  fire(job):
    v
构造 MessageEvent(text=job.prompt, platform="cron")
    │
    │  送进 GatewayRunner._handle_message()
    v
和真实用户消息走完全一样的路
    │
    │  agent 执行、回复
    v
结果发回原来的平台（Telegram / Discord / CLI）
```

## 关键数据结构

### jobs.json

```json
[
  {
    "job_id": "a1b2c3",
    "schedule": "every 2h",
    "prompt": "运行 df -h，如果任何分区超过 80% 就告警",
    "session_key": "main:telegram:alice",
    "created_at": "2025-01-15T14:00:00",
    "next_fire": 1736953200.0,
    "one_shot": false
  },
  {
    "job_id": "d4e5f6",
    "schedule": "0 9 * * 1-5",
    "prompt": "总结昨天的 git log，只看 main 分支",
    "session_key": "main:telegram:alice",
    "created_at": "2025-01-15T14:05:00",
    "next_fire": 1737007200.0,
    "one_shot": false
  }
]
```

## 从最笨的实现开始

在 agent 循环里加一个 `time.sleep` 轮询：

```python
# 最笨：在主循环里轮询
while True:
    user_input = input("You: ")
    if user_input:
        handle_message(user_input)

    # 检查定时任务
    for job in jobs:
        if time.time() >= job.next_fire:
            handle_message(job.prompt)  # 假装用户说了这句话
            update_next_fire(job)
```

能跑，但有两个问题。

### 问题一：阻塞

`input()` 会阻塞。用户不输入，定时任务就永远检查不到。

你可能会想："用 `select` 或 `threading` 让 `input` 不阻塞。"可以，但这就引出了问题二。

### 问题二：Gateway 模式下怎么办

Gateway 模式是异步的，没有 `input()`。你需要一个独立于入口模式的调度机制。

**解法：把调度器放进一个独立的后台线程。** CLI 和 Gateway 都启动同一个线程，线程到期时构造 MessageEvent 送进处理管线。

## 最小实现

### 调度表达式解析

三种格式的解析逻辑：

```python
def parse_schedule(expr: str) -> tuple[float, bool]:
    """
    解析调度表达式，返回 (next_fire_timestamp, one_shot)。

    支持：
      "30m"           → 30 分钟后，一次性
      "2h"            → 2 小时后，一次性
      "every 30m"     → 每 30 分钟，循环
      "every 2h"      → 每 2 小时，循环
      "0 9 * * 1-5"   → cron 表达式，循环
    """
    expr = expr.strip()
    now = time.time()

    # 格式 1: "every Xm" / "every Xh" → 循环间隔
    if expr.startswith("every "):
        seconds = _parse_duration(expr[6:])
        return now + seconds, False

    # 格式 2: "Xm" / "Xh" → 一次性延时
    try:
        seconds = _parse_duration(expr)
        return now + seconds, True
    except ValueError:
        pass

    # 格式 3: cron 表达式
    next_ts = _next_cron_fire(expr)
    return next_ts, False
```

`_parse_duration` 很简单——从字符串末尾拿单位，前面是数字：

```python
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

def _parse_duration(s: str) -> float:
    s = s.strip()
    unit = s[-1].lower()
    if unit not in _UNITS:
        raise ValueError(f"unknown unit: {unit}")
    return float(s[:-1]) * _UNITS[unit]
```

### Cron 表达式解析

五字段 cron 不需要第三方库，标准格式足够：

```text
分 时 日 月 星期几
0  9  *  *  1-5     ← 工作日早上 9 点
```

核心思路：从"现在"开始逐分钟往前推，直到找到一个匹配所有五个字段的时间点。

```python
def _next_cron_fire(expr: str) -> float:
    """从当前时间开始，找到下一个匹配 cron 表达式的时间点。"""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs 5 fields, got {len(fields)}: {expr}")

    matchers = [_parse_cron_field(f, r) for f, r in
                zip(fields, [(0,59), (0,23), (1,31), (1,12), (0,6)])]

    # 从下一分钟开始找，最多找 366 天
    t = datetime.now().replace(second=0, microsecond=0)
    t += timedelta(minutes=1)

    for _ in range(366 * 24 * 60):
        if (matchers[0](t.minute) and matchers[1](t.hour)
                and matchers[2](t.day) and matchers[3](t.month)
                and matchers[4](t.weekday())):
            # Python weekday(): 0=Mon, cron: 0=Sun → 转换
            return t.timestamp()
        t += timedelta(minutes=1)

    raise ValueError(f"no match in 366 days for: {expr}")
```

`_parse_cron_field` 处理 `*`、`*/5`、`1-5`、`1,3,5` 这四种语法，返回一个 `int → bool` 的判断函数。这是 cron 解析最复杂的部分，但不是本章重点，放在代码文件里。

### JobStore

```python
class JobStore:
    """任务持久化：CRUD + 写盘。"""

    def __init__(self, path: str = "jobs.json"):
        self._path = Path(path)
        self._jobs: dict[str, CronJob] = {}
        self._lock = threading.Lock()
        self._load()

    def add(self, job: CronJob):
        with self._lock:
            self._jobs[job.job_id] = job
            self._save()

    def remove(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._save()
                return True
            return False

    def list_all(self) -> list[CronJob]:
        with self._lock:
            return list(self._jobs.values())

    def get_due(self) -> list[CronJob]:
        """返回所有到期的 job。"""
        now = time.time()
        with self._lock:
            return [j for j in self._jobs.values() if now >= j.next_fire]

    def advance(self, job: CronJob):
        """更新 next_fire（循环任务），或删除（一次性任务）。"""
        with self._lock:
            if job.one_shot:
                self._jobs.pop(job.job_id, None)
            else:
                next_ts, _ = parse_schedule(job.schedule)
                job.next_fire = next_ts
            self._save()

    def _save(self):
        data = [vars(j) for j in self._jobs.values()]
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load(self):
        if not self._path.exists():
            return
        for item in json.loads(self._path.read_text()):
            job = CronJob(**item)
            self._jobs[job.job_id] = job
```

为什么要加锁？因为 JobScheduler 在后台线程里读 `_jobs`，cron_tool 在主线程里写 `_jobs`。不加锁 → 竞态条件。

### JobScheduler

```python
class JobScheduler:
    """后台线程，周期性检查到期任务并触发。"""

    def __init__(self, store: JobStore, fire_callback):
        self._store = store
        self._fire = fire_callback   # def fire(job: CronJob) → None
        self._interval = 30          # 秒
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            for job in self._store.get_due():
                try:
                    self._fire(job)
                except Exception as e:
                    print(f"  [scheduler] job {job.job_id} failed: {e}")
                self._store.advance(job)
            time.sleep(self._interval)
```

`daemon=True` 很重要：主进程退出时后台线程自动结束，不会卡住。

### cron_tool：agent 的接口

```python
def handle_cron_tool(args: dict, *, store: JobStore, session_key: str, **kw):
    action = args.get("action", "list")

    if action == "create":
        schedule = args["schedule"]
        prompt = args["prompt"]
        next_fire, one_shot = parse_schedule(schedule)
        job = CronJob(
            job_id=uuid.uuid4().hex[:8],
            schedule=schedule,
            prompt=prompt,
            session_key=session_key,
            created_at=datetime.now().isoformat(),
            next_fire=next_fire,
            one_shot=one_shot,
        )
        store.add(job)
        fire_time = datetime.fromtimestamp(next_fire).strftime("%Y-%m-%d %H:%M")
        return f"Job {job.job_id} created. Next fire: {fire_time}"

    elif action == "list":
        jobs = store.list_all()
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            fire_time = datetime.fromtimestamp(j.next_fire).strftime("%m-%d %H:%M")
            kind = "once" if j.one_shot else "recurring"
            lines.append(f"  {j.job_id}  {j.schedule:15s}  {kind:9s}  "
                         f"next: {fire_time}  {j.prompt[:40]}")
        return "Jobs:\n" + "\n".join(lines)

    elif action == "delete":
        job_id = args["job_id"]
        if store.remove(job_id):
            return f"Job {job_id} deleted."
        return f"Job {job_id} not found."

    return f"Unknown action: {action}"
```

工具定义注册给模型：

```python
CRON_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "cron",
        "description": "Create, list, or delete scheduled tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "delete"],
                },
                "schedule": {
                    "type": "string",
                    "description": 'Schedule expression: "30m", "every 2h", or "0 9 * * 1-5"',
                },
                "prompt": {
                    "type": "string",
                    "description": "What the agent should do when the job fires.",
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID to delete (for action=delete).",
                },
            },
            "required": ["action"],
        },
    },
}
```

## 场景二：循环任务触发后怎么回到用户

用户在 Telegram 上说："每 2 小时帮我查一下磁盘"。

```text
1. agent 调 cron_tool: create_job(schedule="every 2h", prompt="运行 df -h，超 80% 告警")
2. JobStore 写入 jobs.json，next_fire = 2 小时后

   === 2 小时后 ===

3. JobScheduler 发现 job 到期
4. 构造 MessageEvent：
     text = "运行 df -h，超 80% 告警"
     source.platform = "cron"
     source.chat_id = "main:telegram:alice"   ← 原来那个用户的 session_key

5. 送进 GatewayRunner._handle_message()
6. agent 执行 df -h（通过 s14 的终端后端）
7. 发现 /data 分区 85% → agent 回复告警信息
8. GatewayRunner 把回复发回 Telegram
9. JobStore 更新 next_fire = 再过 2 小时

   === 又过 2 小时 ===

10. 重复步骤 3-9
```

注意步骤 4：**JobScheduler 不直接执行命令，而是构造一条消息塞进 Gateway。** 这意味着 job 的执行享受 agent 的全部能力——工具调用、错误恢复、权限检查、上下文压缩——全部复用，一行都不用重写。

## 场景三：CLI 模式下怎么触发

Gateway 模式有 `_handle_message` 可以接 MessageEvent。CLI 模式没有。

解法：CLI 模式下，JobScheduler 的 `fire_callback` 直接调 `run_conversation()`：

```python
# Gateway 模式
def fire_gateway(job):
    event = MessageEvent(
        text=job.prompt,
        source=SessionSource(platform="cron", chat_id=..., ...),
    )
    asyncio.run_coroutine_threadsafe(
        gateway._handle_message(event), loop
    )

# CLI 模式
def fire_cli(job):
    result = run_conversation(job.prompt, conn, session_id, cached_prompt)
    print(f"\n[cron] {job.job_id}: {result['final_response']}\n")
```

两种模式，同一个 JobScheduler，不同的 `fire_callback`。

## 如何接到主循环里

```text
启动时
  │
  ├── CLI 模式
  │     JobStore("jobs.json")
  │     JobScheduler(store, fire_callback=fire_cli)
  │     scheduler.start()         ← 后台线程启动
  │     while True:
  │         input() → run_conversation()   ← 主线程处理用户输入
  │
  └── Gateway 模式
        JobStore("jobs.json")
        JobScheduler(store, fire_callback=fire_gateway)
        scheduler.start()         ← 后台线程启动
        GatewayRunner.start()     ← asyncio 事件循环

关闭时
  scheduler.stop()
```

工具注册时需要把 `store` 和 `session_key` 传进去：

```python
# 注册 cron 工具时，用闭包绑定 store
def make_cron_handler(store, session_key):
    def handler(args, **kw):
        return handle_cron_tool(args, store=store, session_key=session_key, **kw)
    return handler

tool_registry.register("cron", make_cron_handler(store, current_session_key))
```

## Hermes Agent 的独特设计

### 任务即消息

大多数定时任务系统到期后直接执行一个函数。Hermes Agent 不这样——**到期后构造一条 MessageEvent，伪装成用户消息送进 Gateway。**

这带来三个好处：

1. **全部能力免费复用。** 工具调用、错误恢复、权限检查、子 agent 委派——全都自动生效。
2. **执行历史自动持久化。** 任务触发的对话存在 SQLite 里，和用户发起的对话一样可搜索。
3. **回复自动路由。** 结果通过原来的平台（Telegram / Discord）发回给用户，不需要额外接线。

### 三种调度格式的设计取舍

为什么不只用 cron 表达式？

用户说"30分钟后提醒我"的频率远高于"设个 cron"。如果强制用 cron 格式：
- 用户说的："30分钟后"
- agent 要算出的：当前时间 14:00，那就是 `30 14 15 1 *`（2025-01-15 14:30）
- 还得考虑跨天、跨月、时区

用延时格式一行搞定：`parse_schedule("30m")` → `(now + 1800, True)`。

简单场景简单做，复杂场景用 cron。

## 初学者最容易犯的错

### 1. 在主线程里检查定时任务

```python
while True:
    user_input = input()     # ← 阻塞
    check_cron_jobs()        # ← 永远执行不到
```

`input()` 阻塞了主线程，定时任务永远触发不了。

**修：调度器放独立线程。**

### 2. 忘了加锁

JobStore 被两个线程访问：主线程（cron_tool 写入）和后台线程（JobScheduler 读取）。不加锁 → 字典遍历时大小改变 → `RuntimeError`。

**修：JobStore 的每个方法都 `with self._lock`。**

### 3. 一次性任务不删除

`one_shot=True` 的 job 触发后忘了从 store 里删除。30 秒后 scheduler 又扫到它，又触发一次。

**修：`advance()` 方法里，one_shot 直接 pop，不是更新 next_fire。**

### 4. Cron 表达式的星期几搞错

Python `datetime.weekday()` 返回 0=Monday ... 6=Sunday。标准 cron 的 0=Sunday。

```text
cron 里的 5 = Friday
Python 里的 5 = Saturday
```

一字之差，任务在错误的日子触发。

**修：解析时做 `(python_weekday + 1) % 7` 转换，或者在 cron 匹配时注意映射。**

### 5. 没处理 jobs.json 损坏

进程在写 `jobs.json` 的时候崩了，文件只写了一半。下次启动 `json.loads` 直接报错。

**修：写入时先写临时文件再 rename（原子操作），读取时 catch `json.JSONDecodeError` 并降级到空列表。**

## 教学边界

这一章讲三件事：

1. **为什么需要定时任务** — 从"agent 只能被动响应"的痛点推出
2. **三种调度格式** — 延时、间隔、cron 表达式的解析
3. **任务即消息** — job 到期后伪装成 MessageEvent 送进 Gateway

不讲的：

- 分布式调度（多个 Gateway 实例怎么不重复触发同一个 job）→ 生产优化
- 任务依赖链（job A 完成后才触发 job B）→ 太接近工作流引擎
- 时区处理 → 教学里用本地时间，生产环境需要存 UTC + 用户时区
- 任务执行超时和重试策略 → s06 的错误恢复已经覆盖

## 这一章和其他章节的关系

- **s02** 注册了 cron_tool → 和其他工具一样自注册
- **s03** 的 SQLite → 定时任务触发的对话也存在 session 里
- **s06** 的错误恢复 → job 触发的 agent 循环如果出错，走同样的重试逻辑
- **s12** 的 Gateway → job 到期时走 `_handle_message`，和平台消息同路
- **s14** 的终端后端 → job 里的命令复用同一个 backend

**s15 是阶段 3 的最后一章。** 到这里，Hermes Agent 已经能：
- 从十几个消息平台接收消息（s12-s13）
- 在不同执行环境里跑命令（s14）
- 在未来某个时间主动做事（s15）

阶段 4 开始进入高级能力：MCP、浏览器自动化、语音视觉。

## 学完这章后，你应该能回答

- 为什么定时任务到期后要构造 MessageEvent，而不是直接执行命令？
- 用户说"30分钟后提醒我"，为什么不把它解析成 cron 表达式？
- JobScheduler 为什么是线程而不是 asyncio task？
- 一次性任务和循环任务在 `advance()` 里的处理有什么区别？
- CLI 模式和 Gateway 模式下，job 触发的路径有什么不同？

---

**一句话记住：定时任务不是新的执行路径——它只是一个会在未来"假装用户说了句话"的机制。从 Gateway 往下，所有逻辑完全复用。**
