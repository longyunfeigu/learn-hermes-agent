"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "创建会话", description: "create_session() 在 sessions 表插入一行，返回 session_id。" },
  { title: "用户输入", description: "用户消息追加到 messages 并通过 add_message() 写入 SQLite。" },
  { title: "模型回复", description: "assistant 消息（含 tool_calls）也实时写入 SQLite。" },
  { title: "工具结果", description: "tool 消息写入 SQLite。每条消息都实时持久化。" },
  { title: "重启恢复", description: "下次启动时，get_session_messages() 从 SQLite 读出历史，传给循环继续。" },
];

const STEPS_EN = [
  { title: "Create Session", description: "create_session() inserts a row, returns session_id." },
  { title: "User Input", description: "User message appended and written to SQLite." },
  { title: "Model Reply", description: "Assistant message written to SQLite in real-time." },
  { title: "Tool Result", description: "Tool message written. Every message persisted." },
  { title: "Restart Recovery", description: "Next startup loads history from SQLite." },
];

export default function S03SessionStore() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const viz = useSteppedVisualization({ totalSteps: steps.length });
  const dbRows = Math.min(viz.currentStep + 1, 4);

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "SQLite 持久化" : "SQLite Persistence"}</h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">messages[]</p>
          <div className="mt-2 space-y-1">
            {Array.from({ length: Math.min(viz.currentStep, 3) + 1 }).map((_, i) => (
              <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded border border-zinc-200 px-2 py-1 text-[10px] font-mono dark:border-zinc-700">
                {["user", "assistant", "tool", "assistant"][i]}
              </motion.div>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider text-amber-500">SQLite</p>
          <div className="mt-2 space-y-1">
            {Array.from({ length: dbRows }).map((_, i) => (
              <motion.div key={i} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 }}
                className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-mono dark:border-amber-800 dark:bg-amber-950/30">
                row {i + 1}
              </motion.div>
            ))}
            {viz.currentStep === 4 && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-2 rounded bg-emerald-50 px-2 py-1 text-[10px] text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                &larr; {locale === "zh" ? "重启后从这里恢复" : "Restored on restart"}
              </motion.div>
            )}
          </div>
        </div>
      </div>
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
