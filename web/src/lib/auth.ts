import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export const sessionCookieName = "demo_session";
const sessionTtlSeconds = 60 * 60 * 12;

type SessionPayload = { exp: number };

function configuredToken() {
  return process.env.API_ACCESS_TOKEN ?? "";
}

function configuredPassword() {
  return process.env.DEMO_PASSWORD ?? "";
}

export function isAuthConfigured() {
  return configuredToken() !== "" && configuredPassword() !== "";
}

function signingSecret() {
  if (!isAuthConfigured()) return "";
  return `${configuredToken()}\0${configuredPassword()}`;
}

export function constantTimeEquals(a: string, b: string) {
  const left = createHash("sha256").update(a).digest();
  const right = createHash("sha256").update(b).digest();
  return timingSafeEqual(left, right);
}

function signature(payload: string) {
  return createHmac("sha256", signingSecret())
    .update(payload)
    .digest("base64url");
}

export function verifyPassword(password: string) {
  const expected = configuredPassword();
  return expected !== "" && constantTimeEquals(password, expected);
}

export function signSession(now = Date.now()) {
  if (!isAuthConfigured()) throw new Error("Demo auth is not configured.");
  const payload = Buffer.from(
    JSON.stringify({
      exp: now + sessionTtlSeconds * 1000,
    } satisfies SessionPayload),
  ).toString("base64url");
  return `${payload}.${signature(payload)}`;
}

export function verifySession(value: string | undefined, now = Date.now()) {
  if (!value || !isAuthConfigured()) return false;
  const [payload, mac, extra] = value.split(".");
  if (!payload || !mac || extra !== undefined) return false;
  if (!constantTimeEquals(mac, signature(payload))) return false;
  try {
    const parsed = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    ) as Partial<SessionPayload>;
    return typeof parsed.exp === "number" && parsed.exp > now;
  } catch {
    return false;
  }
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: sessionTtlSeconds,
  };
}
