import { expect, test } from "@playwright/test";

test("reviews and approves a synthetic replay change", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(
    /\/api\/changes\?source=replay$/,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.continue();
    },
    { times: 1 },
  );
  await page.goto("/changes");

  await expect(page.getByLabel("Loading changes")).toBeVisible();
  await expect(page.getByText("Replay workspace")).toBeVisible();
  await expect(page.getByText(/not live registry history/i)).toBeVisible();

  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const loadReplay = page.getByRole("button", { name: "Load replay event" });
  await expect(loadReplay).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("CRITICAL")).toBeVisible();

  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: /status changed/i }),
  ).toBeVisible();
  await expect(
    page.locator("header").getByText(/not live registry history/i),
  ).toBeVisible();
  const statusEvidence = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: "overall status" }) });
  await expect(statusEvidence).toContainText('Before"RECRUITING"');
  await expect(statusEvidence).toContainText('After"TERMINATED"');

  const approve = page.getByRole("button", { name: "Approve" }).first();
  await approve.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("approved", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText(/Follow-up approved:/)).toBeVisible();

  await page.route(
    /\/api\/changes\?source=replay$/,
    (route) => route.fulfill({ status: 503, body: "{}" }),
    { times: 1 },
  );
  await page.goto("/changes");
  await expect(page.getByText("Changes could not be loaded")).toBeVisible();

  await page.route(
    /\/api\/studies$/,
    (route) =>
      route.fulfill({
        json: {
          studies: [],
          skipped: 0,
          retrieved_at: "2026-09-17T12:00:00Z",
        },
      }),
    { times: 1 },
  );
  await page.goto("/");
  await expect(page.getByText(/Live from ClinicalTrials.gov/)).toBeVisible();
});
