const MOJIBAKE_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00b9/g, 'Rs '],
  [/\u00e2\u201a\u00b9/g, 'Rs '],
  [/\u00e2\u20ac\u201d/g, ' - '],
  [/\u00e2\u20ac\u201c/g, ' - '],
  [/\u00e2\u20ac\u02dc/g, "'"],
  [/\u00e2\u20ac\u2122/g, "'"],
  [/\u00e2\u20ac\u0153/g, '"'],
  [/\u00e2\u20ac\u009d/g, '"'],
  [/\u00e2\u20ac\u00a6/g, '...'],
  [/\u00e2\u20ac\u00a2/g, '-'],
  [/\u00e2\u2020\u2019/g, '->'],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u20ac\u009d/g, ' - '],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u20ac\u0153/g, ' - '],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u02dc/g, "'"],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u2122/g, "'"],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u0153/g, '"'],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u009d/g, '"'],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u00a6/g, '...'],
  [/\u00c3\u00a2\u00e2\u201a\u00ac\u00a2/g, '-'],
  [/\u00c3\u00a2\u00e2\u20ac\u2020\u00e2\u20ac\u2122/g, '->'],
  [/\u00c2\u00b7/g, ' - '],
  [/\u00c2/g, ''],
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
