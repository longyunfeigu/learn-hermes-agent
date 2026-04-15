export interface BridgeDocDescriptor {
  slug: string;
  kind: "map" | "mechanism";
  title: Record<"zh" | "en", string>;
  summary: Record<"zh" | "en", string>;
}

export const BRIDGE_DOCS: Record<string, BridgeDocDescriptor> = {
  "glossary": {
    slug: "glossary",
    kind: "map",
    title: { zh: "术语表", en: "Glossary" },
    summary: { zh: "核心术语快速查阅", en: "Quick reference for core terms" },
  },
  "entity-map": {
    slug: "entity-map",
    kind: "map",
    title: { zh: "系统实体边界图", en: "Entity Map" },
    summary: { zh: "各实体属于哪一层、互相什么关系", en: "Entity boundaries across layers" },
  },
  "data-structures": {
    slug: "data-structures",
    kind: "map",
    title: { zh: "核心数据结构总表", en: "Core Data Structures" },
    summary: { zh: "状态到底存在哪一层", en: "Where state lives across layers" },
  },
  "teaching-scope": {
    slug: "teaching-scope",
    kind: "mechanism",
    title: { zh: "教学范围说明", en: "Teaching Scope" },
    summary: { zh: "教什么、不教什么", en: "What is covered and what is not" },
  },
};

// Which bridge docs are related to each chapter
export const CHAPTER_BRIDGE_DOCS: Partial<Record<string, string[]>> = {
  s00: ["glossary", "entity-map", "data-structures", "teaching-scope"],
  s01: ["glossary", "entity-map"],
  s02: ["glossary", "entity-map"],
  s03: ["data-structures"],
  s04: ["data-structures"],
  s05: ["data-structures"],
  s07: ["data-structures", "entity-map"],
  s08: ["entity-map"],
  s10: ["entity-map"],
  s11: ["data-structures"],
};

export function getBridgeDocDescriptors(version: string): BridgeDocDescriptor[] {
  const slugs = CHAPTER_BRIDGE_DOCS[version] ?? [];
  return slugs
    .map((slug) => BRIDGE_DOCS[slug])
    .filter((d): d is BridgeDocDescriptor => Boolean(d));
}

export function getChaptersForBridgeDoc(slug: string): string[] {
  return Object.entries(CHAPTER_BRIDGE_DOCS)
    .filter(([, slugs]) => slugs?.includes(slug))
    .map(([version]) => version);
}
