export type UnknownRecord = Record<string, unknown>;

export function asRecord(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}

export function at(record: UnknownRecord, ...path: string[]): unknown {
  return path.reduce<unknown>((value, key) => asRecord(value)[key], record);
}

export function numberAt(record: UnknownRecord, ...path: string[]): number | null {
  const value = at(record, ...path);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value)))
    return Number(value);
  return null;
}

export function stringAt(record: UnknownRecord, ...path: string[]): string | null {
  const value = at(record, ...path);
  return typeof value === "string" && value ? value : null;
}

export function stringArrayAt(record: UnknownRecord, ...path: string[]): string[] {
  const value = at(record, ...path);
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function formatRate(numerator: number | null, denominator: number | null): string {
  if (numerator === null || denominator === null || denominator === 0) return "Not measured";
  return new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(
    numerator / denominator,
  );
}

export function shortHash(value: string | null | undefined): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "Not published";
}
