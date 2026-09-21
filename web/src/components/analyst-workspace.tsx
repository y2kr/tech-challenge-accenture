"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  decideDraft,
  fetchChange,
  fetchChanges,
  fetchStudies,
  generateDraft,
  saveDraft,
  syncReplay,
  type ChangeDetail,
  type ChangeSummary,
  type Decision,
  type Draft,
  type DraftHistoryEntry,
  type DraftStatus,
} from "@/api/client";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StudyTable } from "@/components/study-table";

export function AnalystWorkspace({ initialId }: { initialId?: number }) {
  const queryClient = useQueryClient();
  const changes = useQuery({
    queryKey: ["changes", "replay"],
    queryFn: fetchChanges,
  });
  const [selectedId, setSelectedId] = useState<number | null>(
    initialId ?? null,
  );
  const [mobileDetail, setMobileDetail] = useState(Boolean(initialId));
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const effectiveSelectedId = selectedId ?? changes.data?.[0]?.id ?? null;

  const detail = useQuery({
    queryKey: ["change", effectiveSelectedId],
    queryFn: () => fetchChange(effectiveSelectedId ?? 0),
    enabled: Boolean(effectiveSelectedId),
  });

  const replay = useMutation({
    mutationFn: syncReplay,
    onSuccess: (result) => {
      setNotice(
        result.event_ids.length > 0
          ? "Replay loaded: synthetic AstraZeneca reconciliation is ready."
          : "Replay already loaded: no new change was created.",
      );
      queryClient.invalidateQueries({ queryKey: ["changes", "replay"] });
    },
  });

  function selectChange(change: ChangeSummary) {
    if (change.id === effectiveSelectedId) {
      setMobileDetail(true);
      return;
    }
    if (draftDirty && !window.confirm("Discard unsaved draft edits?")) return;
    setSelectedId(change.id);
    setDraftDirty(false);
    setMobileDetail(true);
  }

  return (
    <main className="min-h-screen bg-muted/30">
      <div className="mx-auto grid max-w-7xl gap-0 lg:grid-cols-[22rem_1fr]">
        <aside
          className={`${mobileDetail ? "hidden" : "block"} border-r bg-background lg:block`}
        >
          <Queue
            changes={changes}
            selectedId={effectiveSelectedId}
            replayPending={replay.isPending}
            onReplay={() => replay.mutate()}
            onSelect={selectChange}
            notice={notice}
            replayError={replay.error?.message}
            onDrawer={() => setDrawerOpen(true)}
          />
        </aside>

        <section className={`${mobileDetail ? "block" : "hidden"} lg:block`}>
          <WorkspaceHeader
            onBack={() => setMobileDetail(false)}
            onDrawer={() => setDrawerOpen(true)}
          />
          <div className="p-4 sm:p-6">
            <ReplayNotice />
            {detail.isPending && effectiveSelectedId ? (
              <LoadingDetail />
            ) : detail.isError ? (
              <Alert variant="destructive">
                <AlertTitle>Change could not be loaded</AlertTitle>
                <AlertDescription>{detail.error.message}</AlertDescription>
              </Alert>
            ) : detail.data ? (
              <DetailSession
                key={detail.data.id}
                data={detail.data}
                onDirtyChange={setDraftDirty}
                onNotice={setNotice}
              />
            ) : (
              <EmptyDetail />
            )}
          </div>
        </section>
      </div>

      {drawerOpen && <StudiesDialog onClose={() => setDrawerOpen(false)} />}
    </main>
  );
}

function Queue({
  changes,
  selectedId,
  replayPending,
  onReplay,
  onSelect,
  notice,
  replayError,
  onDrawer,
}: {
  changes: UseQueryResult<ChangeSummary[], Error>;
  selectedId: number | null;
  replayPending: boolean;
  onReplay: () => void;
  onSelect: (change: ChangeSummary) => void;
  notice: string | null;
  replayError?: string;
  onDrawer: () => void;
}) {
  return (
    <div className="sticky top-0 h-screen overflow-auto p-4 sm:p-5">
      <div className="mb-5 space-y-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Analyst workspace
          </p>
          <h1 className="text-2xl font-semibold">AstraZeneca changes</h1>
          <p className="text-sm text-muted-foreground">
            Prioritised synthetic public-record reconciliation.
          </p>
        </div>
        <div className="grid gap-2">
          <Button
            className="w-full"
            onClick={onReplay}
            disabled={replayPending}
          >
            {replayPending ? "Loading replay…" : "Load replay event"}
          </Button>
          <Button
            className="w-full lg:hidden"
            variant="outline"
            onClick={onDrawer}
          >
            Monitored studies
          </Button>
        </div>
        {notice && <StatusNote>{notice}</StatusNote>}
        {replayError && (
          <Alert variant="destructive">
            <AlertTitle>Replay could not be loaded</AlertTitle>
            <AlertDescription>{replayError}</AlertDescription>
          </Alert>
        )}
      </div>

      {changes.isPending ? (
        <LoadingRows label="Loading changes" />
      ) : changes.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Changes could not be loaded</AlertTitle>
          <AlertDescription>{changes.error.message}</AlertDescription>
        </Alert>
      ) : changes.data.length === 0 ? (
        <p className="rounded-xl border bg-card p-4 text-sm text-muted-foreground">
          No replay events yet. Load the replay to create the demonstration
          case.
        </p>
      ) : (
        <ol className="space-y-2" aria-label="Change queue">
          {changes.data.map((change) => (
            <li key={change.id}>
              <button
                className={`w-full rounded-xl border p-3 text-left transition hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 ${
                  selectedId === change.id
                    ? "border-primary bg-muted"
                    : "bg-card"
                }`}
                onClick={() => onSelect(change)}
              >
                <span className="mb-2 flex items-center justify-between gap-2">
                  <Badge
                    variant={
                      change.severity === "critical" ? "destructive" : "outline"
                    }
                  >
                    {change.severity.toUpperCase()}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {change.review_status.replaceAll("_", " ")}
                  </span>
                </span>
                <span className="block font-medium leading-snug">
                  {change.headline}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {change.nct_id} · {change.label}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function StudiesDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const studies = useQuery({
    queryKey: ["studies"],
    queryFn: fetchStudies,
    enabled: true,
  });

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    dialog.showModal();
    const handleClose = () => {
      returnFocusRef.current?.focus();
      onClose();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      className="m-0 ml-auto h-full max-h-none w-full max-w-2xl overflow-auto bg-background p-0 text-foreground shadow-xl backdrop:bg-black/30"
      aria-label="Live monitored studies"
      onCancel={(event) => {
        event.preventDefault();
        dialogRef.current?.close();
      }}
    >
      <div className="p-4 sm:p-6">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Monitored live studies</h2>
            <p className="text-sm text-muted-foreground">
              Secondary live ClinicalTrials.gov watchlist for AstraZeneca.
            </p>
          </div>
          <Button variant="outline" onClick={() => dialogRef.current?.close()}>
            Close
          </Button>
        </div>
        {studies.isPending ? (
          <LoadingRows label="Loading live studies" />
        ) : studies.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Studies could not be loaded</AlertTitle>
            <AlertDescription>{studies.error.message}</AlertDescription>
          </Alert>
        ) : (
          <StudyTable list={studies.data} />
        )}
      </div>
    </dialog>
  );
}

function WorkspaceHeader({
  onBack,
  onDrawer,
}: {
  onBack: () => void;
  onDrawer: () => void;
}) {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <Button className="lg:hidden" variant="outline" onClick={onBack}>
          ← Queue
        </Button>
        <div className="hidden lg:block">
          <p className="text-sm font-medium">Selected change detail</p>
          <p className="text-xs text-muted-foreground">
            Evidence, interpretation, verification draft, and audit history.
          </p>
        </div>
        <Button variant="outline" onClick={onDrawer}>
          Live studies
        </Button>
      </div>
    </header>
  );
}

function DetailSession({
  data,
  onDirtyChange,
  onNotice,
}: {
  data: ChangeDetail;
  onDirtyChange: (dirty: boolean) => void;
  onNotice: (notice: string) => void;
}) {
  const queryClient = useQueryClient();
  const [draftBody, setDraftBodyState] = useState(
    data.draft?.body ?? suggestedDraft(data),
  );
  const [lastSaved, setLastSaved] = useState<Draft | null>(data.draft);
  const [detailMessage, setDetailMessage] = useState<string | null>(null);
  const cleanBody = lastSaved?.body ?? suggestedDraft(data);
  const dirty = draftBody !== cleanBody;

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  function setDraftBody(value: string) {
    setDraftBodyState(value);
    onDirtyChange(value !== cleanBody);
  }

  function updateDraft(draft: Draft) {
    setLastSaved(draft);
    setDraftBodyState(draft.body);
    onDirtyChange(false);
    setDetailMessage(`Draft ${draft.status} at revision ${draft.revision}.`);
    onNotice(`Draft ${draft.status} at revision ${draft.revision}.`);
    queryClient.invalidateQueries({ queryKey: ["change", data.id] });
    queryClient.invalidateQueries({ queryKey: ["changes", "replay"] });
  }

  async function reloadCurrentDraft() {
    if (dirty && !window.confirm("Discard unsaved draft edits and reload?"))
      return;
    const fresh = await queryClient.fetchQuery({
      queryKey: ["change", data.id],
      queryFn: () => fetchChange(data.id),
    });
    setLastSaved(fresh.draft);
    setDraftBodyState(fresh.draft?.body ?? suggestedDraft(fresh));
    onDirtyChange(false);
    setDetailMessage("Current draft reloaded.");
    onNotice("Current draft reloaded.");
  }

  const generate = useMutation({
    mutationFn: () => generateDraft(data.id),
    onSuccess: updateDraft,
  });
  const save = useMutation({
    mutationFn: () =>
      saveDraft({
        id: data.id,
        body: draftBody,
        revision: lastSaved?.revision ?? 0,
      }),
    onSuccess: updateDraft,
  });
  const decision = useMutation({
    mutationFn: (status: Decision) =>
      decideDraft({
        id: data.id,
        status,
        revision: lastSaved?.revision ?? 0,
      }),
    onSuccess: updateDraft,
  });

  return (
    <Detail
      data={data}
      draftBody={draftBody}
      setDraftBody={setDraftBody}
      dirty={dirty}
      lastSaved={lastSaved}
      generate={() => generate.mutate()}
      save={() => save.mutate()}
      decide={(status) => decision.mutate(status)}
      busy={generate.isPending || save.isPending || decision.isPending}
      error={
        generate.error?.message ??
        save.error?.message ??
        decision.error?.message
      }
      reloadCurrentDraft={() => void reloadCurrentDraft()}
      detailMessage={detailMessage}
      onDetailMessage={setDetailMessage}
    />
  );
}

function Detail({
  data,
  draftBody,
  setDraftBody,
  dirty,
  lastSaved,
  generate,
  save,
  decide,
  busy,
  error,
  reloadCurrentDraft,
  detailMessage,
  onDetailMessage,
}: {
  data: ChangeDetail;
  draftBody: string;
  setDraftBody: (value: string) => void;
  dirty: boolean;
  lastSaved: Draft | null;
  generate: () => void;
  save: () => void;
  decide: (status: Decision) => void;
  busy: boolean;
  error?: string;
  reloadCurrentDraft: () => void;
  detailMessage: string | null;
  onDetailMessage: (message: string | null) => void;
}) {
  const currentStatus = dirty ? "proposed" : (lastSaved?.status ?? "proposed");
  const label = currentStatus === "approved" ? "Approved" : "Draft";
  const canSave = draftBody.trim() !== "" && (dirty || !lastSaved);
  const history = useMemo(() => data.draft_history ?? [], [data.draft_history]);

  return (
    <div className="space-y-5">
      <header className="rounded-2xl border bg-card p-5 shadow-sm">
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge variant="destructive">{data.severity.toUpperCase()}</Badge>
          <Badge variant="outline">{data.category}</Badge>
          <Badge variant="outline">{data.source}</Badge>
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">
          {data.headline}
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {data.nct_id} · {data.title}
        </p>
        {data.source_url && (
          <a
            href={data.source_url}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-block text-sm underline underline-offset-4"
          >
            Open ClinicalTrials.gov source
          </a>
        )}
      </header>

      <section
        className="grid gap-4 xl:grid-cols-2"
        aria-labelledby="evidence-heading"
      >
        <div className="xl:col-span-2">
          <h3 id="evidence-heading" className="text-lg font-semibold">
            Exact public-record evidence
          </h3>
          <p className="text-sm text-muted-foreground">
            Deterministic facts from before/after snapshots. AI cannot decide or
            alter these changes.
          </p>
        </div>
        {data.structured_diff.map((item) => (
          <article key={item.field} className="rounded-2xl border bg-card p-4">
            <h4 className="mb-3 font-medium">
              {item.field.replaceAll("_", " ")}
            </h4>
            <div className="grid gap-3 md:grid-cols-2">
              <Evidence label="Before" value={item.before} />
              <Evidence label="After" value={item.after} />
            </div>
          </article>
        ))}
      </section>

      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
        <h3 className="text-lg font-semibold">AI interpretation</h3>
        <p className="text-sm text-muted-foreground">
          Grounded only in the evidence above; decision-support, not a
          prediction.
        </p>
        {data.ai_analysis ? (
          <div className="mt-3 space-y-2 text-sm">
            <p className="font-medium">{data.ai_analysis.headline}</p>
            <p>{data.ai_analysis.summary}</p>
            <ul className="list-disc space-y-1 pl-5">
              {data.ai_analysis.possible_significance.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <Badge variant="outline">
              Confidence: {data.ai_analysis.confidence}
            </Badge>
          </div>
        ) : (
          <p className="mt-3 text-sm">
            AI explanation is unavailable. Evidence and draft review still work.
          </p>
        )}
      </section>

      <section
        className="rounded-2xl border bg-card p-5"
        aria-labelledby="draft-heading"
      >
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="draft-heading" className="text-lg font-semibold">
              Editable verification request
            </h3>
            <p className="text-sm text-muted-foreground">
              {label} · not sent externally · revision{" "}
              {lastSaved?.revision ?? 0}
              {dirty ? " · unsaved edits require fresh approval" : ""}
            </p>
          </div>
          <Badge
            variant={currentStatus === "approved" ? "secondary" : "outline"}
          >
            {currentStatus}
          </Badge>
        </div>
        {error && (
          <Alert className="mb-3" variant="destructive">
            <AlertTitle>Draft change was not saved</AlertTitle>
            <AlertDescription>
              {error} Reload the current draft if another update was saved.
            </AlertDescription>
          </Alert>
        )}
        {detailMessage && (
          <p
            className="mb-3 rounded-lg border bg-muted p-2 text-sm"
            role="status"
          >
            {detailMessage}
          </p>
        )}
        <textarea
          className="min-h-52 w-full rounded-xl border bg-background p-3 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
          value={draftBody}
          onChange={(event) => setDraftBody(event.target.value)}
          aria-label="Verification request draft"
          disabled={busy}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={generate}
            disabled={busy || dirty || Boolean(lastSaved)}
          >
            Generate AI draft
          </Button>
          <Button onClick={save} disabled={busy || !canSave}>
            Save draft
          </Button>
          <Button
            onClick={() => decide("approved")}
            disabled={
              busy || dirty || !lastSaved || lastSaved.status === "approved"
            }
          >
            Approve
          </Button>
          <Button
            variant="outline"
            onClick={() => decide("rejected")}
            disabled={
              busy || dirty || !lastSaved || lastSaved.status === "rejected"
            }
          >
            Reject
          </Button>
          <Button
            variant="outline"
            onClick={reloadCurrentDraft}
            disabled={busy}
          >
            Reload current draft
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              onDetailMessage(null);
              void copyText(
                exportRequestText({
                  body: draftBody,
                  label,
                  data,
                  revision: lastSaved?.revision ?? 0,
                  status: currentStatus,
                }),
              )
                .then(() => onDetailMessage(`${label} copied.`))
                .catch((error: unknown) =>
                  onDetailMessage(
                    error instanceof Error ? error.message : "Copy failed.",
                  ),
                );
            }}
          >
            Copy {label}
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              downloadText(
                exportRequestText({
                  body: draftBody,
                  label,
                  data,
                  revision: lastSaved?.revision ?? 0,
                  status: currentStatus,
                }),
                label,
              );
              onDetailMessage(`${label} downloaded.`);
            }}
          >
            Download {label}
          </Button>
        </div>
      </section>

      <section
        className="rounded-2xl border bg-card p-5"
        aria-labelledby="audit-heading"
      >
        <h3 id="audit-heading" className="text-lg font-semibold">
          Audit history
        </h3>
        <ol className="mt-3 space-y-3 border-l pl-5 text-sm">
          <li>
            <p className="font-medium">Change detected</p>
            <time className="text-muted-foreground">
              {formatTime(data.created_at)}
            </time>
          </li>
          {history.map((entry) => (
            <HistoryItem
              key={`${entry.event}-${entry.revision}-${entry.created_at}`}
              entry={entry}
            />
          ))}
          {data.audit_timeline.map((entry) => (
            <li key={entry.id}>
              <p className="font-medium">
                Legacy follow-up {entry.decision}: {entry.action_title}
              </p>
              <time className="text-muted-foreground">
                {formatTime(entry.created_at)}
              </time>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ReplayNotice() {
  return (
    <Alert className="mb-5">
      <AlertTitle>Synthetic replay workspace</AlertTitle>
      <AlertDescription>
        Demonstrates AstraZeneca public-record reconciliation using older/newer
        fixtures. It is clearly synthetic and not live registry history.
      </AlertDescription>
    </Alert>
  );
}

function EmptyDetail() {
  return (
    <div className="rounded-2xl border bg-card p-8 text-center text-sm text-muted-foreground">
      Select a queue item, or load the replay event to start.
    </div>
  );
}

function LoadingDetail() {
  return (
    <div className="space-y-3" aria-label="Loading change detail">
      {Array.from({ length: 5 }, (_, row) => (
        <Skeleton key={row} className="h-24 w-full" />
      ))}
    </div>
  );
}

function LoadingRows({ label }: { label: string }) {
  return (
    <div className="space-y-2" aria-label={label}>
      {Array.from({ length: 5 }, (_, row) => (
        <Skeleton key={row} className="h-16 w-full" />
      ))}
    </div>
  );
}

function Evidence({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <pre className="overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function HistoryItem({ entry }: { entry: DraftHistoryEntry }) {
  return (
    <li>
      <details>
        <summary className="cursor-pointer font-medium">
          Draft {entry.event} · revision {entry.revision} · {entry.status}
        </summary>
        <time className="text-muted-foreground">
          {formatTime(entry.created_at)}
        </time>
        <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-xs">
          {entry.body}
        </pre>
      </details>
    </li>
  );
}

function StatusNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border bg-card p-3 text-sm">{children}</p>;
}

function suggestedDraft(data?: ChangeDetail) {
  if (!data) return "";
  const evidence = data.structured_diff
    .map(
      (item) =>
        `${item.field}: ${JSON.stringify(item.before)} → ${JSON.stringify(item.after)}`,
    )
    .join("\n");
  return `Manual template—not AI generated. Synthetic replay for AstraZeneca public-record reconciliation; not historical registry evidence.\n\nPlease verify the public ClinicalTrials.gov record for ${data.nct_id} (${data.title}).\n\nObserved change:\n${evidence}\n\nConfirm whether this public-record change affects the monitoring note. This draft is not sent externally.`;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function exportRequestText({
  body,
  label,
  data,
  revision,
  status,
}: {
  body: string;
  label: string;
  data: ChangeDetail;
  revision: number;
  status: DraftStatus;
}) {
  const appendix = data.structured_diff
    .map(
      (item) =>
        `- ${item.field}\n  Before: ${JSON.stringify(item.before)}\n  After: ${JSON.stringify(item.after)}`,
    )
    .join("\n");
  const exportStatus = status === "approved" ? "Approved—not sent" : "Draft";
  return `${label}—not sent\nRevision: ${revision}\nStatus: ${exportStatus}\nStudy: ${data.nct_id} — ${data.title}\nProvenance: Synthetic replay for AstraZeneca public-record reconciliation; not historical registry evidence.\n\n${body}\n\nEvidence appendix\n${appendix}`;
}

async function copyText(text: string) {
  if (!navigator.clipboard?.writeText) {
    throw new Error(
      "Copy is unavailable in this browser. Use Download instead.",
    );
  }
  await navigator.clipboard.writeText(text);
}

function downloadText(text: string, label: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${label.toLowerCase()}-verification-request.txt`;
  link.click();
  URL.revokeObjectURL(url);
}
