import { context } from "esbuild";
import { createServer, request } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { options, copyStatic } from "./build.mjs";

await copyStatic();
const builder = await context({ ...options, minify: false });
await builder.rebuild();
await builder.watch();
const root = resolve("dist");
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".map": "application/json",
};
const server = createServer(async (req, res) => {
  if (req.url?.startsWith("/api/")) {
    const upstream = request(
      {
        hostname: "127.0.0.1",
        port: 8000,
        path: req.url,
        method: req.method,
        headers: req.headers,
      },
      (response) => {
        res.writeHead(response.statusCode ?? 502, response.headers);
        response.pipe(res);
      },
    );
    upstream.on("error", () => {
      if (res.headersSent) {
        res.destroy();
        return;
      }
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          detail: "Backend unavailable. Start FastAPI on port 8000.",
        }),
      );
    });
    req.pipe(upstream);
    return;
  }
  try {
    const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
    const path = resolve(
      root,
      `.${pathname === "/" ? "/index.html" : pathname}`,
    );
    if (!path.startsWith(root + "/")) {
      res.writeHead(403);
      res.end();
      return;
    }
    const content = await readFile(path);
    res.writeHead(200, {
      "Content-Type": types[extname(path)] ?? "application/octet-stream",
      "Cache-Control": "no-cache",
    });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end("File not found.");
  }
});
server.listen(5173, "127.0.0.1", () =>
  console.log(
    "Workbench: http://127.0.0.1:5173 — refresh after source changes.",
  ),
);
async function stop() {
  server.close();
  await builder.dispose();
  process.exit();
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
