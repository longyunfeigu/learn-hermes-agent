type SupportedLocale = "zh" | "en";

const FLOW_LABELS: Record<string, Record<SupportedLocale, string>> = {
  "User Input": { zh: "用户输入", en: "User Input" },
  "Build System Prompt": { zh: "组装 System Prompt", en: "Build System Prompt" },
  "Call Model API": { zh: "调用模型 API", en: "Call Model API" },
  "Has tool_calls?": { zh: "有 tool_calls?", en: "Has tool_calls?" },
  "Execute Tools": { zh: "执行工具", en: "Execute Tools" },
  "Write Results": { zh: "写回结果", en: "Write Results" },
  "Return Response": { zh: "返回回复", en: "Return Response" },
  "tool_use": { zh: "有工具调用", en: "tool_use" },
  "end_turn": { zh: "结束", en: "end_turn" },
  "Register Tool": { zh: "注册工具", en: "Register Tool" },
  "Dispatch": { zh: "分发执行", en: "Dispatch" },
  "Save to SQLite": { zh: "存入 SQLite", en: "Save to SQLite" },
  "Load History": { zh: "加载历史", en: "Load History" },
  "Load Sources": { zh: "加载来源", en: "Load Sources" },
  "Cache Prompt": { zh: "缓存 Prompt", en: "Cache Prompt" },
  "Estimate Tokens": { zh: "估算 Token", en: "Estimate Tokens" },
  "Compress": { zh: "压缩", en: "Compress" },
  "Over threshold?": { zh: "超过阈值?", en: "Over threshold?" },
  "Classify Error": { zh: "分类错误", en: "Classify Error" },
  "Retry / Fallback": { zh: "重试 / 转移", en: "Retry / Fallback" },
  "API Error?": { zh: "API 出错?", en: "API Error?" },
  "yes": { zh: "是", en: "yes" },
  "no": { zh: "否", en: "no" },
};

export function translateFlowText(text: string, locale: string): string {
  const loc = (locale === "en" ? "en" : "zh") as SupportedLocale;
  return FLOW_LABELS[text]?.[loc] ?? text;
}

export function pickDiagramText(obj: Record<string, string>, locale: string): string {
  return obj[locale] ?? obj["zh"] ?? obj["en"] ?? "";
}
