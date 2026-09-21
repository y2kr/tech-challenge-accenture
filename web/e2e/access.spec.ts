import { expect, test } from "@playwright/test";

test("protects both API surfaces and rejects cross-origin mutations", async ({
  page,
  request,
}) => {
  expect((await request.get("/api/changes")).status()).toBe(401);
  expect(
    (await request.get("http://127.0.0.1:8000/api/changes")).status(),
  ).toBe(401);
  expect((await request.get("http://127.0.0.1:8000/health")).status()).toBe(
    200,
  );

  await page.goto("/");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Invalid password.")).toBeVisible();
  await page.getByLabel("Password").fill("local-e2e-password");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(
    page.getByRole("heading", { name: "AstraZeneca changes" }),
  ).toBeVisible();

  expect((await page.request.get("/api/changes?source=replay")).status()).toBe(
    200,
  );
  expect(
    (
      await page.request.post("/api/sync?mode=replay", {
        headers: { Origin: "https://untrusted.example" },
      })
    ).status(),
  ).toBe(403);
  expect((await page.request.post("/api/sync?mode=replay")).status()).toBe(403);
  expect((await page.request.get("/api/not-allowed")).status()).toBe(404);
});
