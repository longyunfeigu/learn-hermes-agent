import * as fs from "fs";
import * as path from "path";
import type { DocContent, AgentVersion, VersionIndex } from "../src/types/doc-data";
import { VERSION_ORDER, VERSION_META } from "../src/lib/constants";

const WEB_DIR = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(WEB_DIR, "..");
const AGENTS_DIR = path.join(REPO_ROOT, "agents");
const DOCS_DIR = path.join(REPO_ROOT, "docs");
const ILLUSTRATIONS_DIR = path.join(REPO_ROOT, "illustrations");
const PUBLIC_DIR = path.join(WEB_DIR, "public");
const OUT_DIR = path.join(WEB_DIR, "src", "data", "generated");

// ---------------------------------------------------------------------------
// Python source extraction
// ---------------------------------------------------------------------------

// s01_agent_loop.py -> "s01"
function filenameToVersionId(filename: string): string | null {
  const base = path.basename(filename, ".py");
  if (base === "__init__") return null;
  const match = base.match(/^(s\d+[a-z]?)_/);
  return match ? match[1] : null;
}

function extractClasses(lines: string[]): string[] {
  return lines
    .filter((l) => /^class\s+\w+/.test(l))
    .map((l) => l.match(/^class\s+(\w+)/)?.[1] || "");
}

function extractFunctions(lines: string[]): string[] {
  return lines
    .filter((l) => /^def\s+\w+/.test(l))
    .map((l) => l.match(/^def\s+(\w+)/)?.[1] || "");
}

function extractTools(source: string): string[] {
  const toolPattern = /"name"\s*:\s*"(\w+)"/g;
  const tools = new Set<string>();
  let m;
  while ((m = toolPattern.exec(source)) !== null) {
    tools.add(m[1]);
  }
  return Array.from(tools);
}

function countLoc(lines: string[]): number {
  return lines.filter((l) => {
    const t = l.trim();
    return t !== "" && !t.startsWith("#");
  }).length;
}

// ---------------------------------------------------------------------------
// Doc extraction
// ---------------------------------------------------------------------------

function extractDocVersion(filename: string): string | null {
  const m = filename.match(/^(s\d+[a-z]?)-/);
  return m ? m[1] : null;
}

function isMainlineChapter(version: string | null): boolean {
  return version !== null && (VERSION_ORDER as readonly string[]).includes(version);
}

function slugFromFilename(filename: string): string {
  return path.basename(filename, ".md");
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  console.log("Extracting content from agents and docs...");

  // 1. Extract agent Python files
  const versions: AgentVersion[] = [];

  if (fs.existsSync(AGENTS_DIR)) {
    const agentFiles = fs
      .readdirSync(AGENTS_DIR)
      .filter((f: string) => f.startsWith("s") && f.endsWith(".py"));

    console.log(`  Found ${agentFiles.length} agent files`);

    for (const filename of agentFiles) {
      const versionId = filenameToVersionId(filename);
      if (!versionId) continue;

      const filePath = path.join(AGENTS_DIR, filename);
      const source = fs.readFileSync(filePath, "utf-8");
      const lines = source.split("\n");

      const meta = VERSION_META[versionId];
      versions.push({
        id: versionId,
        filename,
        title: meta?.title ?? versionId,
        loc: countLoc(lines),
        tools: extractTools(source),
        classes: extractClasses(lines),
        functions: extractFunctions(lines),
        source,
      });
    }

    // Sort by VERSION_ORDER
    const orderMap = new Map(VERSION_ORDER.map((v, i) => [v, i]));
    versions.sort(
      (a, b) => (orderMap.get(a.id as any) ?? 99) - (orderMap.get(b.id as any) ?? 99)
    );
  } else {
    console.log("  Agents directory not found, skipping.");
  }

  // 2. Extract doc markdown files
  const docs: DocContent[] = [];

  if (fs.existsSync(DOCS_DIR)) {
    const localeDirs = ["zh", "en"];
    let total = 0;

    for (const locale of localeDirs) {
      const localeDir = path.join(DOCS_DIR, locale);
      if (!fs.existsSync(localeDir)) continue;

      const docFiles = fs.readdirSync(localeDir).filter((f: string) => f.endsWith(".md"));
      total += docFiles.length;

      for (const filename of docFiles) {
        const version = extractDocVersion(filename);
        const kind = isMainlineChapter(version) ? "chapter" : "bridge";
        const filePath = path.join(localeDir, filename);
        const rawContent = fs.readFileSync(filePath, "utf-8");
        // Rewrite illustration paths: ../../illustrations/... -> /illustrations/...
        const content = rawContent.replace(/\.\.\/\.\.\/illustrations\//g, "/illustrations/");
        const titleMatch = content.match(/^#\s+(.+)$/m);

        docs.push({
          version: kind === "chapter" ? version : null,
          slug: slugFromFilename(filename),
          locale,
          title: titleMatch ? titleMatch[1] : filename,
          kind,
          filename,
          content,
        });
      }
    }
    console.log(`  Found ${total} doc files`);
  } else {
    console.log("  Docs directory not found, skipping.");
  }

  // 3. Link illustrations into public/ so images referenced as /illustrations/... resolve
  if (fs.existsSync(ILLUSTRATIONS_DIR)) {
    fs.mkdirSync(PUBLIC_DIR, { recursive: true });
    const linkPath = path.join(PUBLIC_DIR, "illustrations");
    const linkStat = fs.lstatSync(linkPath, { throwIfNoEntry: false });
    if (linkStat) fs.rmSync(linkPath, { recursive: true, force: true });
    fs.symlinkSync(ILLUSTRATIONS_DIR, linkPath, "dir");
    console.log(`  Linked illustrations -> ${linkPath}`);
  }

  // 4. Write output
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const versionsPath = path.join(OUT_DIR, "versions.json");
  const index: VersionIndex = { versions };
  fs.writeFileSync(versionsPath, JSON.stringify(index, null, 2));
  console.log(`  Wrote ${versionsPath}`);

  const docsPath = path.join(OUT_DIR, "docs.json");
  fs.writeFileSync(docsPath, JSON.stringify(docs, null, 2));
  console.log(`  Wrote ${docsPath}`);

  console.log(`\nDone: ${versions.length} versions, ${docs.length} docs`);
  for (const v of versions) {
    console.log(`  ${v.id}: ${v.loc} LOC, ${v.tools.length} tools, ${v.classes.length} classes`);
  }
}

main();
