const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const ts = require("typescript");

const root = path.resolve(__dirname, "..");
const originalResolve = Module._resolveFilename;

Module._resolveFilename = function resolveAlias(
  request,
  parent,
  isMain,
  options,
) {
  if (request.startsWith("@/")) {
    return originalResolve.call(
      this,
      path.join(root, "src", request.slice(2)),
      parent,
      isMain,
      options,
    );
  }
  return originalResolve.call(this, request, parent, isMain, options);
};

for (const extension of [".ts", ".tsx"]) {
  require.extensions[extension] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
      },
      fileName: filename,
    });
    module._compile(outputText, filename);
  };
}

const { StudyTable } = require("../src/components/study-table.tsx");

const baseList = {
  retrieved_at: "2026-09-17T12:00:00Z",
};
const study = {
  nct_id: "NCT00000001",
  title: "Example trial",
  lead_sponsor: "AstraZeneca",
  phases: ["PHASE3"],
  overall_status: "RECRUITING",
  last_update_posted: "2026-09-01",
};

function render(list) {
  return renderToStaticMarkup(React.createElement(StudyTable, { list }));
}

const allSkipped = render({ ...baseList, studies: [], skipped: 2 });
assert.match(allSkipped, /2 studies could not be read and are hidden/);
assert.doesNotMatch(allSkipped, /No studies found/);

const zeroFetched = render({ ...baseList, studies: [], skipped: 0 });
assert.match(zeroFetched, /No studies found for AstraZeneca as lead sponsor/);

const partialSkipped = render({ ...baseList, studies: [study], skipped: 1 });
assert.match(partialSkipped, /1 study could not be read and is hidden/);
assert.match(partialSkipped, /<table/);
assert.match(partialSkipped, /NCT00000001/);
