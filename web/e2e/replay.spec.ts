import { expect, test, type Page } from "@playwright/test";

const demoPassword = "local-e2e-password";

async function login(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Demo access" }),
  ).toBeVisible();
  await page.getByLabel("Password").fill(demoPassword);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByRole("heading", { name: "AstraZeneca changes" }),
  ).toBeVisible();
}

test("logs in and reviews a synthetic replay draft", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);

  await expect(page.getByText(/Prioritised synthetic/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Monitored studies" }),
  ).toBeVisible();
  await expect(page.getByText("Load replay event")).toBeVisible();
  await page.getByRole("button", { name: "Load replay event" }).click();
  await expect(
    page.getByText(/Replay loaded|Replay already loaded/),
  ).toBeVisible();
  const queuedChange = page.getByRole("button", { name: /status changed/i });
  await expect(queuedChange).toContainText("CRITICAL");

  await queuedChange.click();
  await expect(page.getByRole("button", { name: "← Queue" })).toBeVisible();
  await expect(page.getByText("Synthetic replay workspace")).toBeVisible();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Synthetic replay workspace" })
      .getByText(/not live registry history/i),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Exact public-record evidence" }),
  ).toBeVisible();
  await expect(page.locator("pre", { hasText: '"RECRUITING"' })).toBeVisible();
  await expect(page.locator("pre", { hasText: '"TERMINATED"' })).toBeVisible();

  const draft = page.getByLabel("Verification request draft");
  await expect(draft).toContainText("Manual template—not AI generated");
  await expect(draft).toContainText("Synthetic replay");
  await draft.fill(
    "Verify public registry status changed from recruiting to terminated.",
  );
  await expect(
    page.getByText(/unsaved edits require fresh approval/i),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Generate AI draft" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status")).toContainText(
    /Draft proposed at revision/i,
  );
  await expect(
    page.getByRole("button", { name: "Generate AI draft" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    /Draft approved at revision/i,
  );
  await expect(page.getByText(/Draft approved · revision/i)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Copy Approved" }).click();
  await expect(page.getByRole("status")).toContainText(
    /copied|unavailable|failed/i,
  );
  const approvedHistory = page
    .locator("details")
    .filter({ hasText: /Draft approved · revision/i });
  await approvedHistory.locator("summary").click();
  await expect(approvedHistory.locator("pre")).toContainText(
    /Verify public registry status changed/,
  );

  await draft.fill("Edited after approval requires a fresh decision.");
  await expect(
    page.getByText(/unsaved edits require fresh approval/i),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve", exact: true }),
  ).toBeDisabled();
});

test("shows replay and queue error states", async ({ page }) => {
  await login(page);

  await page.route(
    /\/api\/sync\?mode=replay$/,
    (route) =>
      route.fulfill({ status: 503, json: { detail: "Replay unavailable" } }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Load replay event" }).click();
  await expect(page.getByText("Replay could not be loaded")).toBeVisible();

  await page.route(
    /\/api\/changes\?source=replay$/,
    (route) =>
      route.fulfill({ status: 503, json: { detail: "Queue unavailable" } }),
    { times: 1 },
  );
  await page.reload();
  await expect(page.getByText("Changes could not be loaded")).toBeVisible();
});

test("opens the live monitored studies drawer", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Live studies" }).click();
  await expect(page.getByLabel("Live monitored studies")).toBeVisible();
  await expect(page.getByText(/ClinicalTrials.gov watchlist/i)).toBeVisible();
});
