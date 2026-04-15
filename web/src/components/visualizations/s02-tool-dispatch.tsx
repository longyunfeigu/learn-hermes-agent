"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "工具注册", description: "每个工具文件被导入时，自动调用 register() 把自己登记到注册表。" },
  { title: "获取工具定义", description: "循环通过 get_definitions() 从注册表获取当前启用的工具列表，发给模型。" },
  { title: "模型选择工具", description: "模型分析用户请求后，返回 tool_calls，指定要调用的工具名和参数。" },
  { title: "注册表分发", description: "dispatch() 在注册表里查找工具名对应的 handler 函数。" },
  { title: "执行 handler", description: "handler 函数执行实际操作（终端命令、文件读写、网络请求等）。" },
  { title: "结果回写", description: "handler 返回值作为 tool 消息写回 messages，循环继续。" },
];

const STEPS_EN = [
  { title: "Tool Registration", description: "Each tool file calls register() on import." },
  { title: "Get Definitions", description: "Loop calls get_definitions() to get enabled tools." },
  { title: "Model Selects Tool", description: "Model returns tool_calls with name and args." },
  { title: "Registry Dispatch", description: "dispatch() looks up the handler by name." },
  { title: "Execute Handler", description: "Handler runs the actual operation." },
  { title: "Write Result Back", description: "Handler output written as tool message." },
];

const TOOLS = ["terminal", "read_file", "write_file", "web_search"];

export default function S02ToolDispatch() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const viz = useSteppedVisualization({ totalSteps: steps.length });

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "工具注册与分发" : "Tool Registration & Dispatch"}</h3>
      <div className="flex flex-wrap gap-2">
        {TOOLS.map((tool, i) => (
          <motion.div key={tool} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: viz.currentStep >= 0 ? 1 : 0.3, scale: 1 }} transition={{ delay: i * 0.1 }}
            className={`rounded-md border px-3 py-1.5 text-xs font-mono ${viz.currentStep >= 3 && i === 0 ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300" : "border-zinc-200 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"}`}>
            {tool}
          </motion.div>
        ))}
      </div>
      <div className="flex items-center gap-4">
        {["register()", "get_definitions()", "dispatch()", "handler()"].map((fn, i) => (
          <motion.div key={fn} className={`rounded-md px-3 py-2 text-xs font-mono transition-colors ${viz.currentStep === i ? "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300" : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"}`}
            animate={{ scale: viz.currentStep === i ? 1.05 : 1 }}>
            {fn}
          </motion.div>
        ))}
      </div>
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
