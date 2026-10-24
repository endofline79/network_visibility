// Date.parse truncates sub-millisecond precision. Keep the remaining fractional
// digits so two exported observations in the same millisecond stay ordered.
export function observationTime(value: string): bigint | null {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) return null;
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] || "";
  const subMillisecond = fraction.padEnd(9, "0").slice(3, 9);
  return BigInt(milliseconds) * 1000000n + BigInt(subMillisecond || "0");
}
