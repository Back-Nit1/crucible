import Link from "next/link";
import { PageHeader } from "@/components/ui/page-header";

export default function NotFound() {
  return (
    <div className="py-16">
      <PageHeader
        eyebrow="404 / route"
        title="This trace does not exist."
        description="The requested Crucible view is unavailable or the identifier is no longer present."
      />
      <Link
        href="/world"
        className="inline-flex rounded-lg bg-emerald-200 px-4 py-2 text-sm font-semibold text-slate-950"
      >
        Return to World
      </Link>
    </div>
  );
}
