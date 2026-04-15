const GENERIC_OVERVIEW_VERSIONS = new Set([
  "s00", "s07", "s08", "s09", "s10", "s11",
  "s12", "s13", "s14", "s15",
  "s16", "s17", "s18", "s19", "s20",
]);

export function isGenericOverviewVersion(version: string): boolean {
  return GENERIC_OVERVIEW_VERSIONS.has(version);
}

const GENERIC_SCENARIO_VERSIONS = new Set([
  "s07", "s08", "s09", "s10", "s11",
  "s12", "s13", "s14", "s15",
  "s16", "s17", "s18", "s19", "s20",
]);

export function isGenericScenarioVersion(version: string): boolean {
  return GENERIC_SCENARIO_VERSIONS.has(version);
}
