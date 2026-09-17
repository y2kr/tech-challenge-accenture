import { defineConfig, devices } from "@playwright/test";

const testDatabaseUrl = process.env.TEST_DATABASE_URL;
if (!testDatabaseUrl) throw new Error("TEST_DATABASE_URL is required");

export default defineConfig({
  testDir: "./e2e",
  outputDir: ".next/playwright-results",
  use: {
    baseURL: "http://127.0.0.1:3000",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command:
        "cd ../api && uv run alembic upgrade head && uv run uvicorn monitor.main:app --host 127.0.0.1 --port 8000",
      env: {
        CORS_ORIGINS: "http://127.0.0.1:3000",
        DATABASE_URL: testDatabaseUrl,
        OPENAI_API_KEY: "",
      },
      port: 8000,
      reuseExistingServer: false,
    },
    {
      command: "pnpm dev --hostname 127.0.0.1",
      env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8000" },
      port: 3000,
      reuseExistingServer: false,
    },
  ],
});
