export interface FlowNode {
  id: string;
  label: string;
  type: "start" | "process" | "decision" | "subprocess" | "end";
  x: number;
  y: number;
}

export interface FlowEdge {
  from: string;
  to: string;
  label?: string;
}

export interface FlowDefinition {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

const W = 600;
const COL_CENTER = W / 2;
const COL_LEFT = W / 4;
const COL_RIGHT = (W * 3) / 4;

export const EXECUTION_FLOWS: Record<string, FlowDefinition> = {
  s01: {
    nodes: [
      { id: "input", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 110 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_CENTER, y: 200 },
      { id: "exec", label: "Execute Tools", type: "subprocess", x: COL_LEFT, y: 300 },
      { id: "append", label: "Write Results", type: "process", x: COL_LEFT, y: 380 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 300 },
    ],
    edges: [
      { from: "input", to: "api" },
      { from: "api", to: "check" },
      { from: "check", to: "exec", label: "yes" },
      { from: "exec", to: "append" },
      { from: "append", to: "api" },
      { from: "check", to: "end", label: "no" },
    ],
  },
  s02: {
    nodes: [
      { id: "input", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 110 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_CENTER, y: 200 },
      { id: "registry", label: "Registry Dispatch", type: "subprocess", x: COL_LEFT, y: 300 },
      { id: "handler", label: "Tool Handler", type: "process", x: COL_LEFT, y: 380 },
      { id: "append", label: "Write Results", type: "process", x: COL_LEFT, y: 460 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 300 },
    ],
    edges: [
      { from: "input", to: "api" },
      { from: "api", to: "check" },
      { from: "check", to: "registry", label: "yes" },
      { from: "registry", to: "handler" },
      { from: "handler", to: "append" },
      { from: "append", to: "api" },
      { from: "check", to: "end", label: "no" },
    ],
  },
  s03: {
    nodes: [
      { id: "input", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "load", label: "Load History", type: "process", x: COL_CENTER, y: 110 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 190 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_CENTER, y: 280 },
      { id: "exec", label: "Execute Tools", type: "subprocess", x: COL_LEFT, y: 370 },
      { id: "save", label: "Save to SQLite", type: "process", x: COL_LEFT, y: 450 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 370 },
      { id: "persist", label: "Save to SQLite", type: "process", x: COL_RIGHT, y: 450 },
    ],
    edges: [
      { from: "input", to: "load" },
      { from: "load", to: "api" },
      { from: "api", to: "check" },
      { from: "check", to: "exec", label: "yes" },
      { from: "exec", to: "save" },
      { from: "save", to: "api" },
      { from: "check", to: "end", label: "no" },
      { from: "end", to: "persist" },
    ],
  },
  s04: {
    nodes: [
      { id: "soul", label: "Load SOUL.md", type: "start", x: COL_LEFT, y: 30 },
      { id: "memory", label: "Load MEMORY.md", type: "process", x: COL_CENTER, y: 30 },
      { id: "project", label: "Load Project Config", type: "process", x: COL_RIGHT, y: 30 },
      { id: "assemble", label: "Build System Prompt", type: "process", x: COL_CENTER, y: 120 },
      { id: "cache", label: "Cache Prompt", type: "process", x: COL_CENTER, y: 200 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 280 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_CENTER, y: 370 },
      { id: "exec", label: "Execute Tools", type: "subprocess", x: COL_LEFT, y: 460 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 460 },
    ],
    edges: [
      { from: "soul", to: "assemble" },
      { from: "memory", to: "assemble" },
      { from: "project", to: "assemble" },
      { from: "assemble", to: "cache" },
      { from: "cache", to: "api" },
      { from: "api", to: "check" },
      { from: "check", to: "exec", label: "yes" },
      { from: "exec", to: "api" },
      { from: "check", to: "end", label: "no" },
    ],
  },
  s05: {
    nodes: [
      { id: "input", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "estimate", label: "Estimate Tokens", type: "process", x: COL_CENTER, y: 110 },
      { id: "threshold", label: "Over threshold?", type: "decision", x: COL_CENTER, y: 200 },
      { id: "compress", label: "Compress", type: "subprocess", x: COL_LEFT, y: 300 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 390 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_CENTER, y: 470 },
      { id: "exec", label: "Execute Tools", type: "subprocess", x: COL_LEFT, y: 560 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 560 },
    ],
    edges: [
      { from: "input", to: "estimate" },
      { from: "estimate", to: "threshold" },
      { from: "threshold", to: "compress", label: "yes" },
      { from: "threshold", to: "api", label: "no" },
      { from: "compress", to: "api" },
      { from: "api", to: "check" },
      { from: "check", to: "exec", label: "yes" },
      { from: "exec", to: "estimate" },
      { from: "check", to: "end", label: "no" },
    ],
  },
  s06: {
    nodes: [
      { id: "input", label: "User Input", type: "start", x: COL_CENTER, y: 30 },
      { id: "api", label: "Call Model API", type: "process", x: COL_CENTER, y: 110 },
      { id: "error", label: "API Error?", type: "decision", x: COL_CENTER, y: 200 },
      { id: "classify", label: "Classify Error", type: "process", x: COL_LEFT, y: 300 },
      { id: "retry", label: "Retry / Fallback", type: "subprocess", x: COL_LEFT, y: 380 },
      { id: "check", label: "Has tool_calls?", type: "decision", x: COL_RIGHT, y: 300 },
      { id: "exec", label: "Execute Tools", type: "subprocess", x: COL_RIGHT, y: 400 },
      { id: "end", label: "Return Response", type: "end", x: COL_RIGHT, y: 500 },
    ],
    edges: [
      { from: "input", to: "api" },
      { from: "api", to: "error" },
      { from: "error", to: "classify", label: "yes" },
      { from: "classify", to: "retry" },
      { from: "retry", to: "api" },
      { from: "error", to: "check", label: "no" },
      { from: "check", to: "exec", label: "yes" },
      { from: "exec", to: "api" },
      { from: "check", to: "end", label: "no" },
    ],
  },
};

// Generic flows for chapters without custom visualizations
export const GENERIC_FLOWS: Record<string, FlowDefinition> = {
  "s07-s11": {
    nodes: [
      { id: "loop", label: "Agent Loop", type: "start", x: COL_CENTER, y: 30 },
      { id: "smart", label: "Intelligence Layer", type: "process", x: COL_CENTER, y: 120 },
      { id: "tools", label: "Tool Execution", type: "subprocess", x: COL_CENTER, y: 210 },
      { id: "persist", label: "Persist State", type: "process", x: COL_CENTER, y: 300 },
    ],
    edges: [
      { from: "loop", to: "smart" },
      { from: "smart", to: "tools" },
      { from: "tools", to: "persist" },
      { from: "persist", to: "loop" },
    ],
  },
  "s12-s15": {
    nodes: [
      { id: "platform", label: "Platform Message", type: "start", x: COL_LEFT, y: 30 },
      { id: "adapter", label: "Platform Adapter", type: "process", x: COL_LEFT, y: 120 },
      { id: "gateway", label: "Gateway Router", type: "process", x: COL_CENTER, y: 210 },
      { id: "agent", label: "Agent Loop", type: "subprocess", x: COL_CENTER, y: 300 },
      { id: "reply", label: "Reply via Adapter", type: "end", x: COL_RIGHT, y: 210 },
    ],
    edges: [
      { from: "platform", to: "adapter" },
      { from: "adapter", to: "gateway" },
      { from: "gateway", to: "agent" },
      { from: "agent", to: "reply" },
    ],
  },
  "s16-s20": {
    nodes: [
      { id: "core", label: "Core Agent", type: "start", x: COL_CENTER, y: 30 },
      { id: "mcp", label: "MCP / External", type: "subprocess", x: COL_LEFT, y: 120 },
      { id: "browser", label: "Browser / Voice", type: "subprocess", x: COL_RIGHT, y: 120 },
      { id: "full", label: "Full System", type: "end", x: COL_CENTER, y: 210 },
    ],
    edges: [
      { from: "core", to: "mcp" },
      { from: "core", to: "browser" },
      { from: "mcp", to: "full" },
      { from: "browser", to: "full" },
    ],
  },
};

export function getFlowForVersion(version: string): FlowDefinition | null {
  if (EXECUTION_FLOWS[version]) return EXECUTION_FLOWS[version];
  const num = parseInt(version.replace("s", ""), 10);
  if (num >= 7 && num <= 11) return GENERIC_FLOWS["s07-s11"];
  if (num >= 12 && num <= 15) return GENERIC_FLOWS["s12-s15"];
  if (num >= 16 && num <= 20) return GENERIC_FLOWS["s16-s20"];
  return null;
}
