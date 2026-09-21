"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  sessionCookieName,
  sessionCookieOptions,
  signSession,
  verifyPassword,
  isAuthConfigured,
} from "@/lib/auth";

export type LoginState = { error?: string };

export async function login(
  _state: LoginState,
  formData: FormData,
): Promise<LoginState> {
  if (!isAuthConfigured()) {
    return { error: "Demo access is not configured." };
  }
  const password = formData.get("password");
  if (typeof password !== "string" || !verifyPassword(password)) {
    return { error: "Invalid password." };
  }
  const cookieStore = await cookies();
  cookieStore.set(sessionCookieName, signSession(), sessionCookieOptions());
  redirect("/");
}
