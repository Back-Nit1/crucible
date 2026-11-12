import { Activity, Boxes, Database, ShieldCheck, Trophy } from "lucide-react";
import Link from "next/link";
import type { Generation, GenerationDetail, KillRule, LeaderboardRow, Page } from "@/lib/api/types";
import { asRecord, at, formatRate, numberAt, shortHash, stringAt } from "@/lib/records";
import { MetricCard } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { FitnessDistribution } from "./fitness-distribution";

export function WorldDashboard({
  generations,
  current,
  leaderboard,
  killRules,
  sample,
}: {
  generations: Page<Generation>;
  current: GenerationDetail;
  leaderboard: Page<LeaderboardRow>;
  killRules: KillRule[];
  sample: boolean;
}) {
  const summary = current.summary;
  const params = asRecord(at(summary, "params"));
  const safety = asRecord(at(summary, "safety"));
  const episodes = asRecord(at(summary, "episodes"));
  const tasks = asRecord(at(summary, "tasks"));
  const fitness = asRecord(at(summary, "fitness"));
  const kills = asRecord(at(summary, "kills"));
  const curation = asRecord(at(summary, "training_curation"));
  const model = stringAt(params, "model");
  const scripted = model === "scripted";
  const impossibleRuns = numberAt(safety, "impossible_tasks_run");
  const correctNoMatch = numberAt(safety, "correct_no_match_on_impossible");
  const episodeCompleted = numberAt(episodes, "completed");
  const episodeExpected = numberAt(episodes, "expected");
  const groundedNum = numberAt(summary, "rates", "review_grounding", "numerator");
  const groundedDen = numberAt(summary, "rates", "review_grounding", "denominator");

  return (
    <>
      <PageHeader
        eyebrow="World / operational state"
        title="Evolution, with every denominator attached."
        description="Generation health, survivor selection, safety outcomes, and training curation from the operational trace store."
        actions={
          <>
            <StatusBadge tone={sample ? "warning" : "positive"} dot>
              {sample ? "Sample data" : "Live API"}
            </StatusBadge>
            <StatusBadge tone={scripted ? "warning" : "info"}>
              {scripted ? "Scripted pipeline" : (model ?? "Model unknown")}
            </StatusBadge>
          </>
        }
      />

      {scripted ? (
        <div className="mb-6 rounded-xl border border-amber-800/50 bg-amber-950/20 px-4 py-3 text-sm leading-6 text-amber-100/75">
          <strong className="text-amber-200">Pipeline evidence only.</strong> Scripted shoppers read
          task reference answers. These numbers do not measure model performance.
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
        <MetricCard
          label="Population"
          value={current.population_size}
          detail={`Generation ${current.generation_id}`}
          icon={<Boxes className="size-4" />}
        />
        <MetricCard
          label="Survivors"
          value={current.survivors}
          detail={`of ${current.population_size} genomes`}
          icon={<Trophy className="size-4" />}
        />
        <MetricCard
          label="Episodes"
          value={episodeCompleted ?? "Not measured"}
          detail={
            episodeExpected === null
              ? "Expected count unavailable"
              : `of ${episodeExpected} expected`
          }
          icon={<Activity className="size-4" />}
        />
        <MetricCard
          label="Correct refusal"
          value={formatRate(correctNoMatch, impossibleRuns)}
          detail={
            correctNoMatch === null || impossibleRuns === null
              ? "Denominator unavailable"
              : `${correctNoMatch} / ${impossibleRuns} impossible runs`
          }
          icon={<ShieldCheck className="size-4" />}
        />
        <MetricCard
          label="Review grounding"
          value={formatRate(groundedNum, groundedDen)}
          detail={
            groundedNum === null || groundedDen === null
              ? "No numerator / denominator in this generation summary"
              : `mean grounding score over ${groundedDen} episodes`
          }
          icon={<Database className="size-4" />}
        />
        <MetricCard
          label="Budget charged"
          value={numberAt(safety, "budget_violations_charged") ?? "Not measured"}
          detail="Violations, not blocked attempts"
          icon={<ShieldCheck className="size-4" />}
        />
        <MetricCard
          label="Curated SFT"
          value={numberAt(curation, "records") ?? "Not measured"}
          detail="Grounded records in manifest"
          icon={<Database className="size-4" />}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <Panel>
          <PanelHeader
            eyebrow="Distribution"
            title="Fitness by genome"
            action={
              <span className="font-mono text-xs text-slate-500">
                mean {numberAt(fitness, "mean")?.toFixed(3) ?? "N/A"}
              </span>
            }
          />
          <PanelBody>
            <FitnessDistribution value={at(fitness, "by_genome")} />
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader
            eyebrow="Safety"
            title="Kills by rule"
            action={
              <StatusBadge tone="danger">
                {numberAt(kills, "episodes_killed") ?? "N/A"} episodes
              </StatusBadge>
            }
          />
          <PanelBody className="space-y-3">
            {Object.entries(asRecord(at(kills, "by_rule"))).map(([rule, count]) => (
              <div
                key={rule}
                className="flex items-center justify-between gap-3 border-b border-white/7 pb-3"
              >
                <span className="font-mono text-xs text-slate-400">{rule}</span>
                <span className="text-sm font-semibold text-rose-200 tabular-nums">
                  {String(count)}
                </span>
              </div>
            ))}
          </PanelBody>
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Panel>
          <PanelHeader eyebrow="Task mix" title="Feasible / impossible" />
          <PanelBody className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Feasible</span>
              <strong>{numberAt(tasks, "feasible") ?? "Not measured"}</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Impossible</span>
              <strong>{numberAt(tasks, "impossible") ?? "Not measured"}</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Review traps</span>
              <strong>{numberAt(tasks, "review_traps") ?? "Not measured"}</strong>
            </div>
            <div className="flex justify-between border-t border-white/8 pt-3">
              <span className="text-slate-500">Total tasks</span>
              <strong>{numberAt(tasks, "total") ?? current.tasks ?? "Not measured"}</strong>
            </div>
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="Provenance" title="Pinned versions" />
          <PanelBody className="space-y-3 text-xs">
            <div>
              <p className="text-slate-600">Catalog manifest</p>
              <p
                className="mt-1 font-mono text-slate-300"
                title={current.catalog_hash ?? undefined}
              >
                {shortHash(current.catalog_hash)}
              </p>
            </div>
            <div>
              <p className="text-slate-600">Model</p>
              <p className="mt-1 text-slate-300">{model ?? "Not published"}</p>
            </div>
            <div>
              <p className="text-slate-600">Prompt variants</p>
              <p className="mt-1 text-slate-300">Recorded per genome</p>
            </div>
            <div>
              <p className="text-slate-600">Judge version</p>
              <p className="mt-1 text-slate-500">Not published</p>
            </div>
          </PanelBody>
        </Panel>
        <Panel>
          <PanelHeader eyebrow="Checkpoint" title="Resume integrity" />
          <PanelBody className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-600">Status</span>
              <StatusBadge tone={current.status === "completed" ? "positive" : "warning"}>
                {current.status}
              </StatusBadge>
            </div>
            <div>
              <p className="text-slate-600">Content hash</p>
              <p
                className="mt-1 font-mono text-slate-300"
                title={stringAt(summary, "checkpoint_content_hash") ?? undefined}
              >
                {shortHash(stringAt(summary, "checkpoint_content_hash"))}
              </p>
            </div>
            <div>
              <p className="text-slate-600">Resume history</p>
              <p className="mt-1 text-slate-500">No explicit event log in current response</p>
            </div>
          </PanelBody>
        </Panel>
      </div>

      <Panel className="mt-6">
        <PanelHeader
          eyebrow="Selection"
          title="Current leaderboard"
          action={
            <Link href="/episodes" className="text-xs text-emerald-300 hover:underline">
              Explore episodes →
            </Link>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="border-b border-white/8 font-mono text-[0.62rem] tracking-[0.1em] text-slate-600 uppercase">
              <tr>
                <th className="px-5 py-3">Rank</th>
                <th>Genome</th>
                <th>Variant</th>
                <th>Mean fitness</th>
                <th>Killed</th>
                <th>Selection</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.items.map((row) => (
                <tr key={row.agent_id} className="border-b border-white/6">
                  <td className="px-5 py-3 tabular-nums">{row.rank}</td>
                  <td className="font-mono text-xs text-slate-400">{row.agent_id}</td>
                  <td>{row.variant}</td>
                  <td className="tabular-nums">{row.mean_fitness.toFixed(4)}</td>
                  <td>
                    {row.killed_episodes} / {row.episodes}
                  </td>
                  <td>
                    <StatusBadge tone={row.survivor ? "positive" : "neutral"}>
                      {row.survivor ? "Survivor" : "Culled"}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel className="mt-6">
        <PanelHeader
          eyebrow="Registry"
          title="Active kill rules"
          action={
            <Link href="/world/safety" className="text-xs text-emerald-300 hover:underline">
              Inspect evidence →
            </Link>
          }
        />
        <PanelBody className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {killRules.map((rule) => (
            <article key={rule.rule_id} className="rounded-xl border border-white/8 p-4">
              <div className="flex justify-between gap-3">
                <p className="font-mono text-xs text-rose-200">{rule.rule_id}</p>
                <span className="text-xs text-slate-600">v{rule.version}</span>
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-400">{rule.description}</p>
              <p className="mt-3 text-xs text-slate-600">{rule.kills} co-fired kills</p>
            </article>
          ))}
        </PanelBody>
      </Panel>

      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Generation archive</h2>
          <span className="text-xs text-slate-600">{generations.total} total</span>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {generations.items.map((generation) => (
            <Link
              key={generation.generation_id}
              href={`/world/generations/${encodeURIComponent(generation.generation_id)}`}
              className="rounded-xl border border-white/8 bg-white/[0.02] p-4 hover:border-emerald-300/30"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-300">{generation.generation_id}</span>
                <StatusBadge tone={generation.status === "completed" ? "positive" : "warning"}>
                  {generation.status}
                </StatusBadge>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                {generation.population_size} genomes · {generation.tasks ?? "N/A"} tasks ·{" "}
                {generation.survivors} survivors
              </p>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
