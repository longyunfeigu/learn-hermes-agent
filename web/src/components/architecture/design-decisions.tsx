"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useLocale } from "@/lib/i18n";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface Decision {
  title: Record<string, string>;
  description: Record<string, string>;
  alternative: Record<string, string>;
}

const DECISIONS: Record<string, Decision[]> = {
  s01: [
    {
      title: {
        zh: "为什么用同步循环而不是 async",
        en: "Why synchronous loop instead of async",
      },
      description: {
        zh: "大部分工具（文件读写、终端命令）本身是同步的，同步循环的错误处理和调试简单得多。",
        en: "Most tools are synchronous; sync loops are easier to debug.",
      },
      alternative: {
        zh: "全 async 循环——增加复杂度但允许并发工具执行",
        en: "Full async loop -- more complex but allows concurrent tools.",
      },
    },
    {
      title: {
        zh: "为什么用 OpenAI SDK 而不绑定具体 provider",
        en: "Why OpenAI SDK instead of provider-specific",
      },
      description: {
        zh: "通过 base_url 可以接入 200+ 模型提供商，切换只需改配置。",
        en: "base_url can connect 200+ providers, switch via config only.",
      },
      alternative: {
        zh: "各 provider 原生 SDK——类型更准但切换成本高",
        en: "Native provider SDKs -- better types but high switching cost.",
      },
    },
  ],
  s02: [
    {
      title: {
        zh: "为什么用自注册而不是中心配置",
        en: "Why self-registration instead of central config",
      },
      description: {
        zh: "添加工具只写一个文件，不改任何其他文件。注册表不依赖工具，避免循环导入。",
        en: "Add a tool = one file. Registry depends on nothing.",
      },
      alternative: {
        zh: "中心配置文件——可预测但每次加工具都要改",
        en: "Central config -- predictable but requires edits for each tool.",
      },
    },
  ],
  s03: [
    {
      title: {
        zh: "为什么用 SQLite 而不是文件系统",
        en: "Why SQLite instead of filesystem",
      },
      description: {
        zh: "WAL 模式支持并发读写（Gateway 多平台场景），FTS5 支持全文搜索。文件系统在并发场景下不可靠。",
        en: "WAL supports concurrent reads/writes; FTS5 enables full-text search.",
      },
      alternative: {
        zh: "JSON 文件——简单但不支持并发和搜索",
        en: "JSON files -- simple but no concurrency or search.",
      },
    },
  ],
  s04: [
    {
      title: {
        zh: "为什么缓存 system prompt",
        en: "Why cache the system prompt",
      },
      description: {
        zh: "Anthropic 的 prompt caching 要求多轮间 system prompt 不变。缓存还减少了重复的文件读取。",
        en: "Prompt caching requires stable system prompt across turns.",
      },
      alternative: {
        zh: "每轮重新组装——灵活但浪费 prompt cache",
        en: "Reassemble each turn -- flexible but wastes cache.",
      },
    },
  ],
  s05: [
    {
      title: {
        zh: "为什么用 LLM 做摘要而不是截断",
        en: "Why LLM summary instead of truncation",
      },
      description: {
        zh: "截断会丢失关键决策和进度信息。LLM 摘要能保留\"做了什么、为什么\"的核心信息。",
        en: 'Truncation loses key decisions. LLM summary preserves what and why.',
      },
      alternative: {
        zh: "简单截断——便宜但可能丢失关键上下文",
        en: "Simple truncation -- cheap but may lose critical context.",
      },
    },
  ],
  s06: [
    {
      title: {
        zh: "为什么根据错误类型走不同路径",
        en: "Why different recovery paths per error type",
      },
      description: {
        zh: "429 需要退避等待，400 context overflow 需要压缩，401 需要换凭据。一刀切的重试会浪费时间。",
        en: "429 needs backoff, 400 needs compression, 401 needs credential switch.",
      },
      alternative: {
        zh: "统一重试 3 次——简单但很多错误不是重试能解决的",
        en: "Uniform retry 3x -- simple but many errors need specific handling.",
      },
    },
  ],
};

export function DesignDecisions({ version }: { version: string }) {
  const locale = useLocale();
  const decisions = DECISIONS[version];
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!decisions || decisions.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {locale === "zh" ? "设计决策" : "Design Decisions"}
      </h3>
      {decisions.map((d, i) => (
        <div
          key={i}
          className="rounded-lg border border-zinc-200 dark:border-zinc-700"
        >
          <button
            onClick={() => setExpanded(expanded === i ? null : i)}
            className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-zinc-800 dark:text-zinc-200"
          >
            {d.title[locale] || d.title.en}
            <ChevronDown
              size={16}
              className={cn(
                "transition-transform",
                expanded === i && "rotate-180"
              )}
            />
          </button>
          <AnimatePresence>
            {expanded === i && (
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: "auto" }}
                exit={{ height: 0 }}
                className="overflow-hidden"
              >
                <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-700">
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">
                    {d.description[locale] || d.description.en}
                  </p>
                  <p className="mt-2 text-xs italic text-zinc-400 dark:text-zinc-500">
                    {locale === "zh" ? "替代方案：" : "Alternative: "}
                    {d.alternative[locale] || d.alternative.en}
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      ))}
    </div>
  );
}
