"use client";

import { lazy, Suspense } from "react";
import { isGenericOverviewVersion } from "@/lib/session-assets";

const visualizations: Record<
  string,
  React.LazyExoticComponent<React.ComponentType>
> = {
  s01: lazy(() => import("./s01-agent-loop")),
  s02: lazy(() => import("./s02-tool-dispatch")),
  s03: lazy(() => import("./s03-session-store")),
  s04: lazy(() => import("./s04-prompt-builder")),
  s05: lazy(() => import("./s05-context-compression")),
  s06: lazy(() => import("./s06-error-recovery")),
};

export function SessionVisualization({ version }: { version: string }) {
  if (isGenericOverviewVersion(version)) return null;

  const Component = visualizations[version];
  if (!Component) return null;

  return (
    <Suspense
      fallback={
        <div className="min-h-[400px] animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-800" />
      }
    >
      <div className="min-h-[400px]">
        <Component />
      </div>
    </Suspense>
  );
}
