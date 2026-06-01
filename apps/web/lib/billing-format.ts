export function formatMoneyMinor(
  amountMinor: number | null | undefined,
  currency = "INR",
): string {
  if (amountMinor === null || amountMinor === undefined) return "Custom";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amountMinor / 100);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "Unlimited";
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatLimit(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "custom") return "Custom";
  if (value === true) return "Yes";
  if (value === false) return "No";
  if (typeof value === "number") {
    return `${new Intl.NumberFormat("en-IN").format(value)}${suffix}`;
  }
  return String(value).replaceAll("_", " ");
}

export function ratioPercent(used: number, limit: number | null | undefined): number {
  if (!limit || limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}
