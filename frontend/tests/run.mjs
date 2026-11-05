// Unit testlarni esbuild bilan yig'ib Node'da ishga tushirish
import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const out = join(mkdtempSync(join(tmpdir(), "ilmt-")), "t.mjs");
await build({ entryPoints: ["tests/logic.test.ts"], bundle: true, platform: "node", format: "esm", outfile: out,
  define: { __STATIC__: "false" }, logLevel: "error" });
await import(pathToFileURL(out).href);
