"use client";

import { motion } from "framer-motion";

interface WhatsNewProps {
  diff: {
    newClasses: string[];
    newFunctions: string[];
    newTools: string[];
    locDelta: number;
  } | null;
}

export function WhatsNew({ diff }: WhatsNewProps) {
  if (!diff) return null;
  const { newClasses, newFunctions, newTools, locDelta } = diff;
  const hasContent =
    newClasses.length > 0 || newFunctions.length > 0 || newTools.length > 0;
  if (!hasContent) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        What's New
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {newClasses.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30"
          >
            <p className="text-[10px] font-bold uppercase text-emerald-600 dark:text-emerald-400">
              Classes
            </p>
            <div className="mt-1 space-y-0.5">
              {newClasses.map((c) => (
                <p
                  key={c}
                  className="font-mono text-xs text-emerald-700 dark:text-emerald-300"
                >
                  {c}
                </p>
              ))}
            </div>
          </motion.div>
        )}
        {newTools.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-900 dark:bg-blue-950/30"
          >
            <p className="text-[10px] font-bold uppercase text-blue-600 dark:text-blue-400">
              Tools
            </p>
            <div className="mt-1 space-y-0.5">
              {newTools.map((t) => (
                <p
                  key={t}
                  className="font-mono text-xs text-blue-700 dark:text-blue-300"
                >
                  {t}
                </p>
              ))}
            </div>
          </motion.div>
        )}
        {newFunctions.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800"
          >
            <p className="text-[10px] font-bold uppercase text-zinc-600 dark:text-zinc-400">
              Functions
            </p>
            <div className="mt-1 space-y-0.5">
              {newFunctions.map((f) => (
                <p
                  key={f}
                  className="font-mono text-xs text-zinc-700 dark:text-zinc-300"
                >
                  {f}
                </p>
              ))}
            </div>
          </motion.div>
        )}
        {locDelta !== 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col items-center justify-center rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-800"
          >
            <p className="text-[10px] font-bold uppercase text-zinc-500">
              LOC Delta
            </p>
            <p
              className={`mt-1 text-lg font-bold ${locDelta > 0 ? "text-emerald-600" : "text-red-500"}`}
            >
              {locDelta > 0 ? "+" : ""}
              {locDelta}
            </p>
          </motion.div>
        )}
      </div>
    </div>
  );
}
