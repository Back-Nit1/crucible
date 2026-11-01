import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "..");
const sourceRoot = path.resolve(webRoot, "../docs/api/samples");
const output = path.resolve(webRoot, "src/generated/samples.json");
const files = [
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
  if (!("body" in payload) || !("request" in payload) || !("status" in payload)) {
    throw new Error(`${file} is not an API sample envelope`);
  }
  fixtures[file.replace(/\.json$/, "")] = payload;
}

await mkdir(path.dirname(output), { recursive: true });
await writeFile(
  output,
  `${JSON.stringify({ source: "docs/api/samples", fixtures }, null, 2)}\n`,
  "utf8",
);
