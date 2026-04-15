export const VERSION_ORDER = [
  "s00", "s01", "s02", "s03", "s04", "s05", "s06",
  "s07", "s08", "s09", "s10", "s11",
  "s12", "s13", "s14", "s15",
  "s16", "s17", "s18", "s19", "s20",
] as const;

// s00 is the architecture overview, not a hands-on chapter.
// LEARNING_PATH starts from s01.
export const LEARNING_PATH = VERSION_ORDER.slice(1);

export type VersionId = (typeof VERSION_ORDER)[number];
export type LearningLayer = "core" | "smart" | "gateway" | "advanced";

export const VERSION_META: Record<
  string,
  {
    title: string;
    subtitle: string;
    keyInsight: string;
    layer: LearningLayer;
    prevVersion: string | null;
  }
> = {
  s00: {
    title: "Architecture Overview",
    subtitle: "架构总览",
    keyInsight: "Hermes Agent 的核心是一个同步对话循环 + 自注册工具系统 + SQLite 持久化，通过 Gateway 接入多个平台。",
    layer: "core",
    prevVersion: null,
  },
  s01: {
    title: "The Agent Loop",
    subtitle: "同步对话循环",
    keyInsight: "Agent 就是一个循环：发给模型 → 处理工具调用 → 结果回写 → 继续。",
    layer: "core",
    prevVersion: "s00",
  },
  s02: {
    title: "Tool System",
    subtitle: "自注册工具系统",
    keyInsight: "添加新工具只需要写一个文件，不需要修改任何其他文件。",
    layer: "core",
    prevVersion: "s01",
  },
  s03: {
    title: "Session Store",
    subtitle: "SQLite 持久化",
    keyInsight: "SQLite + WAL + FTS5 让对话跨重启存活，支持并发读写和全文搜索。",
    layer: "core",
    prevVersion: "s02",
  },
  s04: {
    title: "Prompt Builder",
    subtitle: "系统提示词组装",
    keyInsight: "System prompt 不是一整段静态文本，而是从人设、记忆、配置多个来源动态组装的。",
    layer: "core",
    prevVersion: "s03",
  },
  s05: {
    title: "Context Compression",
    subtitle: "上下文压缩",
    keyInsight: "压缩不是删除历史，而是用摘要替代原文，让 agent 能继续工作。",
    layer: "core",
    prevVersion: "s04",
  },
  s06: {
    title: "Error Recovery",
    subtitle: "错误恢复与故障转移",
    keyInsight: "大部分 API 错误不是真正的任务失败，而是切换路径的信号。",
    layer: "core",
    prevVersion: "s05",
  },
  s07: {
    title: "Memory System",
    subtitle: "跨会话持久知识",
    keyInsight: "记忆不是聊天记录，而是 agent 主动筛选出的跨会话精华信息。",
    layer: "smart",
    prevVersion: "s06",
  },
  s08: {
    title: "Skill System",
    subtitle: "Agent 管理的技能",
    keyInsight: "技能不是硬编码的工具，而是 agent 运行时可以创建、编辑、执行的能力文件。",
    layer: "smart",
    prevVersion: "s07",
  },
  s09: {
    title: "Permission System",
    subtitle: "危险命令审批",
    keyInsight: "在所有工具里终端最危险，所以权限系统专门针对终端命令做模式匹配。",
    layer: "smart",
    prevVersion: "s08",
  },
  s10: {
    title: "Subagent Delegation",
    subtitle: "子 Agent 委派",
    keyInsight: "子 agent 就是一个拥有独立 messages 的临时实例，完成后只返回结果文本。",
    layer: "smart",
    prevVersion: "s09",
  },
  s11: {
    title: "Configuration System",
    subtitle: "配置系统",
    keyInsight: "config.yaml 放行为配置，.env 放秘密信息，Profile 隔离整个运行上下文。",
    layer: "smart",
    prevVersion: "s10",
  },
  s12: {
    title: "Gateway Architecture",
    subtitle: "多平台消息分发",
    keyInsight: "Gateway 和 CLI 的区别只在入口和出口，核心循环完全一样。",
    layer: "gateway",
    prevVersion: "s11",
  },
  s13: {
    title: "Platform Adapters",
    subtitle: "平台适配器模式",
    keyInsight: "所有适配器遵循同一个基类接口，添加新平台只需要写一个新适配器。",
    layer: "gateway",
    prevVersion: "s12",
  },
  s14: {
    title: "Terminal Backends",
    subtitle: "执行环境抽象",
    keyInsight: "工具只管发命令，不管命令在本地、Docker 还是云端跑。",
    layer: "gateway",
    prevVersion: "s13",
  },
  s15: {
    title: "Cron Scheduler",
    subtitle: "定时任务",
    keyInsight: "定时调度只是给同一个 agent 循环多了一个时间触发器。",
    layer: "gateway",
    prevVersion: "s14",
  },
  s16: {
    title: "MCP Integration",
    subtitle: "外部能力总线",
    keyInsight: "MCP 工具接入后在模型看来和内置工具完全一样，模型不需要知道区别。",
    layer: "advanced",
    prevVersion: "s15",
  },
  s17: {
    title: "Browser Automation",
    subtitle: "浏览器自动化",
    keyInsight: "浏览器是 agent 操作网页世界的眼睛和手。",
    layer: "advanced",
    prevVersion: "s16",
  },
  s18: {
    title: "Voice & Vision",
    subtitle: "语音与视觉",
    keyInsight: "多模态能力让 agent 能听、能说、能看图。",
    layer: "advanced",
    prevVersion: "s17",
  },
  s19: {
    title: "CLI Interface",
    subtitle: "交互式终端界面",
    keyInsight: "CLI 是开发者和 agent 最直接的交互面。",
    layer: "advanced",
    prevVersion: "s18",
  },
  s20: {
    title: "Full System",
    subtitle: "完整系统集成",
    keyInsight: "所有机制组装在一起，就是一个完整的 Hermes Agent。",
    layer: "advanced",
    prevVersion: "s19",
  },
};

export const LAYERS = [
  {
    id: "core" as const,
    label: "Core Single-Agent",
    color: "#2563EB",
    versions: ["s00", "s01", "s02", "s03", "s04", "s05", "s06"],
  },
  {
    id: "smart" as const,
    label: "Intelligence & Safety",
    color: "#059669",
    versions: ["s07", "s08", "s09", "s10", "s11"],
  },
  {
    id: "gateway" as const,
    label: "Multi-Platform",
    color: "#D97706",
    versions: ["s12", "s13", "s14", "s15"],
  },
  {
    id: "advanced" as const,
    label: "Advanced Capabilities",
    color: "#DC2626",
    versions: ["s16", "s17", "s18", "s19", "s20"],
  },
] as const;
