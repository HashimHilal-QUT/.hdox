export function toLLMContext(html: string, manifest: Record<string, any>): {
  markdown: string;
  jsonLd: Record<string, unknown>[];
  manifest: Record<string, any>;
} {
  const jsonLd: Record<string, unknown>[] = [];
  const ldPattern = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let match: RegExpExecArray | null;
  while ((match = ldPattern.exec(html))) {
    try {
      const value = JSON.parse(match[1]);
      jsonLd.push(...(Array.isArray(value) ? value : [value]));
    } catch {}
  }
  const markdown = html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<h1[^>]*>([\s\S]*?)<\/h1>/gi, "\n# $1\n")
    .replace(/<h2[^>]*>([\s\S]*?)<\/h2>/gi, "\n## $1\n")
    .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, "\n$1\n")
    .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, "\n- $1")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { markdown, jsonLd, manifest };
}
