"use client";

import { motion } from "framer-motion";
import { useSteppedVisualization } from "@/hooks/useSteppedVisualization";
import { StepControls } from "@/components/visualizations/shared/step-controls";
import { useLocale } from "@/lib/i18n";

const STEPS_ZH = [
  { title: "正常调用", description: "API 调用成功，循环正常运行。" },
  { title: "遇到 429", description: "被限速了。classify_error 判断为 rate_limit。" },
  { title: "退避等待", description: "jittered_backoff() 计算等待时间：指数退避 + 随机抖动。" },
  { title: "重试成功", description: "等待后重试，API 恢复正常。" },
  { title: "遇到 400 context overflow", description: "上下文太长。classify_error 判断为 context_overflow。" },
  { title: "触发压缩", description: "自动调用 compress() 压缩上下文，然后重试。" },
  { title: "遇到 401", description: "认证失败。classify_error 判断为 auth。" },
  { title: "故障转移", description: "switch_to_fallback() 切换到备用模型和凭据。" },
];

const STEPS_EN = [
  { title: "Normal Call", description: "API succeeds, loop runs normally." },
  { title: "Hit 429", description: "Rate limited. classify_error -> rate_limit." },
  { title: "Backoff Wait", description: "jittered_backoff() calculates delay." },
  { title: "Retry Success", description: "Retry after wait, API recovers." },
  { title: "Hit 400 Context Overflow", description: "Context too long. -> context_overflow." },
  { title: "Trigger Compression", description: "Auto-compress context, then retry." },
  { title: "Hit 401", description: "Auth failed. classify_error -> auth." },
  { title: "Fallback Switch", description: "switch_to_fallback() to backup model." },
];

const ERROR_TYPES = [
  { code: "429", label: "Rate Limit", action: "Backoff", color: "#f59e0b" },
  { code: "400", label: "Context Overflow", action: "Compress", color: "#ef4444" },
  { code: "401", label: "Auth Failed", action: "Fallback", color: "#8b5cf6" },
];

export default function S06ErrorRecovery() {
  const locale = useLocale();
  const steps = locale === "en" ? STEPS_EN : STEPS_ZH;
  const viz = useSteppedVisualization({ totalSteps: steps.length });
  const activeError = viz.currentStep >= 1 && viz.currentStep <= 3 ? 0 : viz.currentStep >= 4 && viz.currentStep <= 5 ? 1 : viz.currentStep >= 6 ? 2 : -1;

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-700">
      <h3 className="text-sm font-semibold">{locale === "zh" ? "错误恢复路径" : "Error Recovery Paths"}</h3>
      <div className="grid grid-cols-3 gap-3">
        {ERROR_TYPES.map((err, i) => (
          <motion.div key={err.code} animate={{ scale: activeError === i ? 1.05 : 1, opacity: activeError === i ? 1 : 0.5 }}
            className="rounded-lg border p-3 text-center" style={{ borderColor: activeError === i ? err.color : undefined }}>
            <p className="text-lg font-bold font-mono" style={{ color: err.color }}>{err.code}</p>
            <p className="text-[10px] text-zinc-500">{err.label}</p>
            <p className="mt-1 text-xs font-medium" style={{ color: err.color }}>&rarr; {err.action}</p>
          </motion.div>
        ))}
      </div>
      {viz.currentStep > 0 && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="rounded-lg bg-zinc-50 p-3 text-center dark:bg-zinc-800">
          <p className="text-xs font-mono text-zinc-600 dark:text-zinc-400">
            classify_error() &rarr; {activeError >= 0 ? ERROR_TYPES[activeError].action.toLowerCase() : "..."}
          </p>
        </motion.div>
      )}
      <StepControls currentStep={viz.currentStep} totalSteps={viz.totalSteps} isPlaying={viz.isPlaying} onReset={viz.reset} onPrev={viz.prev} onNext={viz.next} onTogglePlay={viz.toggleAutoPlay} annotations={steps} />
    </div>
  );
}
