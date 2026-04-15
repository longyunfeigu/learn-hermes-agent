import Link from "next/link";
import { BRIDGE_DOCS, getChaptersForBridgeDoc } from "@/lib/bridge-docs";
import { VERSION_META } from "@/lib/constants";
import { DocRenderer } from "@/components/docs/doc-renderer";
import { getTranslations } from "@/lib/i18n-server";

const locales = ["zh", "en"];

export function generateStaticParams() {
  const params: { locale: string; slug: string }[] = [];
  for (const locale of locales) {
    for (const slug of Object.keys(BRIDGE_DOCS)) {
      params.push({ locale, slug });
    }
  }
  return params;
}

export default async function BridgeDocPage({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;
  const descriptor = BRIDGE_DOCS[slug];
  const tSession = getTranslations(locale, "sessions");

  if (!descriptor) {
    return (
      <div className="py-20 text-center">
        <h1 className="text-2xl font-bold">Document not found</h1>
        <p className="mt-2 text-zinc-500">{slug}</p>
      </div>
    );
  }

  const relatedVersions = getChaptersForBridgeDoc(slug);

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-4">
      <header className="space-y-2">
        <Link
          href={`/${locale}`}
          className="text-sm text-zinc-500 transition-colors hover:text-zinc-900 dark:hover:text-white"
        >
          &larr; Back
        </Link>
        <h1 className="text-2xl font-bold sm:text-3xl">
          {descriptor.title[locale as "zh" | "en"] || descriptor.title.zh}
        </h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {descriptor.summary[locale as "zh" | "en"] || descriptor.summary.zh}
        </p>
      </header>

      <DocRenderer slug={slug} />

      {relatedVersions.length > 0 && (
        <div className="rounded-lg border border-[var(--color-border)] p-4">
          <h3 className="mb-3 text-sm font-semibold">Related Chapters</h3>
          <div className="flex flex-wrap gap-2">
            {relatedVersions.map((vId) => (
              <Link
                key={vId}
                href={`/${locale}/${vId}`}
                className="rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              >
                {vId} - {tSession(vId) || VERSION_META[vId]?.title}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
