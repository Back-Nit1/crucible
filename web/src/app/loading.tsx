import { LoadingBlock } from "@/components/ui/data-state";

export default function Loading() {
  return (
    <div className="grid gap-5 lg:grid-cols-2" aria-label="Loading page">
      <div className="rounded-2xl border border-white/8 bg-white/[0.02]">
        <LoadingBlock />
      </div>
      <div className="rounded-2xl border border-white/8 bg-white/[0.02]">
        <LoadingBlock />
      </div>
    </div>
  );
}
