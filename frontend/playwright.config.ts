import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { tmpdir } from "node:os";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:8011", trace: "retain-on-failure" },
  projects: [
    {
      name: "compact",
      grep: /automated accessibility/,
      use: { viewport: { width: 900, height: 1000 } },
    },
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer: {
    command: `"${process.env.WORKBENCH_PYTHON || resolve("../.venv/bin/python")}" -m uvicorn workbench.main:create_app --factory --app-dir ../backend --host 127.0.0.1 --port 8011`,
    url: "http://127.0.0.1:8011/api/health",
    reuseExistingServer: false,
    env: {
      WORKBENCH_DB: resolve(
        tmpdir(),
        `workbench-browser-${process.pid}.sqlite3`,
      ),
    },
  },
});
