import { defineConfig, devices } from "@playwright/test";

const testDatabaseUrl = process.env.TEST_DATABASE_URL;
if (!testDatabaseUrl) throw new Error("TEST_DATABASE_URL is required");

const apiAccessToken = "local-e2e-token";
const demoPassword = "local-e2e-password";

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
        "cd ../api && uv run alembic downgrade base && uv run alembic upgrade head && uv run uvicorn monitor.main:app --host 127.0.0.1 --port 8000",
      env: {
        CORS_ORIGINS: "http://127.0.0.1:3000",
        DATABASE_URL: testDatabaseUrl,
        OPENAI_API_KEY: "",
        API_ACCESS_TOKEN: apiAccessToken,
      },
      port: 8000,
      reuseExistingServer: false,
    },
    {
      command: "pnpm dev --hostname 127.0.0.1",
      env: {
        API_BASE_URL: "http://127.0.0.1:8000",
        API_ACCESS_TOKEN: apiAccessToken,
        DEMO_PASSWORD: demoPassword,
      },
      port: 3000,
      reuseExistingServer: false,
    },
  ],
});
