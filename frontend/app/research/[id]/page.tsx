import { LiveRunView } from "./LiveRunView";

export default async function LiveRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <LiveRunView sessionId={id} />;
}
