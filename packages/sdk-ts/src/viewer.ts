import { HDOXArchive } from "./archive";
import { toLLMContext } from "./llm";

export class HDOXViewer {
  private urls = new Map<string, string>();

  async render(archive: HDOXArchive, iframe: HTMLIFrameElement): Promise<Record<string, unknown>> {
    for (const [name, bytes] of Object.entries(archive.files)) {
      if (name === "mimetype" || name === "manifest.json") continue;
      const blob = new Blob([new Uint8Array(bytes)], { type: this.mimeType(name) });
      this.urls.set(name, URL.createObjectURL(blob));
    }
    const documentElement = new DOMParser().parseFromString(archive.html, "text/html");
    documentElement.querySelectorAll("[src], [href]").forEach((element) => {
      for (const attribute of ["src", "href"] as const) {
        const value = element.getAttribute(attribute);
        if (!value || /^[a-z]+:/i.test(value) || value.startsWith("//")) continue;
        const resolved = value.split(/[?#]/)[0];
        const url = this.urls.get(resolved);
        if (url) element.setAttribute(attribute, url);
      }
    });
    if (!archive.manifest.security?.allow_scripts) {
      documentElement.querySelectorAll("script").forEach((script) => script.remove());
    }
    iframe.sandbox.value = "allow-same-origin";
    iframe.srcdoc = "<!doctype html>\n" + documentElement.documentElement.outerHTML;
    return this.inspect(archive) as unknown as Record<string, unknown>;
  }

  inspect(archive: HDOXArchive) {
    return toLLMContext(archive.html, archive.manifest);
  }

  print(iframe: HTMLIFrameElement) {
    iframe.contentWindow?.print();
  }

  dispose() {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }

  private mimeType(name: string): string {
    if (name.endsWith(".css")) return "text/css";
    if (name.endsWith(".html")) return "text/html";
    if (name.endsWith(".woff2")) return "font/woff2";
    if (name.endsWith(".svg")) return "image/svg+xml";
    if (name.endsWith(".webp")) return "image/webp";
    if (name.endsWith(".png")) return "image/png";
    if (name.endsWith(".json")) return "application/json";
    if (name.endsWith(".csv")) return "text/csv";
    return "application/octet-stream";
  }
}
