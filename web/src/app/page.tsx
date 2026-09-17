"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchStudies } from "@/api/client";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { StudyTable } from "@/components/study-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function WatchlistPage() {
  const studies = useQuery({ queryKey: ["studies"], queryFn: fetchStudies });

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">AstraZeneca watchlist</h1>
          <p className="text-sm text-muted-foreground">
            Lead sponsor · 50 most recently updated studies · Live from
            ClinicalTrials.gov
            {studies.data &&
              ` · retrieved ${utcTime(studies.data.retrieved_at)}`}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => studies.refetch()}
          disabled={studies.isFetching}
        >
          {studies.isFetching ? "Refreshing…" : "Refresh"}
        </Button>
      </header>
      {studies.isPending ? (
        <LoadingRows />
      ) : studies.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Studies could not be loaded</AlertTitle>
          <AlertDescription>{studies.error.message}</AlertDescription>
          <AlertAction>
            <Button
              size="sm"
              variant="outline"
              onClick={() => studies.refetch()}
              disabled={studies.isFetching}
            >
              Retry
            </Button>
          </AlertAction>
        </Alert>
      ) : (
        <StudyTable list={studies.data} />
      )}
    </main>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2" aria-label="Loading studies">
      {Array.from({ length: 8 }, (_, row) => (
        <Skeleton key={row} className="h-9 w-full" />
      ))}
    </div>
  );
}

function utcTime(timestamp: string) {
  return `${new Date(timestamp).toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  })} UTC`;
}
