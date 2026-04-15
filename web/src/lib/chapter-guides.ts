interface ChapterGuide {
  focus: string;
  confusion: string;
  goal: string;
}

const GUIDES_ZH: Record<string, ChapterGuide> = {
  s00: {
    focus: "先盯住五层架构图和一条消息的完整流动路径。",
    confusion: "不要把 CLI 和 Gateway 当成两套系统，它们共用同一个核心循环。",
    goal: "能画出 Hermes Agent 的五层架构，说清每一层的职责。",
  },
  s01: {
    focus: "先盯住 messages 列表如何在 user → assistant → tool 之间闭环回流。",
    confusion: '不要把"模型会思考"和"系统能行动"混成一回事。模型只输出意图，系统负责执行。',
    goal: "手写一个最小但可运行的同步对话循环。",
  },
  s02: {
    focus: "先盯住 register() → dispatch() 的完整链路，不要一开始就看单个工具的实现。",
    confusion: "注册表不依赖任何工具，工具依赖注册表。导入方向是单向的。",
    goal: "手写一个自注册工具系统，新增工具不改循环代码。",
  },
  s03: {
    focus: "先盯住 WAL 模式和 session/messages 两张表的关系。",
    confusion: "Session 不是聊天记录展示，是模型下一轮要读的输入的持久化。",
    goal: "让 agent 重启后能恢复历史对话。",
  },
  s04: {
    focus: "先盯住多来源组装和缓存机制——为什么同一会话只组装一次。",
    confusion: "SOUL.md 是人设，MEMORY.md 是记忆，HERMES.md 是项目规则，三者性质不同。",
    goal: "手写一个从多个来源组装 system prompt 的管道。",
  },
  s05: {
    focus: "先盯住压缩触发条件和 head/tail 边界的划分逻辑。",
    confusion: "压缩不是删除历史，而是用摘要替代中间细节。",
    goal: "手写一个上下文膨胀时自动摘要压缩的机制。",
  },
  s06: {
    focus: "先盯住 classify_error 的分类逻辑——不同错误走不同恢复路径。",
    confusion: "429 不是致命错误，是退避信号；400 context overflow 是压缩信号。",
    goal: "手写一套错误分类 + 退避重试 + 故障转移。",
  },
  s07: {
    focus: "先搞清 MEMORY.md 和 Session 的区别——一个是精选，一个是全量。",
    confusion: "记忆写入是即时的，但效果是延迟的（下次会话才生效）。",
    goal: "手写一个跨会话的持久记忆系统。",
  },
  s08: {
    focus: "先搞清技能和工具的区别——技能是 agent 管理的，工具是开发者硬编码的。",
    confusion: '技能不替代工具，技能是"agent 用工具做事的方法"。',
    goal: "手写一个能创建、编辑、执行的技能系统。",
  },
  s09: {
    focus: "先盯住 DANGEROUS_PATTERNS 列表和审批流程。",
    confusion: "权限系统不是通用的 deny/allow，是专门针对终端命令的模式匹配。",
    goal: '手写一条"危险操作先过闸"的审批管道。',
  },
  s10: {
    focus: "先盯住子 agent 的独立 messages 和 budget 共享机制。",
    confusion: "子 agent 的中间过程不回到父 agent，只有最终结果回来。",
    goal: "手写一个能隔离上下文做委派的子 agent 机制。",
  },
  s11: {
    focus: "先盯住 _deep_merge 和两文件分离（config.yaml vs .env）。",
    confusion: "dict.update() 会丢嵌套字段，必须用递归深度合并。",
    goal: "手写一套 YAML 配置 + Profile 隔离 + 运行时迁移。",
  },
};

const GUIDES_EN: Record<string, ChapterGuide> = {
  s00: { focus: "Focus on the five-layer architecture and message flow.", confusion: "CLI and Gateway share the same core loop.", goal: "Draw the five-layer architecture and explain each layer." },
  s01: { focus: "Watch how messages flow between user, assistant, and tool.", confusion: "The model outputs intent; the system executes.", goal: "Build a minimal synchronous agent loop." },
  s02: { focus: "Trace the register() → dispatch() chain.", confusion: "Registry depends on nothing; tools depend on registry.", goal: "Build a self-registering tool system." },
  s03: { focus: "Understand WAL mode and the session/messages table relationship.", confusion: "Session is not chat display — it's persisted model input.", goal: "Make conversations survive restarts." },
  s04: { focus: "Understand multi-source assembly and why caching matters.", confusion: "SOUL.md, MEMORY.md, HERMES.md serve different purposes.", goal: "Build a multi-source system prompt pipeline." },
  s05: { focus: "Understand compression triggers and head/tail boundary logic.", confusion: "Compression replaces detail with summaries, not deletion.", goal: "Build auto-compression for long contexts." },
  s06: { focus: "Understand classify_error and different recovery paths.", confusion: "429 means back off; 400 context overflow means compress.", goal: "Build error classification + retry + fallback." },
  s07: { focus: "Distinguish MEMORY.md from Session — curated vs. complete.", confusion: "Memory writes are immediate but take effect next session.", goal: "Build a persistent cross-session memory system." },
  s08: { focus: "Distinguish skills from tools — agent-managed vs hardcoded.", confusion: "Skills don't replace tools; skills describe how to use tools.", goal: "Build a create/edit/execute skill system." },
  s09: { focus: "Focus on DANGEROUS_PATTERNS and the approval flow.", confusion: "Permission system targets terminal commands specifically.", goal: "Build a dangerous-command approval pipeline." },
  s10: { focus: "Focus on isolated messages and shared budget.", confusion: "Child's intermediate work doesn't return to parent.", goal: "Build a context-isolated subagent delegation." },
  s11: { focus: "Focus on _deep_merge and two-file separation.", confusion: "dict.update() loses nested fields; use recursive merge.", goal: "Build YAML config + Profile isolation + migration." },
};

export function getChapterGuide(version: string, locale: string): ChapterGuide | null {
  const guides = locale === "en" ? GUIDES_EN : GUIDES_ZH;
  return guides[version] ?? null;
}
