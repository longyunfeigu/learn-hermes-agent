"use client";

import { DocRenderer } from "@/components/docs/doc-renderer";
import { SourceViewer } from "@/components/code/source-viewer";
import { ExecutionFlow } from "@/components/architecture/execution-flow";
import { ArchDiagram } from "@/components/architecture/arch-diagram";
import { DesignDecisions } from "@/components/architecture/design-decisions";
import { WhatsNew } from "@/components/diff/whats-new";
import { SessionVisualization } from "@/components/visualizations";
import { Card } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { useLocale, useTranslations } from "@/lib/i18n";

interface VersionDetailClientProps {
  version: string;
  source: string | null;
  filename: string | null;
  diff: { newClasses: string[]; newFunctions: string[]; newTools: string[]; locDelta: number } | null;
  guideData: { focus: string; confusion: string; goal: string } | null;
  bridgeDocs: { slug: string; title: string }[];
  locale: string;
}

export function VersionDetailClient({
  version,
  source,
  filename,
  diff,
  guideData,
  bridgeDocs,
  locale: serverLocale,
}: VersionDetailClientProps) {
  const t = useTranslations("version");
  const locale = useLocale() || serverLocale;

  const tabs = [
    { id: "learn", label: t("tab_learn") },
    ...(source && filename ? [{ id: "code", label: t("tab_code") }] : []),
    { id: "deep-dive", label: t("tab_deep_dive") },
  ];

  return (
    <Tabs tabs={tabs} defaultTab="learn">
      {(activeTab) => (
        <>
          {activeTab === "learn" && <DocRenderer version={version} />}

          {activeTab === "code" && source && filename && (
            <SourceViewer source={source} filename={filename} />
          )}

          {activeTab === "deep-dive" && (
            <div className="space-y-8">
              <SessionVisualization version={version} />

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <section className="space-y-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    {locale === "zh" ? "执行流程" : "Execution Flow"}
                  </h3>
                  <ExecutionFlow version={version} />
                </section>
                <section className="space-y-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    {locale === "zh" ? "架构" : "Architecture"}
                  </h3>
                  <ArchDiagram version={version} />
                </section>
              </div>

              {diff && <WhatsNew diff={diff} />}
              <DesignDecisions version={version} />

              {guideData && (
                <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <Card className="border-emerald-200/70 bg-gradient-to-br from-emerald-50 via-white to-emerald-100/60 p-5 dark:border-emerald-900/70 dark:from-emerald-950/40 dark:via-zinc-950 dark:to-zinc-900">
                    <p className="text-xs uppercase tracking-widest text-emerald-500/80 dark:text-emerald-300/70">{locale === "zh" ? "先盯住" : "Focus"}</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">{guideData.focus}</p>
                  </Card>
                  <Card className="border-amber-200/70 bg-gradient-to-br from-amber-50 via-white to-amber-100/70 p-5 dark:border-amber-900/70 dark:from-amber-950/30 dark:via-zinc-950 dark:to-zinc-900">
                    <p className="text-xs uppercase tracking-widest text-amber-500/80 dark:text-amber-300/70">{locale === "zh" ? "最容易混" : "Confusion"}</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">{guideData.confusion}</p>
                  </Card>
                  <Card className="border-sky-200/70 bg-gradient-to-br from-sky-50 via-white to-sky-100/60 p-5 dark:border-sky-900/70 dark:from-sky-950/30 dark:via-zinc-950 dark:to-zinc-900">
                    <p className="text-xs uppercase tracking-widest text-sky-500/80 dark:text-sky-300/70">{locale === "zh" ? "学完要会" : "Goal"}</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">{guideData.goal}</p>
                  </Card>
                </section>
              )}
            </div>
          )}
        </>
      )}
    </Tabs>
  );
}
