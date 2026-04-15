import type { LearningLayer } from "@/lib/constants";

const LAYER_COLORS: Record<LearningLayer, string> = {
  core: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  smart: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  gateway: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  advanced: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
};

export function LayerBadge({
  layer,
  children,
}: {
  layer: LearningLayer;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${LAYER_COLORS[layer]}`}
    >
      {children}
    </span>
  );
}
