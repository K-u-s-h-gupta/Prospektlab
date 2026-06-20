const MOJIBAKE_REPLACEMENTS: Array<[RegExp, string]> = [
  [/Ã¢â€šÂ¹/g, '₹'],
  [/â‚¹/g, '₹'],
  [/â€”/g, '—'],
  [/â€“/g, '–'],
  [/â€˜/g, '‘'],
  [/â€™/g, '’'],
  [/â€œ/g, '“'],
  [/â€/g, '”'],
  [/â€¦/g, '…'],
  [/â€¢/g, '•'],
  [/â†’/g, '→'],
  [/Ã¢â‚¬â€/g, '—'],
  [/Ã¢â‚¬â€œ/g, '–'],
  [/Ã¢â‚¬Ëœ/g, '‘'],
  [/Ã¢â‚¬â„¢/g, '’'],
  [/Ã¢â‚¬Å“/g, '“'],
  [/Ã¢â‚¬Â/g, '”'],
  [/Ã¢â‚¬Â¦/g, '…'],
  [/Ã¢â‚¬Â¢/g, '•'],
  [/Ã¢â€\u00a0â€™/g, '→'],
  [/Â·/g, '·'],
  [/Â/g, ''],
];

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && Object.prototype.toString.call(value) === '[object Object]';

export function repairMojibakeText(value: string): string {
  let next = String(value ?? '').normalize('NFC');
  for (const [pattern, replacement] of MOJIBAKE_REPLACEMENTS) {
    next = next.replace(pattern, replacement);
  }
  return next;
}

export function sanitizeMojibakeValue<T>(value: T): T {
  if (typeof value === 'string') {
    return repairMojibakeText(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeMojibakeValue(item)) as T;
  }
  if (isPlainObject(value)) {
    const entries = Object.entries(value).map(([key, item]) => [key, sanitizeMojibakeValue(item)]);
    return Object.fromEntries(entries) as T;
  }
  return value;
}
