import { AnalystWorkspace } from "@/components/analyst-workspace";

export default async function ChangePage({
  params,
}: PageProps<"/changes/[id]">) {
  const { id } = await params;
  return <AnalystWorkspace initialId={Number(id)} />;
}
