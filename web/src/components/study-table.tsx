import type { StudyList } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isStoppedStatus, phaseLabel, statusLabel } from "@/lib/labels";

export function StudyTable({ list }: { list: StudyList }) {
  return (
    <>
      {list.skipped > 0 ? (
        <p className="text-sm text-muted-foreground">
          {list.skipped} {list.skipped === 1 ? "study" : "studies"} could not be
          read and {list.skipped === 1 ? "is" : "are"} hidden.
        </p>
      ) : list.studies.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No studies found for AstraZeneca as lead sponsor.
        </p>
      ) : null}
      {list.studies.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>NCT ID</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Phase</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last update</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.studies.map((study) => (
              <TableRow key={study.nct_id}>
                <TableCell className="font-mono">
                  <a
                    className="underline underline-offset-4"
                    href={`https://clinicaltrials.gov/study/${study.nct_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {study.nct_id}
                  </a>
                </TableCell>
                <TableCell className="min-w-72 whitespace-normal">
                  {study.title}
                </TableCell>
                <TableCell>{phaseLabel(study.phases)}</TableCell>
                <TableCell>
                  <Badge
                    variant={
                      isStoppedStatus(study.overall_status)
                        ? "destructive"
                        : "secondary"
                    }
                  >
                    {statusLabel(study.overall_status)}
                  </Badge>
                </TableCell>
                <TableCell>{study.last_update_posted}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
