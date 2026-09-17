"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { fetchChanges, syncReplay } from "@/api/client";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function ChangeInboxPage() {
  const queryClient = useQueryClient();
  const changes = useQuery({
    queryKey: ["changes", "replay"],
    queryFn: fetchChanges,
  });
  const replay = useMutation({
    mutationFn: syncReplay,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["changes", "replay"] }),
  });

  return (
    <main className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Change inbox</h1>
          <p className="text-sm text-muted-foreground">
            Prioritised by deterministic severity, then newest first.
          </p>
        </div>
        <Button onClick={() => replay.mutate()} disabled={replay.isPending}>
          {replay.isPending ? "Loading replay…" : "Load replay event"}
        </Button>
      </header>

      <Alert>
        <AlertTitle>Replay workspace</AlertTitle>
        <AlertDescription>
          Synthetic recruiting-to-terminated history for demonstration; not live
          registry history.
        </AlertDescription>
      </Alert>

      {replay.isError && (
        <Alert variant="destructive">
          <AlertTitle>Replay could not be loaded</AlertTitle>
          <AlertDescription>{replay.error.message}</AlertDescription>
        </Alert>
      )}

      {changes.isPending ? (
        <div className="space-y-2" aria-label="Loading changes">
          {Array.from({ length: 3 }, (_, row) => (
            <Skeleton key={row} className="h-20 w-full" />
          ))}
        </div>
      ) : changes.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Changes could not be loaded</AlertTitle>
          <AlertDescription>{changes.error.message}</AlertDescription>
        </Alert>
      ) : changes.data.length === 0 ? (
        <p className="rounded-lg border p-6 text-sm text-muted-foreground">
          No replay events yet. Load the replay to create one.
        </p>
      ) : (
        <ol className="divide-y rounded-lg border">
          {changes.data.map((change) => (
            <li key={change.id}>
              <Link
                href={`/changes/${change.id}`}
                className="grid gap-2 p-4 hover:bg-muted/60 sm:grid-cols-[7rem_1fr_auto] sm:items-center"
              >
                <Badge
                  variant={
                    change.severity === "critical" ? "destructive" : "outline"
                  }
                >
                  {change.severity.toUpperCase()}
                </Badge>
                <span>
                  <span className="block font-medium">{change.headline}</span>
                  <span className="block text-sm text-muted-foreground">
                    {change.nct_id} · {change.title}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground">
                  {change.review_status.replaceAll("_", " ")}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}
