import { LedgerGrid } from "@/components/payments/ledger-grid";
import { ErrorState, EmptyState } from "@/components/ui/data-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { serverApi } from "@/lib/api/server";
import { publicEnv } from "@/lib/env";

export default async function PaymentsPage() {
  let ledger = null;
  let message = "The ledger could not be loaded.";
  try {
    ledger = await serverApi().ledger();
  } catch (error) {
    message = error instanceof Error ? error.message : message;
  }
  if (!ledger) return <ErrorState title="Payment ledger unavailable" message={message} />;
  return (
    <>
      <PageHeader eyebrow="Payments / audit ledger" title="Mock and sandbox events, never production money." description="Proposal and capture references recorded by the operational world. Secret values and buyer credentials are never part of this response." actions={<><StatusBadge tone={publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "warning" : "positive"}>{publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "Sample data" : "Live API"}</StatusBadge><StatusBadge tone="warning">Mock / sandbox only</StatusBadge></>} />
      <div className="mb-5 rounded-xl border border-amber-800/40 bg-amber-950/15 px-4 py-3 text-xs leading-5 text-amber-100/70">The current ledger contract publishes mode, episode, event, product, amount, and opaque references. Currency, latency, explicit confirmation, and idempotency result are shown as unavailable—not reconstructed.</div>
      {ledger.items.length ? <LedgerGrid rows={ledger.items} /> : <Panel><EmptyState title="No ledger events" message="No mock or sandbox payment events were published." /></Panel>}
    </>
  );
}
