// Frontend build: esbuild bilan React + TypeScript -> frontend/dist (backend shu papkani beradi)
import { build, context } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");
const outdir = "dist";
rmSync(outdir, { recursive: true, force: true });
mkdirSync(`${outdir}/assets`, { recursive: true });
cpSync("index.html", `${outdir}/index.html`);
cpSync("public", outdir, { recursive: true });

const options = {
  entryPoints: { app: "src/main.tsx" },
  bundle: true,
  outdir: `${outdir}/assets`,
  format: "esm",
  target: ["es2020"],
  minify: !watch,
  sourcemap: watch,
  jsx: "automatic",
  loader: { ".svg": "text" },
  define: {
    "process.env.NODE_ENV": watch ? '"development"' : '"production"',
    // ILMHUB_STATIC=1 — serversiz (Vercel) yig'ish: hammasi brauzerda, foydalanuvchining Gemini kaliti bilan
    __STATIC__: process.env.ILMHUB_STATIC === "1" || process.argv.includes("--static") ? "true" : "false",
  },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(":") : [],
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("Kuzatilmoqda... (Ctrl+C)");
} else {
  await build(options);
}
