import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "..");
const sourceRoot = path.resolve(webRoot, "../docs/api/samples");
const output = path.resolve(webRoot, "src/generated/samples.json");
// Large: kept out of samples.json so it never rides in the shared client bundle; loaded on demand.
const snapshotFile = "world_generation_snapshot.json";
const snapshotOutput = path.resolve(webRoot, "src/generated/snapshot-sample.json");
const files = [
  "agent_confirm_not_approved.json",
  "agent_confirm_refused_no_confirmation.json",
  "agent_confirm_stale_quote.json",
  "agent_model_unavailable.json",
  "agent_run_no_match.json",
  "agent_run_poll.json",
  "agent_run_receipt.json",
  "agent_run_started.json",
  "health.json",
  "models_checkpoints.json",
  "models_evaluations.json",
  "payments_ledger.json",
  "world_episode_detail.json",
  "world_episode_detail_killed.json",
  "world_episodes.json",
  "world_generation_detail.json",
  "world_generations.json",
  "world_kill_rules.json",
  "world_kills.json",
  "world_leaderboard.json",
];

const fixtures = {};
for (const file of files) {
  const payload = JSON.parse(await readFile(path.join(sourceRoot, file), "utf8"));
  const body = payload.body ?? payload.response;
  if (body === undefined || !("request" in payload) || !("status" in payload)) {
    throw new Error(`${file} is not an API sample envelope`);
  }
  fixtures[file.replace(/\.json$/, "")] = { ...payload, body };
}

await mkdir(path.dirname(output), { recursive: true });
await writeFile(
  output,
  `${JSON.stringify({ source: "docs/api/samples", fixtures })}\n`,
  "utf8",
);

const snapshot = JSON.parse(await readFile(path.join(sourceRoot, snapshotFile), "utf8"));
if (snapshot.body === undefined) throw new Error(`${snapshotFile} is not an API sample envelope`);
await writeFile(snapshotOutput, `${JSON.stringify(snapshot)}\n`, "utf8");
