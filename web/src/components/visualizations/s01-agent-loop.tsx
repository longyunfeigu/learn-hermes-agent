"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useSvgPalette } from "@/hooks/useDarkMode";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "初始状态", description: "用户发了一条消息，messages 列表里只有一条 user 消息。" },
  { title: "调用模型 API", description: "把 system prompt + messages 发给模型，等待回复。" },
  { title: "模型返回 tool_calls", description: "模型决定调用 terminal 工具，返回 assistant 消息。" },
  { title: "执行工具", description: "系统执行 terminal 命令，得到输出结果。" },
  { title: "结果回写", description: "工具输出作为 tool 角色的消息写回 messages。" },
  { title: "再次调用模型", description: "带着工具结果再次发给模型，模型看到结果后决定下一步。" },
  { title: "模型返回文本", description: "没有 tool_calls 了，循环结束，返回最终回复给用户。" },
];

const STEPS_EN = [
  { title: "Initial State", description: "User sent a message. messages[] has one user message." },
  { title: "Call Model API", description: "Send system prompt + messages to the model." },
  { title: "Model Returns tool_calls", description: "Model decides to call terminal tool." },
  { title: "Execute Tool", description: "System runs the terminal command." },
  { title: "Write Results Back", description: "Tool output appended as tool-role message." },
  { title: "Call Model Again", description: "Send updated messages with tool results." },
  { title: "Model Returns Text", description: "No tool_calls. Loop ends. Return response." },
];

const MESSAGES_PER_STEP = [
  [{ role: "user", color: "#3b82f6" }],
  [{ role: "user", color: "#3b82f6" }],
  [{ role: "user", color: "#3b82f6" }, { role: "assistant+tool_calls", color: "#10b981" }],
  [{ role: "user", color: "#3b82f6" }, { role: "assistant+tool_calls", color: "#10b981" }],
  [{ role: "user", color: "#3b82f6" }, { role: "assistant+tool_calls", color: "#10b981" }, { role: "tool", color: "#f59e0b" }],
  [{ role: "user", color: "#3b82f6" }, { role: "assistant+tool_calls", color: "#10b981" }, { role: "tool", color: "#f59e0b" }],
  [{ role: "user", color: "#3b82f6" }, { role: "assistant+tool_calls", color: "#10b981" }, { role: "tool", color: "#f59e0b" }, { role: "assistant", color: "#8b5cf6" }],
];

export default function S01AgentLoop() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const palette = useSvgPalette();
  const viz = useSteppedVisualization({ totalSteps: steps.length });
  const msgs = MESSAGES_PER_STEP[viz.currentStep] || [];

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "Agent 循环可视化" : "Agent Loop Visualization"}</h3>
      <div className="flex items-start gap-6">
        {/* Messages list */}
        <div className="flex-1 space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">messages[]</p>
          <div className="space-y-1.5">
            {msgs.map((m, i) => (
              <motion.div key={i} initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }} className="flex items-center gap-2 rounded-md px-3 py-2" style={{ backgroundColor: m.color + "15", borderLeft: `3px solid ${m.color}` }}>
                <span className="text-xs font-mono font-medium" style={{ color: m.color }}>{m.role}</span>
              </motion.div>
            ))}
            {msgs.length === 0 && <p className="text-xs text-zinc-400 italic">empty</p>}
          </div>
        </div>
        {/* Flow indicator */}
        <div className="w-32 shrink-0">
          <svg width={120} height={280} viewBox="0 0 120 280">
            {["API Call", "tool_calls?", "Execute", "Write Back"].map((label, i) => {
              const y = 30 + i * 70;
              const active = viz.currentStep >= i + 1 && viz.currentStep <= i + 5;
              return (
                <g key={i}>
                  <rect x={10} y={y} width={100} height={30} rx={6} fill={active ? palette.activeNodeFill : palette.nodeFill} stroke={active ? palette.activeNodeStroke : palette.nodeStroke} strokeWidth={1.5} />
                  <text x={60} y={y + 19} textAnchor="middle" fill={active ? palette.activeNodeText : palette.nodeText} fontSize={10}>{label}</text>
                  {i < 3 && <line x1={60} y1={y + 30} x2={60} y2={y + 70} stroke={palette.edgeStroke} strokeWidth={1} />}
                </g>
              );
            })}
          </svg>
        </div>
      </div>
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
