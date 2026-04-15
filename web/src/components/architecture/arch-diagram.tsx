"use client";

import { motion } from "framer-motion";
import { getArchitectureBlueprint } from "@/data/architecture-blueprints";
import { useLocale } from "@/lib/i18n";
import { pickDiagramText } from "@/lib/diagram-localization";

const SLICE_COLORS: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  mainline: {
    bg: "bg-blue-50 dark:bg-blue-950/30",
    border: "border-blue-200 dark:border-blue-800",
    text: "text-blue-700 dark:text-blue-300",
  },
  control: {
    bg: "bg-emerald-50 dark:bg-emerald-950/30",
    border: "border-emerald-200 dark:border-emerald-800",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  state: {
    bg: "bg-amber-50 dark:bg-amber-950/30",
    border: "border-amber-200 dark:border-amber-800",
    text: "text-amber-700 dark:text-amber-300",
  },
  lanes: {
    bg: "bg-purple-50 dark:bg-purple-950/30",
    border: "border-purple-200 dark:border-purple-800",
    text: "text-purple-700 dark:text-purple-300",
  },
};

const SLICE_LABELS: Record<string, Record<string, string>> = {
  mainline: { zh: "主线", en: "Mainline" },
  control: { zh: "控制", en: "Control" },
  state: { zh: "状态", en: "State" },
  lanes: { zh: "侧车道", en: "Lanes" },
};

export function ArchDiagram({ version }: { version: string }) {
  const locale = useLocale();
  const bp = getArchitectureBlueprint(version);

  if (!bp) {
    return (
      <div className="rounded-lg border border-zinc-200 p-8 text-center text-sm text-zinc-400 dark:border-zinc-700">
        No architecture blueprint for this chapter yet.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        {pickDiagramText(bp.summary, locale)}
      </p>

      {/* Slices */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {(Object.entries(bp.slices) as [string, any[]][]).map(
          ([sliceId, items]) => {
            const colors = SLICE_COLORS[sliceId] || SLICE_COLORS.mainline;
            const label = SLICE_LABELS[sliceId]?.[locale] || sliceId;
            return (
              <motion.div
                key={sliceId}
                className={`rounded-lg border p-3 ${colors.bg} ${colors.border}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <p
                  className={`text-[10px] font-bold uppercase tracking-wider ${colors.text}`}
                >
                  {label}
                </p>
                <div className="mt-2 space-y-1">
                  {items.map((item: any, i: number) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className={`text-xs ${colors.text}`}>
                        {pickDiagramText(item.name, locale)}
                      </span>
                      {item.fresh && (
                        <span className="rounded-full bg-blue-500 px-1.5 py-0.5 text-[9px] font-bold text-white">
                          NEW
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </motion.div>
            );
          }
        )}
      </div>

      {/* Handoff */}
      {bp.handoff.length > 0 && (
        <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
          <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
            Handoff
          </p>
          <div className="mt-2 space-y-1">
            {bp.handoff.map((step, i) => (
              <p
                key={i}
                className="text-xs text-zinc-600 dark:text-zinc-400"
              >
                {pickDiagramText(step, locale)}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
