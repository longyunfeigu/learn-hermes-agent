"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "消息增长", description: "随着工具调用，messages 列表不断增长。" },
  { title: "估算 Token", description: "estimate_tokens() 粗略计算当前上下文大小。" },
  { title: "超过阈值", description: "Token 数超过 COMPRESSION_THRESHOLD，触发压缩。" },
  { title: "裁剪旧输出", description: "保留最近 3 条工具输出，旧的替换为占位符。" },
  { title: "划分边界", description: "保护头部 + 保护尾部，中间部分待压缩。" },
  { title: "LLM 摘要", description: "中间部分交给辅助 LLM 做摘要。" },
  { title: "替换完成", description: "[CONTEXT COMPACTION] 消息替代原始中间部分，循环继续。" },
];

const STEPS_EN = [
  { title: "Messages Grow", description: "Tool calls keep growing the messages list." },
  { title: "Estimate Tokens", description: "estimate_tokens() calculates context size." },
  { title: "Over Threshold", description: "Exceeds COMPRESSION_THRESHOLD, triggers compression." },
  { title: "Prune Old Outputs", description: "Keep recent 3 tool outputs, replace rest." },
  { title: "Find Boundaries", description: "Protect head + tail, middle to compress." },
  { title: "LLM Summary", description: "Middle sent to auxiliary LLM for summary." },
  { title: "Replacement Done", description: "[CONTEXT COMPACTION] replaces middle. Loop continues." },
];

export default function S05ContextCompression() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const viz = useSteppedVisualization({ totalSteps: steps.length });
  const msgCount = viz.currentStep < 3 ? 8 + viz.currentStep * 3 : (viz.currentStep >= 6 ? 6 : 8);

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "上下文压缩" : "Context Compression"}</h3>
      <div className="flex items-end gap-1">
        {Array.from({ length: msgCount }).map((_, i) => {
          const isHead = i < 3;
          const isTail = i >= msgCount - 3;
          const isMiddle = !isHead && !isTail;
          const compressed = viz.currentStep >= 6 && isMiddle;
          return (
            <motion.div key={i} animate={{ height: compressed ? 8 : 24 + Math.random() * 16, opacity: viz.currentStep >= 3 && isMiddle && viz.currentStep < 6 ? 0.4 : 1 }}
              className={`w-4 rounded-sm ${isHead ? "bg-blue-400" : isTail ? "bg-emerald-400" : compressed ? "bg-purple-400" : "bg-zinc-300 dark:bg-zinc-600"}`}
              style={{ height: 24 }} />
          );
        })}
      </div>
      <div className="flex gap-3 text-[10px]">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-blue-400" /> Head</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-zinc-300" /> Middle</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-emerald-400" /> Tail</span>
        {viz.currentStep >= 6 && <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-sm bg-purple-400" /> Summary</span>}
      </div>
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
