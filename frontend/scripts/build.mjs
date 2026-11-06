import { build } from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
export const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outdir: "dist/assets",
  entryNames: "app",
  sourcemap: true,
  target: ["es2022"],
  minify: true,
};
export async function copyStatic() {
  await mkdir("dist/assets", { recursive: true });
  await Promise.all(
    ["index.html", "mark.svg"].map((file) => copyFile(file, `dist/${file}`)),
  );
}
if (resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  await copyStatic();
  await build(options);
}
