# s23: Trajectory & RL Training (对话轨迹与强化学习)

`s00 > s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 > s13 > s14 > s15 > s16 > s17 > s18 > s19 > s20 > s21 > s22 > [ s23 ] > s24`

> *s20-s22 让 agent 在运行时学习——更新记忆、创建技能、挂 hook。这一章让 agent 在离线时进化——把对话轨迹变成训练数据，用强化学习训练下一代模型。*

![对话轨迹与 RL 训练流水线](../../illustrations/s23-trajectory-rl/01-flowchart-rl-pipeline.png)

## 这一章要解决什么问题

s20 的后台审视和 s21 的技能创作是**运行时学习**——agent 在当前对话里发现的知识，通过文件（MEMORY.md、skills/）传递给未来的自己。

但这有一个上限：文件里存的是"知识"，不是"能力"。agent 知道"用户不喜欢 type hints"（知识），但它写代码的能力本身不会因为这条记忆而提升。

**要让能力本身提升，需要训练模型。**

整条流水线：

```text
对话 → 轨迹收集 → 轨迹压缩 → 奖励打分 → 强化学习训练 → 更好的模型
```

**场景：从 1000 次对话到一个更强的模型。**

```text
1. batch_runner 用 500 个 prompt 跑 agent，每个 prompt 跑 2 遍
   → 1000 条对话轨迹，存成 JSONL

2. trajectory_compressor 把超长轨迹压缩到 15K token 以内
   → 保留头尾关键信息，中间用摘要替代

3. 环境打分：每条轨迹根据任务完成度得到 0-2 分
   → 完成 = 2.0，部分完成 = 1.0，失败 = 0.0

4. GRPO 训练：用 reward 信号微调模型
   → 2500 步，LoRA rank 32，lr 4e-5

5. 新模型在同样的 prompt 上表现更好
```

这不是理论——Hermes Agent 的模型就是这样迭代的。

## 建议联读

- [`s01-the-agent-loop.md`](./s01-the-agent-loop.md) — 每条轨迹本质上就是一次 `run_conversation` 的完整记录
- [`s20-background-review.md`](./s20-background-review.md) — 运行时学习 vs 离线训练的对比
- [`s05-context-compression.md`](./s05-context-compression.md) — 轨迹压缩复用了上下文压缩的思路

## 先解释几个名词

### 什么是 trajectory（轨迹）

一次完整对话的记录，格式化为 ShareGPT 格式：

```json
[
  {"from": "system", "value": "You are a helpful assistant..."},
  {"from": "human",  "value": "帮我写一个 Python 脚本"},
  {"from": "gpt",    "value": "<think>先分析需求...</think>好的，我来写..."},
  {"from": "gpt",    "value": "<tool_call>{\"name\": \"write_file\", ...}</tool_call>"},
  {"from": "tool",   "value": "<tool_response>{\"content\": \"Written 50 chars\"}</tool_response>"},
  {"from": "gpt",    "value": "文件写好了，你可以运行试试。"}
]
```

和 SQLite 里的 session 消息几乎一样，但有两个关键处理：
- reasoning（模型思考过程）统一包在 `<think>` 标签里
- 工具调用统一包在 `<tool_call>` / `<tool_response>` 标签里

### 什么是 batch_runner

批量跑 agent 的工具。输入一个 prompt 列表（JSONL），为每个 prompt 启动一个 agent 实例执行，收集轨迹和统计信息。

支持并行、断点续跑、自动过滤低质量样本。

### 什么是 trajectory_compressor

轨迹压缩器。很多对话轨迹太长（几万 token），直接训练效率低。压缩器保留头尾关键内容，中间部分用 LLM 生成摘要替代，把轨迹压到目标长度（默认 15250 token）。

### 什么是 GRPO

Group Relative Policy Optimization。一种强化学习算法，比 PPO 更适合语言模型。核心思路：对同一个 prompt 生成多条轨迹，用 reward 信号告诉模型"哪条更好"，模型朝好的方向更新。

## 最小心智模型

```text
第一阶段：收集
  prompts.jsonl → batch_runner → trajectory_samples.jsonl
                                  + tool_stats
                                  + reasoning_stats

第二阶段：压缩
  trajectory_samples.jsonl → trajectory_compressor → compressed.jsonl
    (50K tokens)              (保留头尾，压缩中间)    (15K tokens)

第三阶段：打分
  compressed.jsonl → 环境评分函数 → scored.jsonl
    每条轨迹 + 原始 prompt         (trajectory + reward)

第四阶段：训练
  scored.jsonl → GRPO trainer → 新模型权重
    同一 prompt 多条轨迹            LoRA adapters
    reward 高的强化，低的削弱
```

## 关键数据结构

### 轨迹记录（batch_runner 输出）

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

### 压缩配置

```yaml
tokenizer_name: "moonshotai/Kimi-K2-Thinking"
target_max_tokens: 15250
summary_target_tokens: 750

# 保护策略：头尾不压缩
protect_first_system: true
protect_first_human: true
protect_first_gpt: true
protect_last_n_turns: 4

# 摘要模型
summarization_model: "google/gemini-3-flash-preview"
summarization_temperature: 0.3
```

### 奖励函数

```python
def correctness_reward(prompts, completions, answer):
    """2.0 分如果完全正确，0.0 分如果错误。"""
    rewards = []
    for completion, expected in zip(completions, answer):
        if expected in completion:
            rewards.append(2.0)
        else:
            rewards.append(0.0)
    return rewards

def format_reward(completions):
    """0.5 分如果格式正确（有 <think> 和 <tool_call> 标签）。"""
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

奖励函数是可组合的——correctness 给最高分（2.0），format 做辅助信号（0.5）。GRPO 用加权和作为最终 reward。

## 最小实现

### 第一步：轨迹格式转换

把 `run_conversation` 的 messages 转成 ShareGPT 格式：

```python
def convert_to_trajectory(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-format messages to ShareGPT trajectory format."""
    trajectory = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # 角色映射
        if role == "system":
            from_field = "system"
        elif role == "user":
            from_field = "human"
        elif role == "assistant":
            from_field = "gpt"
            # 工具调用：包在 <tool_call> 标签里
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
            # 包在 <tool_response> 标签里
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

### 第二步：工具统计提取

```python
def extract_tool_stats(messages: list[dict]) -> dict:
    """Count tool usage: how many calls, successes, failures per tool."""
    stats: dict[str, dict] = {}
    # 找所有 tool_call → tool 对
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

### 第三步：批量收集（简化版 batch_runner）

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

    # 写入 JSONL
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = sum(1 for r in results if r.get("completed"))
    print(f"\nBatch complete: {ok}/{len(prompts)} succeeded → {output_path}")
    return results
```

### 第四步：轨迹压缩（简化版）

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

    # 保护头部：system + first human + first gpt/tool
    head = []
    rest = list(trajectory)
    for role in ["system", "human", "gpt"]:
        for i, turn in enumerate(rest):
            if turn["from"] == role:
                head.append(rest.pop(i))
                break

    # 保护尾部
    tail = rest[-protect_last_n:] if len(rest) > protect_last_n else []
    middle = rest[:-protect_last_n] if tail else rest

    # 压缩中间部分为摘要
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
    # 在教学版本里用规则摘要，生产版本用 LLM
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

## 场景走读：一条轨迹的完整生命

```text
=== 第一阶段：收集 ===

prompt: "用 Python 写一个 Markdown 转 HTML 的脚本"

agent 执行：
  Turn 1: [gpt] <think>需要用 markdown 库...</think> 我来写一个脚本。
  Turn 2: [gpt] <tool_call>{"name": "terminal", "arguments": {"command": "pip install markdown"}}</tool_call>
  Turn 3: [tool] <tool_response>{"content": "Successfully installed markdown-3.6"}</tool_response>
  Turn 4: [gpt] <tool_call>{"name": "write_file", ...}</tool_call>
  Turn 5: [tool] <tool_response>{"content": "Written 120 chars"}</tool_response>
  Turn 6: [gpt] <tool_call>{"name": "terminal", "arguments": {"command": "python convert.py test.md"}}</tool_call>
  Turn 7: [tool] <tool_response>{"content": "<h1>Hello</h1>"}</tool_response>
  Turn 8: [gpt] 脚本写好了，测试通过。

tool_stats: terminal(2/2), write_file(1/1)
reasoning_stats: 1/4 turns with <think>
completed: true

=== 第二阶段：压缩 ===

原始：8 turns, ~3000 tokens → 不需要压缩（< 15250）
（如果是 50K token 的复杂对话，Turn 3-5 会被压缩成一段摘要）

=== 第三阶段：打分 ===

correctness_reward: 脚本能跑且输出正确 → 2.0
format_reward: 有 <think> 和 <tool_call> → 0.5
total_reward: 2.5

=== 第四阶段：训练 ===

GRPO 拿到同一个 prompt 的多条轨迹（比如 4 条）：
  轨迹 A: reward 2.5（成功 + 格式好）
  轨迹 B: reward 2.0（成功但没 think）
  轨迹 C: reward 0.5（失败但格式对）
  轨迹 D: reward 0.0（失败 + 格式差）

模型更新方向：强化 A 和 B 的行为模式，削弱 C 和 D 的
```

## 为什么不直接用 SFT（监督微调）

SFT 只学"正确答案"。但 agent 的对话里有大量的**探索行为**——试错、回退、换方案——这些行为没有"正确答案"，只有"好坏程度"。

RL 的优势：**它能从"差一点对了"和"完全错了"之间学到区别。** SFT 只能学"对了"和"没学到"两种状态。

| | SFT | RL (GRPO) |
|---|---|---|
| 信号 | 二值：对/不对 | 连续：reward 分数 |
| 学什么 | 模仿正确轨迹 | 从好/坏对比中学习 |
| 对探索的态度 | 忽略 | 失败的探索也有学习价值 |
| 数据效率 | 需要高质量正确答案 | 任何轨迹都能用（只要有 reward） |

## 初学者最容易犯的错

### 1. 不过滤零推理样本

如果 agent 在某条轨迹里完全没有 `<think>` 推理，这条轨迹会教模型"不需要思考就行动"。

**修：batch_runner 自动丢弃 `has_any_reasoning=false` 的样本。**

### 2. 压缩时删了头尾

头部（system prompt + 用户问题）定义了任务是什么。尾部（最后几轮）包含最终结果。压掉任何一个，模型学到的就是"中间过程没有目标"。

**修：protect_first_system/human/gpt + protect_last_n_turns 永远不压缩。**

### 3. reward 函数只有正确性

只按"最终结果对不对"打分。模型学到了"蒙对就行"——它会跳过推理直接猜答案。

**修：叠加 format_reward，奖励好的推理格式，惩罚没有 `<think>` 的轨迹。**

### 4. 同一 prompt 只跑一次

GRPO 需要对比同一 prompt 的多条轨迹。只跑一次没有对比对象。

**修：每个 prompt 至少跑 2 遍（batch_runner 可配）。**

## 教学边界

这一章讲四件事：

1. **轨迹格式** — ShareGPT 格式、reasoning 标签、tool_call/tool_response 标签
2. **批量收集** — batch_runner 的 prompt → trajectory 流程
3. **轨迹压缩** — 保护头尾、压缩中间、token 预算
4. **RL 训练基础** — reward 函数、GRPO 思路、为什么不只用 SFT

不讲的：

- GRPO 的数学推导 → RL 理论课
- Atropos / Tinker 的具体 API → 平台接线
- WandB 配置和指标解读 → MLOps 细节
- 多 GPU 训练和分布式调度 → 基础设施
- 数据集的具体来源和清洗 → 数据工程

## 这一章和其他章节的关系

- **s01** 的核心循环 → 每条轨迹就是一次 `run_conversation` 的完整记录
- **s05** 的上下文压缩 → 轨迹压缩复用了同样的"保护头尾，压缩中间"策略
- **s20** 的后台审视 → 运行时学习（改文件），s23 是离线学习（改模型）
- **s21** 的技能创作 → 运行时进化，s23 是基因级进化
- **s24** 的 Plugin 架构 → RL 环境可以作为 plugin 扩展

**s20-s21 是 agent 的"学习"，s23 是 agent 的"进化"。** 学习改变知识，进化改变能力本身。

## 学完这章后，你应该能回答

- 轨迹格式里为什么要把 reasoning 包在 `<think>` 标签里？
- 压缩轨迹时为什么头尾不能压？
- 为什么 GRPO 需要同一 prompt 的多条轨迹？
- reward 函数只有 correctness 会出什么问题？
- 运行时学习（s20-s21）和离线训练（s23）各解决什么层面的问题？

---

**一句话记住：对话轨迹是 agent 的经验记录。batch_runner 收集它，trajectory_compressor 压缩它，GRPO 从中学习——让下一代模型的能力本身变强，而不只是知道更多知识。**
