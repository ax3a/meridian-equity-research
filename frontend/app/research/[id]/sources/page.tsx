import { SourcesView } from "./SourcesView";

export default async function SourcesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SourcesView sessionId={id} />;
}
