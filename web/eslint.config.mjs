import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import noComments from "eslint-plugin-no-comments";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: { "no-comments": noComments },
    rules: { "no-comments/disallowComments": "error" },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "src/api/schema.d.ts",
  ]),
]);
