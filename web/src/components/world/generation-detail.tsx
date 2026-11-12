import { ArrowLeft, GitBranch, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import type { GenerationDetail } from "@/lib/api/types";
import { asRecord, at, numberAt, shortHash, stringArrayAt, stringAt } from "@/lib/records";
import { MetricCard } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";

export function GenerationDetailView({
  generation,
  sample,
}: {
  generation: GenerationDetail;
  sample: boolean;
}) {
  const summary = generation.summary;
  const population = at(summary, "population");
  const genomes = Array.isArray(population) ? population.map(asRecord) : [];
  const survivors = new Set(stringArrayAt(summary, "survivors"));
  const nextPopulation = stringArrayAt(summary, "next_population");
  const tasks = asRecord(at(summary, "tasks"));
  const kills = asRecord(at(summary, "kills"));
  const curation = asRecord(at(summary, "training_curation"));
  const proposals = at(summary, "loophole_hunter_proposals");
  const loopholes = Array.isArray(proposals) ? proposals.map(asRecord) : [];
  const model = stringAt(asRecord(at(summary, "params")), "model");

  return (
    <>
      <Link
        href="/world"
        className="mb-5 inline-flex items-center gap-2 text-xs text-slate-500 hover:text-slate-200"
      >
        <ArrowLeft className="size-3.5" /> World overview
      </Link>
      <PageHeader
        eyebrow="World / generation detail"
        title={generation.generation_id}
        description="Population lineage, task composition, safety outcomes, checkpoint identity, and survivor curation for this immutable run."
        actions={
          <>
            <StatusBadge tone={sample ? "warning" : "positive"}>
              {sample ? "Sample data" : "Live API"}
            </StatusBadge>
            <StatusBadge tone={model === "scripted" ? "warning" : "info"}>
              {model === "scripted" ? "Scripted pipeline" : (model ?? "Model unknown")}
            </StatusBadge>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <MetricCard label="Population" value={generation.population_size} />
        <MetricCard label="Survivors" value={generation.survivors} />
        <MetricCard label="Tasks" value={generation.tasks ?? "Not measured"} />
        <MetricCard label="Killed agents" value={stringArrayAt(kills, "killed_agents").length} />
        <MetricCard
          label="Curated traces"
          value={numberAt(curation, "records") ?? "Not measured"}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <Panel>
          <PanelHeader
            eyebrow="Lineage"
            title="Genomes and survivor selection"
            action={<GitBranch className="size-4 text-slate-500" />}
          />
          <PanelBody className="space-y-3">
            {genomes.map((genome) => {
              const id = stringAt(genome, "id") ?? "unknown";
              const parent = stringAt(genome, "parent") ?? stringAt(genome, "parent_id");
              return (
                <article
                  key={id}
                  className="grid gap-3 rounded-xl border border-white/8 p-4 sm:grid-cols-[1fr_auto] sm:items-center"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-mono text-xs text-slate-200">{id}</p>
                      {survivors.has(id) ? (
                        <StatusBadge tone="positive">Survivor</StatusBadge>
                      ) : (
                        <StatusBadge>Culled / killed</StatusBadge>
                      )}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      {stringAt(genome, "variant") ?? "Variant not published"}
                    </p>
                    {parent ? (
                      <p className="mt-1 font-mono text-[0.62rem] text-cyan-300/60">
                        parent {parent}
                      </p>
                    ) : (
                      <p className="mt-1 text-[0.65rem] text-slate-600">founder genome</p>
                    )}
                  </div>
                  <span className="text-xs text-slate-600">
                    {nextPopulation.includes(id) ? "retained → next" : "not retained"}
                  </span>
                </article>
              );
            })}
            <div className="border-t border-white/8 pt-4">
              <p className="font-mono text-[0.62rem] tracking-[0.1em] text-slate-600 uppercase">
                Next population / mutations
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {nextPopulation.map((id) => (
                  <span
                    key={id}
                    className="rounded-full border border-white/8 px-2.5 py-1 font-mono text-[0.62rem] text-slate-400"
                  >
                    {id}
                    {genomes.some((genome) => stringAt(genome, "id") === id)
                      ? " · retained"
                      : " · mutated child"}
                  </span>
                ))}
              </div>
              <p className="mt-3 text-xs text-slate-600">
                Mutation parameters are not included in the current generation response.
              </p>
            </div>
          </PanelBody>
        </Panel>
        <div className="space-y-6">
          <Panel>
            <PanelHeader eyebrow="Task bank" title="Mix and denominators" />
            <PanelBody className="space-y-3 text-sm">
              {Object.entries(tasks)
                .filter(([, value]) => typeof value !== "object")
                .map(([key, value]) => (
                  <div
                    key={key}
                    className="flex justify-between gap-3 border-b border-white/7 pb-2"
                  >
                    <span className="text-slate-500">{key.replaceAll("_", " ")}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
              <div>
                <p className="mt-4 font-mono text-[0.62rem] text-slate-600 uppercase">By split</p>
                {Object.entries(asRecord(at(tasks, "by_split"))).map(([key, value]) => (
                  <p key={key} className="mt-2 flex justify-between text-xs">
                    <span>{key}</span>
                    <span>{String(value)}</span>
                  </p>
                ))}
              </div>
            </PanelBody>
          </Panel>
          <Panel>
            <PanelHeader eyebrow="Checkpoint" title="Resume state" />
            <PanelBody className="space-y-3 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-600">Status</span>
                <span>{generation.status}</span>
              </div>
              <div>
                <p className="text-slate-600">Checkpoint hash</p>
                <p
                  className="mt-1 font-mono"
                  title={stringAt(summary, "checkpoint_content_hash") ?? undefined}
                >
                  {shortHash(stringAt(summary, "checkpoint_content_hash"))}
                </p>
              </div>
              <p className="text-slate-500">
                Completed {numberAt(asRecord(at(summary, "episodes")), "completed") ?? "N/A"} of{" "}
                {numberAt(asRecord(at(summary, "episodes")), "expected") ?? "N/A"} genome/task
                pairs. Explicit resume events are not in this API response.
              </p>
            </PanelBody>
          </Panel>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            eyebrow="Loophole Hunter"
            title="Candidate rule timeline"
            action={<ShieldAlert className="size-4 text-amber-300" />}
          />
          <PanelBody className="space-y-4">
            {loopholes.length ? (
              loopholes.map((proposal) => (
                <article
                  key={stringAt(proposal, "rule_id") ?? JSON.stringify(proposal)}
                  className="border-l border-amber-500/40 pl-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-mono text-xs text-amber-200">
                      {stringAt(proposal, "rule_id") ?? "Unnamed rule"}
                    </p>
                    <StatusBadge tone="warning">
                      {stringAt(proposal, "state") ?? "state unknown"}
                    </StatusBadge>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    Affected episodes: {numberAt(proposal, "episodes") ?? "Not published"}.
                    Candidate rules are not silently enabled.
                  </p>
                </article>
              ))
            ) : (
              <p className="text-sm text-slate-500">No candidate rules were published.</p>
            )}
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader
            eyebrow="Training curation"
            title="Survivor trace manifest"
            action={<Sparkles className="size-4 text-emerald-300" />}
          />
          <PanelBody className="space-y-4 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Records</span>
              <strong>{numberAt(curation, "records") ?? "Not measured"}</strong>
            </div>
            <div>
              <p className="text-xs text-slate-600">Manifest content hash</p>
              <p className="mt-1 break-all font-mono text-xs text-slate-300">
                {stringAt(curation, "manifest_content_hash") ?? "Not published"}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-600">Exclusions</p>
              {Object.entries(asRecord(at(curation, "exclusions"))).map(([reason, count]) => (
                <p key={reason} className="mt-2 flex justify-between text-xs">
                  <span>{reason.replaceAll("_", " ")}</span>
                  <span>{String(count)}</span>
                </p>
              ))}
            </div>
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}
