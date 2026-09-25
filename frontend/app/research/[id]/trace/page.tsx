import { TraceContent } from "./TraceContent";

export default async function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TraceContent sessionId={id} />;
}
