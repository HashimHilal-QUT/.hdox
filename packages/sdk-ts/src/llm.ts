export function toLLMContext(html: string, manifest: Record<string, any>): {
  markdown: string;
  jsonLd: Record<string, unknown>[];
  manifest: Record<string, any>;
} {
  const jsonLd: Record<string, unknown>[] = [];
  if (typeof DOMParser !== "undefined") {
    const documentElement = new DOMParser().parseFromString(html, "text/html");
    documentElement.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
      try {
        const value = JSON.parse(script.textContent ?? "");
        jsonLd.push(...(Array.isArray(value) ? value : [value]));
      } catch {}
    });
  } else {
    let cursor = 0;
    while (cursor < html.length) {
      const start = html.indexOf("<script", cursor);
      if (start < 0) break;
      const openEnd = html.indexOf(">", start);
      if (openEnd < 0) break;
      const opening = html.slice(start, openEnd + 1);
      const end = html.indexOf("</script>", openEnd + 1);
      if (opening.includes("application/ld+json") && end >= 0) {
        try {
          const value = JSON.parse(html.slice(openEnd + 1, end));
          jsonLd.push(...(Array.isArray(value) ? value : [value]));
        } catch {}
      }
      cursor = end >= 0 ? end + 9 : openEnd + 1;
    }
  }

  let markdown = "";
  let cursor = 0;
  let suppressed = 0;
  while (cursor < html.length) {
    const start = html.indexOf("<", cursor);
    if (start < 0) {
      if (!suppressed) markdown += html.slice(cursor);
      break;
    }
    if (!suppressed) markdown += html.slice(cursor, start);
    const end = html.indexOf(">", start);
    if (end < 0) break;
    const tag = html.slice(start + 1, end).trim().toLowerCase();
    if (tag.startsWith("script") || tag.startsWith("style")) suppressed++;
    if (tag.startsWith("/script") || tag.startsWith("/style")) suppressed = Math.max(0, suppressed - 1);
    if (!suppressed) {
      if (tag.startsWith("h1")) markdown += "\n# ";
      else if (tag.startsWith("h2")) markdown += "\n## ";
      else if (tag.startsWith("p") || tag.startsWith("li") || tag.startsWith("/p") || tag.startsWith("/li")) markdown += "\n";
    }
    cursor = end + 1;
  }
  markdown = markdown.split("&nbsp;").join(" ").trim();
  return { markdown, jsonLd, manifest };
}
