import {
  BookOpenCheck,
  CheckCircle2,
  GitCompareArrows,
  Search,
  ShieldCheck,
  ShoppingBag,
} from "lucide-react";
import type { ReplayStep } from "@/lib/api/types";

const icons = {
  parse_intent: ShieldCheck,
  search_catalog: Search,
  get_product: ShoppingBag,
  compare: GitCompareArrows,
  get_reviews: BookOpenCheck,
  summarize_review_evidence: BookOpenCheck,
  propose_purchase: ShoppingBag,
  confirm_and_pay: CheckCircle2,
  report_no_match: ShieldCheck,
};

export function ResearchTimeline({ steps }: { steps: ReplayStep[] }) {
  return (
    <ol className="relative space-y-1" aria-label="Research progress">
      {steps.map((step, index) => {
        const Icon = icons[step.tool as keyof typeof icons] ?? CheckCircle2;
        return (
          <li key={`${step.sequence}-${step.tool}`} className="group relative grid grid-cols-[2rem_1fr] gap-3 pb-5">
            {index < steps.length - 1 ? (
              <span className="absolute top-8 bottom-0 left-[0.96rem] w-px bg-white/8" aria-hidden="true" />
            ) : null}
            <span
              className={`z-10 grid size-8 place-items-center rounded-full border ${
                step.error_code
                  ? "border-rose-700 bg-rose-950 text-rose-300"
                  : "border-emerald-700/60 bg-emerald-950/70 text-emerald-300"
              }`}
            >
              <Icon className="size-3.5" aria-hidden="true" />
            </span>
            <div className="pt-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-mono text-xs font-medium tracking-[0.04em] text-slate-200">
                  {step.tool}
                </p>
                <span className="font-mono text-[0.62rem] text-slate-600">#{step.sequence}</span>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">{step.result_summary}</p>
              {step.error_code ? (
                <p className="mt-1 font-mono text-[0.65rem] text-rose-300">{step.error_code}</p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
