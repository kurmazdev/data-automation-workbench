import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

async function sample(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Use sample data" }).click();
  await expect(
    page.getByRole("heading", { name: "Inspect the source" }),
  ).toBeVisible();
}
async function rules(page: Page) {
  await page.getByRole("button", { name: "Map fields", exact: true }).click();
  await page.getByRole("button", { name: "Configure rules" }).click();
}
async function process(page: Page) {
  const response = page.waitForResponse(
    (r) =>
      /\/api\/datasets\/[^/]+\/runs$/.test(r.url()) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Process \d+ records$/ }).click();
  const run = await (await response).json();
  await expect(
    page.getByRole("heading", { name: "Record review" }),
  ).toBeVisible();
  return run;
}
async function accessible(page: Page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    result.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
  const overflow = await page.evaluate(() => {
    if (document.documentElement.scrollWidth <= window.innerWidth) return [];
    return Array.from(document.querySelectorAll("body *"))
      .filter(
        (element) => element.getBoundingClientRect().right > window.innerWidth,
      )
      .slice(0, 12)
      .map((element) => ({
        element: element.tagName,
        class: element.className,
        right: element.getBoundingClientRect().right,
        viewport: window.innerWidth,
      }));
  });
  expect(overflow).toEqual([]);
}

test("recent runs stays compact while older runs remain accessible", async ({
  page,
}) => {
  const runs = Array.from({ length: 6 }, (_, index) => ({
    id: `run-${index}`,
    dataset_id: `dataset-${index}`,
    filename: `customers-${index}.csv`,
    created: `2026-11-02T12:0${index}:00Z`,
    summary: {
      total: 2,
      accepted: 1,
      changed: 0,
      rejected: 1,
      audit_events: 2,
    },
  }));
  await page.route("**/api/runs", (route) => route.fulfill({ json: runs }));
  await page.goto("/");
  if (await page.locator(".history").isVisible()) {
    await expect(page.locator(".history-item")).toHaveCount(3);
    await page.getByRole("button", { name: "Show all 6 runs" }).click();
    await expect(page.locator(".history-item")).toHaveCount(6);
    await page.getByRole("button", { name: "Show fewer" }).click();
    await expect(page.locator(".history-item")).toHaveCount(3);
  } else {
    await expect(
      page.getByLabel("Open a saved run").locator("option"),
    ).toHaveCount(7);
  }
});

test("sample workflow, key preservation, comparison, search, safe Excel download", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await sample(page);
  await page.getByRole("button", { name: "Map fields", exact: true }).click();
  await page.getByLabel("Destination for Customer ID").fill("account_id");
  await page.getByLabel("Destination for Company").fill("business");
  await page.getByRole("button", { name: "Configure rules" }).click();
  await expect(
    page.getByRole("checkbox", { name: "account_id", exact: true }),
  ).toBeChecked();
  const run = await process(page);
  expect(run.summary).toMatchObject({
    total: 17,
    accepted: 8,
    changed: 6,
    rejected: 9,
  });
  await page.getByRole("button", { name: "Changed 6", exact: true }).click();
  await page
    .getByRole("button", { name: "Review record 2", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator(".comparison .changed-field")).not.toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Review record 2", exact: true }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Rejected 9", exact: true }).click();
  await page
    .getByRole("searchbox", { name: "Search records" })
    .fill("duplicate");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator(".record-results tbody tr")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Review record 5", exact: true })
    .click();
  await expect(page.locator(".rejection-box")).toContainText(
    "matches source record 2",
  );
  await page.getByRole("button", { name: "Close record details" }).click();
  await page.getByRole("button", { name: "Clear search", exact: true }).click();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export Excel workbook" }).click();
  const download = await downloaded;
  const output = testInfo.outputPath("cleaned.xlsx");
  await download.saveAs(output);
  const result = spawnSync(
    processEnvPython(),
    [
      "-c",
      `import json,sys; from openpyxl import load_workbook; w=load_workbook(sys.argv[1]); print(json.dumps({'sheets':w.sheetnames,'accepted':w['Accepted'].max_row-1,'rejected':w['Rejected'].max_row-1,'id':w['Accepted']['D2'].value,'zero':w['Accepted']['G2'].value,'blank':w['Accepted']['G3'].value,'formulas':sum(c.data_type=='f' for s in w for r in s for c in r)}))`,
      output,
    ],
    { encoding: "utf8" },
  );
  expect(result.status, result.stderr).toBe(0);
  expect(JSON.parse(result.stdout)).toEqual({
    sheets: ["Summary", "Accepted", "Rejected", "Audit"],
    accepted: 8,
    rejected: 9,
    id: "001234",
    zero: "0",
    blank: null,
    formulas: 0,
  });
  await expect(page.getByRole("status")).toContainText("Check your downloads");
  expect(errors).toEqual([]);
});

function processEnvPython() {
  return (
    globalThis.process.env.WORKBENCH_PYTHON || resolve("../.venv/bin/python")
  );
}

test("XLSX upload uses explicit field types and preserves text identifiers", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByLabel("Upload spreadsheet")
    .setInputFiles(resolve("../samples/messy_customers.xlsx"));
  await expect(
    page.getByRole("heading", { name: "Inspect the source" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Source preview" }),
  ).toContainText("001234");
  await page.getByRole("button", { name: "Map fields", exact: true }).click();
  await page.getByLabel("Type for Joined").selectOption("date");
  await expect(page.getByLabel("Type for Customer ID")).toHaveValue("text");
  await page.getByRole("button", { name: "Configure rules" }).click();
  const run = await process(page);
  expect(run.summary).toMatchObject({ total: 17, accepted: 14, rejected: 3 });
});

test("malformed uploads recover and ordinary files get usable text mappings", async ({
  page,
}) => {
  await page.goto("/");
  for (const [name, contents, reason] of [
    ["empty.csv", "", "file is empty"],
    ["bad.xlsx", "broken", "Cannot read"],
    ["bad.csv", "id,value\n001,0,extra", "expected 2"],
  ]) {
    await page.getByLabel("Upload spreadsheet").setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: Buffer.from(contents),
    });
    await expect(page.getByRole("alert")).toContainText(reason);
  }
  await page.getByLabel("Upload spreadsheet").setInputFiles({
    name: "ordinary.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(" id ,__ reserved,id\n001234,0,\n001235,,0"),
  });
  await expect(
    page.getByRole("heading", { name: "Inspect the source" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Map fields", exact: true }).click();
  await expect(
    page.locator(".mapping tbody tr").nth(0).getByRole("textbox"),
  ).toHaveValue("id");
  await expect(page.getByLabel("Destination for __ reserved")).toHaveValue(
    "reserved",
  );
  await expect(
    page.locator(".mapping tbody tr").nth(2).getByRole("textbox"),
  ).toHaveValue("id_2");
  await page.getByRole("button", { name: "Configure rules" }).click();
  const run = await process(page);
  expect(run.summary).toMatchObject({
    total: 2,
    accepted: 2,
    changed: 0,
    rejected: 0,
  });
});

test("unprocessed edits are distinct from saved results and reruns are separate", async ({
  page,
}) => {
  await sample(page);
  await rules(page);
  const original = await process(page);
  await page.getByRole("button", { name: "Adjust rules & rerun" }).click();
  await page.getByLabel("When a key repeats").selectOption("keep_all");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /Review & export/ })
    .click();
  await expect(page.locator(".draft-notice")).toContainText(
    "Process your edits",
  );
  await expect(
    page.getByRole("button", { name: "Export saved result" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review edits" }).click();
  const updated = await process(page);
  expect(updated.id).not.toBe(original.id);
  expect(updated.summary).toMatchObject({ accepted: 9, rejected: 8 });
  await expect(page.locator(".draft-notice")).toHaveCount(0);
  await page.reload();
  if (await page.locator(".mobile-history").isVisible())
    await page.getByLabel("Open a saved run").selectOption(updated.id);
  else await page.locator(".history-item").first().click();
  await expect(
    page.getByRole("heading", { name: "Record review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Accepted 9", exact: true }),
  ).toBeVisible();
});

test("pagination, empty filters and search operate on the whole dataset", async ({
  page,
}) => {
  await page.goto("/");
  const rows = Array.from(
    { length: 62 },
    (_, i) => `${String(i + 1).padStart(6, "0")},Row ${i + 1}`,
  );
  await page.getByLabel("Upload spreadsheet").setInputFiles({
    name: "pagination.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("id,name\n" + rows.join("\n")),
  });
  await page.getByRole("button", { name: "Next →", exact: true }).click();
  await expect(page.locator(".pager")).toContainText("26–50 of 62");
  await rules(page);
  await process(page);
  await page.getByRole("button", { name: "Changed 0", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No changed records" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Rejected 0", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No rejected records" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "All records 62", exact: true })
    .click();
  await page.getByRole("button", { name: "Next →", exact: true }).click();
  await page.getByRole("button", { name: "Next →", exact: true }).click();
  await expect(page.locator(".pager")).toContainText("51–62 of 62");
  await page.getByRole("searchbox").fill("000062");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator(".pager")).toContainText("1–1 of 1");
  await expect(
    page.getByRole("button", { name: "Review record 63", exact: true }),
  ).toBeVisible();
});

test("failed navigation preserves the current results and can be retried", async ({
  page,
}) => {
  await sample(page);
  await rules(page);
  await process(page);
  await page.route("**/api/datasets/*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Preview is temporarily unavailable." }),
    }),
  );
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /Upload & inspect/ })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Preview is temporarily unavailable",
  );
  await expect(
    page.getByRole("heading", { name: "Record review" }),
  ).toBeVisible();
  await page.unroute("**/api/datasets/*");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: /Upload & inspect/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Inspect the source" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("all steps and record dialog meet automated accessibility and width checks", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await accessible(page);
  if (testInfo.project.name === "desktop")
    await page.screenshot({
      path:
        globalThis.process.env.WORKBENCH_SCREENSHOTS === "1"
          ? resolve("../docs/screenshots/upload.png")
          : testInfo.outputPath("upload.png"),
      fullPage: true,
    });
  await sample(page);
  await accessible(page);
  await page.getByRole("button", { name: "Map fields", exact: true }).click();
  await accessible(page);
  await page.getByRole("button", { name: "Configure rules" }).click();
  await accessible(page);
  await process(page);
  await accessible(page);
  if (testInfo.project.name === "desktop")
    await page.screenshot({
      path:
        globalThis.process.env.WORKBENCH_SCREENSHOTS === "1"
          ? resolve("../docs/screenshots/review.png")
          : testInfo.outputPath("review.png"),
      fullPage: true,
    });
  await page
    .getByRole("button", { name: "Review record 2", exact: true })
    .click();
  await accessible(page);
  await page.keyboard.press("Tab");
  await expect(page.locator(".original-details summary")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Close record details" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Review record 2", exact: true }),
  ).toBeFocused();
});
