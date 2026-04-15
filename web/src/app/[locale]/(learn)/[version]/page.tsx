import Link from "next/link";
import { VERSION_ORDER, VERSION_META, LAYERS } from "@/lib/constants";
import { LayerBadge } from "@/components/ui/badge";
import { VersionDetailClient } from "./client";
import { getTranslations } from "@/lib/i18n-server";
import { getBridgeDocDescriptors } from "@/lib/bridge-docs";
import { getChapterGuide } from "@/lib/chapter-guides";
import versionsData from "@/data/generated/versions.json";

export function generateStaticParams() {
  return VERSION_ORDER.map((version) => ({ version }));
}

export default async function VersionPage({
  params,
}: {
  params: Promise<{ locale: string; version: string }>;
}) {
  const { locale, version } = await params;

  const meta = VERSION_META[version];
  if (!meta) {
    return (
      <div className="py-20 text-center">
        <h1 className="text-2xl font-bold">Chapter not found</h1>
        <p className="mt-2 text-zinc-500">{version}</p>
      </div>
    );
  }

  const t = getTranslations(locale, "version");
  const tSession = getTranslations(locale, "sessions");
  const tLayer = getTranslations(locale, "layer_labels");
  const layer = LAYERS.find((l) => l.id === meta.layer);
  const guide = getChapterGuide(version, locale);

  const typedVersions = versionsData as { versions: Array<{ id: string; source: string; filename: string; loc: number; tools: string[]; classes: string[]; functions: string[] }> };
  const versionData = typedVersions.versions.find((v) => v.id === version);

  // Compute diff from previous version
  const pathIndex = VERSION_ORDER.indexOf(version as (typeof VERSION_ORDER)[number]);
  const prevVersionId = pathIndex > 0 ? VERSION_ORDER[pathIndex - 1] : null;
  const prevData = prevVersionId ? typedVersions.versions.find((v) => v.id === prevVersionId) : null;

  const diff = versionData && prevData ? {
    newClasses: versionData.classes.filter((c) => !prevData.classes.includes(c)),
    newFunctions: versionData.functions.filter((f) => !prevData.functions.includes(f)),
    newTools: versionData.tools.filter((t) => !prevData.tools.includes(t)),
    locDelta: versionData.loc - prevData.loc,
  } : null;

  const bridgeDocs = getBridgeDocDescriptors(version).map((d) => ({
    slug: d.slug,
    title: d.title[locale as "zh" | "en"] || d.title.zh,
  }));

  const prevVersion = pathIndex > 0 ? VERSION_ORDER[pathIndex - 1] : null;
  const nextVersion = pathIndex < VERSION_ORDER.length - 1 ? VERSION_ORDER[pathIndex + 1] : null;

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-lg bg-zinc-100 px-3 py-1 font-mono text-lg font-bold dark:bg-zinc-800">{version}</span>
          <h1 className="text-2xl font-bold sm:text-3xl">{tSession(version) || meta.title}</h1>
          {layer && <LayerBadge layer={meta.layer}>{tLayer(layer.id)}</LayerBadge>}
        </div>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {meta.subtitle}
          {versionData && (
            <>
              <span className="mx-2 text-zinc-300 dark:text-zinc-600">|</span>
              <span className="font-mono">{versionData.loc} LOC</span>
              <span className="mx-2 text-zinc-300 dark:text-zinc-600">|</span>
              <span>{versionData.tools.length} tools</span>
            </>
          )}
        </p>
        {meta.keyInsight && (
          <blockquote className="border-l-4 border-zinc-300 pl-4 text-sm italic text-zinc-500 dark:border-zinc-600 dark:text-zinc-400">{meta.keyInsight}</blockquote>
        )}
      </header>

      <VersionDetailClient
        version={version}
        source={versionData?.source ?? null}
        filename={versionData?.filename ?? null}
        diff={diff}
        guideData={guide}
        bridgeDocs={bridgeDocs}
        locale={locale}
      />

      {bridgeDocs.length > 0 && (
        <div className="rounded-lg border border-[var(--color-border)] p-4">
          <h3 className="mb-3 text-sm font-semibold">{t("bridge_docs")}</h3>
          <div className="flex flex-wrap gap-2">
            {bridgeDocs.map((doc) => (
              <Link key={doc.slug} href={`/${locale}/docs/${doc.slug}`} className="rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700">
                {doc.title}
              </Link>
            ))}
          </div>
        </div>
      )}

      <nav className="flex items-center justify-between border-t border-zinc-200 pt-6 dark:border-zinc-700">
        {prevVersion ? (
          <Link href={`/${locale}/${prevVersion}`} className="group flex items-center gap-2 text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:hover:text-white">
            <span className="transition-transform group-hover:-translate-x-1">&larr;</span>
            <div><div className="text-xs text-zinc-400">{t("prev")}</div><div className="font-medium">{prevVersion} - {tSession(prevVersion) || VERSION_META[prevVersion]?.title}</div></div>
          </Link>
        ) : <div />}
        {nextVersion ? (
          <Link href={`/${locale}/${nextVersion}`} className="group flex items-center gap-2 text-right text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:hover:text-white">
            <div><div className="text-xs text-zinc-400">{t("next")}</div><div className="font-medium">{tSession(nextVersion) || VERSION_META[nextVersion]?.title} - {nextVersion}</div></div>
            <span className="transition-transform group-hover:translate-x-1">&rarr;</span>
          </Link>
        ) : <div />}
      </nav>
    </div>
  );
}
