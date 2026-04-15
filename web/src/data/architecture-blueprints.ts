type LocalizedText = { zh: string; en: string };

function l(zh: string, en: string): LocalizedText {
  return { zh, en };
}

interface ArchitectureItem {
  name: LocalizedText;
  note?: LocalizedText;
  fresh?: boolean;
}

type ArchitectureSliceId = "mainline" | "control" | "state" | "lanes";

interface ArchitectureBlueprint {
  summary: LocalizedText;
  slices: Partial<Record<ArchitectureSliceId, ArchitectureItem[]>>;
  records: ArchitectureItem[];
  handoff: LocalizedText[];
}

export type { LocalizedText, ArchitectureItem, ArchitectureSliceId, ArchitectureBlueprint };

export const ARCHITECTURE_BLUEPRINTS: Record<string, ArchitectureBlueprint> = {
  s01: {
    summary: l("最小同步循环：发给模型 -> 处理工具 -> 回写 -> 继续", "Minimal sync loop: send to model -> execute tools -> write back -> continue"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()"), fresh: true },
        { name: l("OpenAI SDK", "OpenAI SDK"), fresh: true },
      ],
      state: [
        { name: l("messages[]", "messages[]"), fresh: true },
      ],
    },
    records: [
      { name: l("messages 列表", "messages list"), note: l("当前对话的完整消息", "Complete messages for current conversation") },
    ],
    handoff: [
      l("① 用户输入追加到 messages", "① User input appended to messages"),
      l("② messages + system prompt 发给 API", "② messages + system prompt sent to API"),
      l("③ tool_calls 执行后写回 messages", "③ tool_calls executed and written back"),
      l("④ 无 tool_calls 时返回最终回复", "④ Return final response when no tool_calls"),
    ],
  },
  s02: {
    summary: l("自注册工具系统：每个工具文件导入时自动登记", "Self-registering tool system: each tool registers on import"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()") },
        { name: l("ToolRegistry", "ToolRegistry"), fresh: true },
      ],
      control: [
        { name: l("dispatch()", "dispatch()"), fresh: true },
        { name: l("get_definitions()", "get_definitions()"), fresh: true },
      ],
    },
    records: [
      { name: l("ToolEntry", "ToolEntry"), note: l("name -> handler 映射", "name -> handler mapping"), fresh: true },
    ],
    handoff: [
      l("① 工具文件导入时调用 register()", "① Tool file calls register() on import"),
      l("② 循环通过 get_definitions() 获取工具列表", "② Loop gets tool list via get_definitions()"),
      l("③ 模型返回 tool_calls 后通过 dispatch() 分发", "③ After model returns tool_calls, dispatch via dispatch()"),
    ],
  },
  s03: {
    summary: l("SQLite + WAL 持久化：对话跨重启存活", "SQLite + WAL persistence: conversations survive restarts"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()") },
        { name: l("ToolRegistry", "ToolRegistry") },
      ],
      state: [
        { name: l("messages[]", "messages[]") },
        { name: l("SQLite sessions", "SQLite sessions"), fresh: true },
        { name: l("SQLite messages", "SQLite messages"), fresh: true },
        { name: l("FTS5 索引", "FTS5 index"), fresh: true },
      ],
    },
    records: [
      { name: l("session 行", "session row"), note: l("id, source, started_at", "id, source, started_at"), fresh: true },
      { name: l("message 行", "message row"), note: l("role, content, tool_calls, timestamp", "role, content, tool_calls, timestamp"), fresh: true },
    ],
    handoff: [
      l("① 启动时从 SQLite 加载历史 messages", "① Load history from SQLite on startup"),
      l("② 每条新消息实时写入 SQLite", "② Each new message written to SQLite in real-time"),
      l("③ FTS5 索引支持全文搜索", "③ FTS5 index enables full-text search"),
    ],
  },
  s04: {
    summary: l("多来源系统提示词：人设 + 记忆 + 项目配置 -> 缓存复用", "Multi-source system prompt: soul + memory + project -> cached reuse"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()") },
        { name: l("build_system_prompt()", "build_system_prompt()"), fresh: true },
      ],
      state: [
        { name: l("SOUL.md", "SOUL.md"), fresh: true },
        { name: l("MEMORY.md", "MEMORY.md"), fresh: true },
        { name: l("HERMES.md", "HERMES.md"), fresh: true },
        { name: l("cached_prompt", "cached_prompt"), fresh: true },
      ],
    },
    records: [],
    handoff: [
      l("① 会话开始时读取多个来源", "① Read multiple sources at session start"),
      l("② 组装成一条 system prompt", "② Assemble into single system prompt"),
      l("③ 缓存后整个会话复用", "③ Cache and reuse for entire session"),
    ],
  },
  s05: {
    summary: l("上下文压缩：超阈值时用 LLM 摘要替代中间细节", "Context compression: replace middle details with LLM summary when over threshold"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()") },
      ],
      control: [
        { name: l("estimate_tokens()", "estimate_tokens()"), fresh: true },
        { name: l("compress()", "compress()"), fresh: true },
        { name: l("summarize_middle()", "summarize_middle()"), fresh: true },
      ],
    },
    records: [
      { name: l("[CONTEXT COMPACTION]", "[CONTEXT COMPACTION]"), note: l("压缩后插入的摘要消息", "Summary message inserted after compression"), fresh: true },
    ],
    handoff: [
      l("① 每轮循环前估算 token 数", "① Estimate tokens before each loop iteration"),
      l("② 超过阈值 -> 裁剪旧工具输出 -> 划分 head/tail", "② Over threshold -> prune old outputs -> split head/tail"),
      l("③ 中间部分用辅助 LLM 做摘要", "③ Summarize middle section with auxiliary LLM"),
      l("④ 摘要替代原文，循环继续", "④ Summary replaces originals, loop continues"),
    ],
  },
  s06: {
    summary: l("错误恢复：分类 -> 退避重试 / 压缩 / 故障转移", "Error recovery: classify -> backoff retry / compress / fallback"),
    slices: {
      mainline: [
        { name: l("run_conversation()", "run_conversation()") },
      ],
      control: [
        { name: l("classify_error()", "classify_error()"), fresh: true },
        { name: l("jittered_backoff()", "jittered_backoff()"), fresh: true },
        { name: l("switch_to_fallback()", "switch_to_fallback()"), fresh: true },
      ],
      lanes: [
        { name: l("备用模型", "Fallback model"), fresh: true },
      ],
    },
    records: [],
    handoff: [
      l("① API 调用失败 -> classify_error()", "① API call fails -> classify_error()"),
      l("② context_overflow -> 触发压缩 -> 重试", "② context_overflow -> trigger compress -> retry"),
      l("③ rate_limit -> 退避 + 抖动 -> 重试", "③ rate_limit -> backoff + jitter -> retry"),
      l("④ auth / model_not_found -> 切换备用模型", "④ auth / model_not_found -> switch to fallback"),
      l("⑤ finish_reason=length -> 续写", "⑤ finish_reason=length -> continuation"),
    ],
  },
};

export function getArchitectureBlueprint(version: string): ArchitectureBlueprint | null {
  return ARCHITECTURE_BLUEPRINTS[version] ?? null;
}
