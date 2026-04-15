export interface DocContent {
  version: string | null;
  slug: string;
  locale: string;
  title: string;
  kind: "chapter" | "bridge";
  filename: string;
  content: string;
}

export interface AgentVersion {
  id: string;
  filename: string;
  title: string;
  loc: number;
  tools: string[];
  classes: string[];
  functions: string[];
  source: string;
}

export interface VersionIndex {
  versions: AgentVersion[];
}
