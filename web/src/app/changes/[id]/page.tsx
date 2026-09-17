"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { decideAction, fetchChange, type Decision } from "@/api/client";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export default function ChangeDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const queryClient = useQueryClient();
  const change = useQuery({
    queryKey: ["change", id],
    queryFn: () => fetchChange(id),
    enabled: Number.isInteger(id) && id > 0,
  });
  const decision = useMutation({
    mutationFn: decideAction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["change", id] });
      queryClient.invalidateQueries({ queryKey: ["changes", "replay"] });
    },
  });

  if (change.isPending) {
    return (
      <main
        className="mx-auto max-w-6xl space-y-3 p-4 sm:p-6"
        aria-label="Loading change"
      >
        {Array.from({ length: 5 }, (_, row) => (
          <Skeleton key={row} className="h-24 w-full" />
        ))}
      </main>
    );
  }

  if (change.isError || !change.data) {
    return (
      <main className="mx-auto max-w-6xl p-4 sm:p-6">
        <Alert variant="destructive">
          <AlertTitle>Change could not be loaded</AlertTitle>
          <AlertDescription>
            {change.error?.message ?? "Invalid change ID."}
          </AlertDescription>
        </Alert>
      </main>
    );
  }

  const data = change.data;

  function decide(id: number, status: Decision) {
    decision.mutate({ id, status });
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <header className="space-y-2">
        <Link
          href="/changes"
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Change inbox
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="destructive">{data.severity.toUpperCase()}</Badge>
          <Badge variant="outline">
            {data.review_status.replaceAll("_", " ")}
          </Badge>
        </div>
        <h1 className="text-2xl font-semibold">{data.headline}</h1>
        <p className="text-sm text-muted-foreground">
          {data.nct_id} · {data.title} · {data.label}
        </p>
      </header>

      <section className="space-y-3" aria-labelledby="evidence-heading">
        <div>
          <h2 id="evidence-heading" className="text-lg font-semibold">
            Exact evidence
          </h2>
          <p className="text-sm text-muted-foreground">
            Deterministic facts used for severity and supplied to AI. AI cannot
            edit these values.
          </p>
        </div>
        <div className="space-y-3">
          {data.structured_diff.map((item) => (
            <article key={item.field} className="rounded-lg border p-4">
              <h3 className="mb-3 font-medium">
                {item.field.replaceAll("_", " ")}
              </h3>
              <div className="grid gap-3 md:grid-cols-2">
                <Evidence label="Before" value={item.before} />
                <Evidence label="After" value={item.after} />
              </div>
            </article>
          ))}
        </div>
      </section>

      <section
        className="space-y-3 rounded-lg border border-blue-200 bg-blue-50 p-4"
        aria-labelledby="ai-heading"
      >
        <div>
          <h2 id="ai-heading" className="text-lg font-semibold">
            AI interpretation
          </h2>
          <p className="text-xs text-muted-foreground">
            Generated only from the evidence above; verify before use.
          </p>
        </div>
        {data.ai_analysis ? (
          <div className="space-y-3">
            <h3 className="font-medium">{data.ai_analysis.headline}</h3>
            <p className="text-sm">{data.ai_analysis.summary}</p>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {data.ai_analysis.possible_significance.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <Badge variant="outline">
              Confidence: {data.ai_analysis.confidence}
            </Badge>
          </div>
        ) : (
          <p className="text-sm">
            AI explanation is unavailable. Exact evidence and follow-up
            decisions remain usable.
          </p>
        )}
      </section>

      <section className="space-y-3" aria-labelledby="actions-heading">
        <div>
          <h2 id="actions-heading" className="text-lg font-semibold">
            Proposed follow-up
          </h2>
          <p className="text-sm text-muted-foreground">
            Nothing is approved until you choose an action below.
          </p>
        </div>
        {decision.isError && (
          <Alert variant="destructive">
            <AlertTitle>Decision was not saved</AlertTitle>
            <AlertDescription>{decision.error.message}</AlertDescription>
          </Alert>
        )}
        <div className="space-y-2">
          {data.actions.map((action) => (
            <article
              key={action.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
            >
              <div>
                <p className="font-medium">{action.title}</p>
                <Badge className="mt-1" variant="outline">
                  {action.status}
                </Badge>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={() => decide(action.id, "approved")}
                  disabled={decision.isPending}
                >
                  Approve
                </Button>
                <Button
                  variant="outline"
                  onClick={() => decide(action.id, "rejected")}
                  disabled={decision.isPending}
                >
                  Reject
                </Button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="audit-heading">
        <h2 id="audit-heading" className="text-lg font-semibold">
          Audit timeline
        </h2>
        <ol className="space-y-3 border-l pl-5 text-sm">
          <li>
            <p className="font-medium">Change detected</p>
            <time className="text-muted-foreground">
              {formatTime(data.created_at)}
            </time>
          </li>
          {data.audit_timeline.map((entry) => (
            <li key={entry.id}>
              <p className="font-medium">
                Follow-up {entry.decision}: {entry.action_title}
              </p>
              <time className="text-muted-foreground">
                {formatTime(entry.created_at)}
              </time>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

function Evidence({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <pre className="overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    timeZone: "UTC",
    timeZoneName: "short",
  });
}
