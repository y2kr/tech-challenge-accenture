import assert from "node:assert/strict";
import test from "node:test";

const auth = await import("../src/lib/auth.ts");

function configure({ token = "token", password = "password" } = {}) {
  if (token === undefined) {
    delete process.env.API_ACCESS_TOKEN;
  } else {
    process.env.API_ACCESS_TOKEN = token;
  }
  if (password === undefined) {
    delete process.env.DEMO_PASSWORD;
  } else {
    process.env.DEMO_PASSWORD = password;
  }
}

test("signed session verifies", () => {
  configure();
  const session = auth.signSession(1_000);

  assert.equal(auth.verifySession(session, 2_000), true);
});

test("expired session is rejected", () => {
  configure();
  const session = auth.signSession(1_000);

  assert.equal(
    auth.verifySession(session, 1_000 + 12 * 60 * 60 * 1_000 + 1),
    false,
  );
});

test("tampered session is rejected", () => {
  configure();
  const session = auth.signSession(1_000);

  assert.equal(auth.verifySession(`${session}x`, 2_000), false);
});

test("missing config fails closed", () => {
  configure({ token: "", password: "password" });
  assert.equal(auth.verifySession("anything", 2_000), false);
  assert.throws(() => auth.signSession(1_000), /not configured/);

  configure({ token: "token", password: "" });
  assert.equal(auth.verifyPassword("password"), false);
  assert.equal(auth.verifySession("anything", 2_000), false);
  assert.throws(() => auth.signSession(1_000), /not configured/);
});

test("password rotation invalidates existing sessions", () => {
  configure({ token: "token", password: "old-password" });
  const session = auth.signSession(1_000);

  configure({ token: "token", password: "new-password" });

  assert.equal(auth.verifySession(session, 2_000), false);
});
