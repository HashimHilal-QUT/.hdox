import { unzipSync } from "fflate";

export const HDOX_MIMETYPE = "application/vnd.hdox+zip";

export interface HDOXArchive {
  manifest: Record<string, any>;
  files: Record<string, Uint8Array>;
  html: string;
}

function text(bytes: Uint8Array): string {
  return new TextDecoder("utf-8").decode(bytes);
}

export function readHDOX(bytes: Uint8Array): HDOXArchive {
  const files = unzipSync(bytes);
  if (text(files["mimetype"] ?? new Uint8Array()) !== HDOX_MIMETYPE) {
    throw new Error("Invalid HDOX mimetype");
  }
  if (!files["manifest.json"] || !files["index.html"]) {
    throw new Error("HDOX requires manifest.json and index.html");
  }
  const manifest = JSON.parse(text(files["manifest.json"]));
  if (manifest.security?.allow_external_network) {
    throw new Error("External network access is not allowed in HDOX v1.0.0");
  }
  return { manifest, files, html: text(files["index.html"]) };
}
