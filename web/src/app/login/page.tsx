"use client";

import { useActionState } from "react";
import { login } from "./actions";

export default function LoginPage() {
  const [state, action, pending] = useActionState(login, {});

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 p-6">
      <div>
        <h1 className="text-xl font-semibold">Demo access</h1>
        <p className="text-sm text-muted-foreground">
          Enter the shared demo password to continue.
        </p>
      </div>
      <form action={action} className="space-y-3">
        <label
          className="block space-y-1 text-sm font-medium"
          htmlFor="password"
        >
          <span>Password</span>
          <input
            id="password"
            name="password"
            type="password"
            required
            autoFocus
            className="w-full rounded-md border bg-background px-3 py-2"
          />
        </label>
        {state.error && (
          <p className="text-sm text-destructive">{state.error}</p>
        )}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-md bg-primary px-3 py-2 text-primary-foreground disabled:opacity-60"
        >
          {pending ? "Checking…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
