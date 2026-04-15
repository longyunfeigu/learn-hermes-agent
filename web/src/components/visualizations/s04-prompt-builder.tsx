"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "读取 SOUL.md", description: "从 HERMES_HOME 读取人设文件，定义 agent 的身份和风格。" },
  { title: "读取 MEMORY.md", description: "读取跨会话记忆，包含用户偏好和项目背景。" },
  { title: "读取项目配置", description: "按优先级查找 HERMES.md / AGENTS.md / .cursorrules。" },
  { title: "组装 System Prompt", description: "把三个来源拼成一条完整的 system prompt。" },
  { title: "缓存", description: "缓存组装结果。整个会话内不再重新组装。" },
];

const STEPS_EN = [
  { title: "Load SOUL.md", description: "Read personality from HERMES_HOME." },
  { title: "Load MEMORY.md", description: "Read cross-session memory." },
  { title: "Load Project Config", description: "Priority: HERMES.md > AGENTS.md > .cursorrules." },
  { title: "Assemble Prompt", description: "Combine all sources into one system prompt." },
  { title: "Cache", description: "Cache result. No reassembly during session." },
];

const SOURCES = ["SOUL.md", "MEMORY.md", "HERMES.md"];

export default function S04PromptBuilder() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const viz = useSteppedVisualization({ totalSteps: steps.length });

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "提示词组装管道" : "Prompt Assembly Pipeline"}</h3>
      <div className="flex items-center justify-center gap-4">
        {SOURCES.map((src, i) => (
          <motion.div key={src} animate={{ opacity: viz.currentStep >= i ? 1 : 0.3, scale: viz.currentStep === i ? 1.1 : 1 }}
            className="rounded-lg border border-zinc-200 px-4 py-3 text-center dark:border-zinc-700">
            <p className="text-xs font-mono font-medium">{src}</p>
          </motion.div>
        ))}
      </div>
      {viz.currentStep >= 3 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mx-auto max-w-xs rounded-lg border-2 border-blue-400 bg-blue-50 p-3 text-center dark:bg-blue-950/30">
          <p className="text-xs font-bold text-blue-700 dark:text-blue-300">System Prompt</p>
          <p className="mt-1 text-[10px] text-blue-500">{SOURCES.join(" + ")} + time</p>
        </motion.div>
      )}
      {viz.currentStep >= 4 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center text-xs text-emerald-600 dark:text-emerald-400">
          {locale === "zh" ? "已缓存，整个会话复用" : "Cached for session reuse"}
        </motion.div>
      )}
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
