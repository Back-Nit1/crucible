"use client";

import { Download, Filter, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  AllCommunityModule,
  type ColDef,
  type GridApi,
  type GridReadyEvent,
  type IDatasource,
  type IGetRowsParams,
} from "ag-grid-community";
import { AgGridProvider, AgGridReact } from "ag-grid-react";
import { CrucibleApi } from "@/lib/api/client";
import type { Episode, EpisodeQuery } from "@/lib/api/types";
import { publicEnv } from "@/lib/env";
import { StatusBadge } from "@/components/ui/status-badge";
import { crucibleGridTheme } from "@/components/grid/theme";

type Filters = {
  generation_id: string;
  agent_id: string;
  split: string;
  category: string;
  killed: "" | "true" | "false";
  kill_rule_id: string;
  min_fitness: string;
  max_fitness: string;
};

const initialFilters: Filters = {
  generation_id: "",
  agent_id: "",
  split: "",
  category: "",
  killed: "",
  kill_rule_id: "",
  min_fitness: "",
  max_fitness: "",
};

export function toEpisodeQuery(
  filters: Filters,
  params: Pick<IGetRowsParams, "startRow" | "endRow" | "sortModel">,
): EpisodeQuery {
  const sort = params.sortModel[0];
  const sortable = new Set([
    "fitness",
    "episode_id",
    "agent_id",
    "generation_id",
    "category",
    "killed",
  ]);
  const field = sort && sortable.has(sort.colId) ? sort.colId : "fitness";
  return {
    generation_id: filters.generation_id || undefined,
    agent_id: filters.agent_id || undefined,
    split: filters.split || undefined,
    category: filters.category || undefined,
    killed: filters.killed ? filters.killed === "true" : undefined,
    kill_rule_id: filters.kill_rule_id || undefined,
    min_fitness: filters.min_fitness ? Number(filters.min_fitness) : undefined,
    max_fitness: filters.max_fitness ? Number(filters.max_fitness) : undefined,
    sort: `${sort?.sort === "asc" ? "" : "-"}${field}` as EpisodeQuery["sort"],
    offset: params.startRow,
    limit: Math.min(200, params.endRow - params.startRow),
  };
}

function EpisodeLink({ value }: { value?: string }) {
  return value ? (
    <Link
      href={`/episodes/${encodeURIComponent(value)}`}
      className="font-mono text-[0.68rem] text-emerald-300 hover:underline"
    >
      {value}
    </Link>
  ) : null;
}

function KilledCell({ value }: { value?: boolean }) {
  return (
    <StatusBadge tone={value ? "danger" : "positive"}>{value ? "Killed" : "Clean"}</StatusBadge>
  );
}

export function EpisodeGrid() {
  const api = useMemo(
    () => new CrucibleApi(publicEnv.NEXT_PUBLIC_API_BASE_URL, publicEnv.NEXT_PUBLIC_DATA_MODE),
    [],
  );
  const gridApi = useRef<GridApi<Episode> | null>(null);
  const [draft, setDraft] = useState(initialFilters);
  const [applied, setApplied] = useState(initialFilters);
  const [error, setError] = useState<string | null>(null);

  const columns = useMemo<ColDef<Episode>[]>(
    () => [
      {
        field: "episode_id",
        headerName: "Episode ID",
        pinned: "left",
        minWidth: 280,
        cellRenderer: EpisodeLink,
      },
      { field: "generation_id", headerName: "Generation", minWidth: 190 },
      { field: "agent_id", headerName: "Agent / genome", minWidth: 190 },
      { field: "split", width: 105 },
      { field: "category", minWidth: 190 },
      { headerName: "Feasibility", valueGetter: () => "Not exposed", sortable: false, width: 125 },
      {
        field: "fitness",
        width: 105,
        valueFormatter: ({ value }) =>
          value === null || value === undefined ? "Not scored" : Number(value).toFixed(4),
      },
      { field: "killed", pinned: "right", width: 105, cellRenderer: KilledCell },
      {
        field: "kill_rule_id",
        headerName: "Kill rule",
        minWidth: 205,
        sortable: false,
        valueFormatter: ({ value }) => value ?? "—",
      },
      { headerName: "Grounded", valueGetter: () => "Not exposed", sortable: false, width: 115 },
      {
        headerName: "Outcome",
        field: "termination",
        width: 125,
        valueFormatter: ({ value }) =>
          value === "no_match" ? "No match" : value === "success" ? "Purchase" : value,
      },
      { headerName: "Latency", valueGetter: () => "Not exposed", sortable: false, width: 115 },
      { headerName: "Model", valueGetter: () => "Not exposed", sortable: false, width: 125 },
      { field: "tool_call_count", headerName: "Tools", width: 90, sortable: false },
      {
        headerName: "Review IDs",
        valueGetter: ({ data }) => data?.review_ids_cited.length ?? 0,
        sortable: false,
        width: 105,
      },
    ],
    [],
  );

  const makeDatasource = useCallback(
    (filters: Filters): IDatasource => ({
      getRows: async (params: IGetRowsParams) => {
        setError(null);
        try {
          const page = await api.episodes(toEpisodeQuery(filters, params));
          const lastRow =
            publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? page.items.length : page.total;
          params.successCallback(page.items, lastRow);
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "Episode data could not be loaded.");
          params.failCallback();
        }
      },
    }),
    [api],
  );

  function onReady(event: GridReadyEvent<Episode>) {
    gridApi.current = event.api;
    event.api.setGridOption("datasource", makeDatasource(applied));
  }

  function applyFilters() {
    setApplied(draft);
    gridApi.current?.setGridOption("datasource", makeDatasource(draft));
  }

  function resetFilters() {
    setDraft(initialFilters);
    setApplied(initialFilters);
    gridApi.current?.setGridOption("datasource", makeDatasource(initialFilters));
  }

  return (
    <div className="space-y-4">
      <section
        className="rounded-2xl border border-white/9 bg-[#0b1514]/90 p-4"
        aria-label="Episode filters"
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          {(["generation_id", "agent_id", "category", "kill_rule_id"] as const).map((key) => (
            <label key={key} className="text-xs text-slate-500">
              <span>{key.replaceAll("_", " ")}</span>
              <input
                value={draft[key]}
                onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))}
                className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-slate-200"
              />
            </label>
          ))}
          <label className="text-xs text-slate-500">
            <span>split</span>
            <select
              value={draft.split}
              onChange={(event) => setDraft((value) => ({ ...value, split: event.target.value }))}
              className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#0b1514] px-3 py-2 text-slate-200"
            >
              <option value="">All</option>
              <option value="train">Train</option>
              <option value="val">Validation</option>
              <option value="test">Test</option>
              <option value="held_out_category">Held out</option>
            </select>
          </label>
          <label className="text-xs text-slate-500">
            <span>killed</span>
            <select
              value={draft.killed}
              onChange={(event) =>
                setDraft((value) => ({ ...value, killed: event.target.value as Filters["killed"] }))
              }
              className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#0b1514] px-3 py-2 text-slate-200"
            >
              <option value="">All</option>
              <option value="false">Clean</option>
              <option value="true">Killed</option>
            </select>
          </label>
          <label className="text-xs text-slate-500">
            <span>min fitness</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={draft.min_fitness}
              onChange={(event) =>
                setDraft((value) => ({ ...value, min_fitness: event.target.value }))
              }
              className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-slate-200"
            />
          </label>
          <label className="text-xs text-slate-500">
            <span>max fitness</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={draft.max_fitness}
              onChange={(event) =>
                setDraft((value) => ({ ...value, max_fitness: event.target.value }))
              }
              className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-slate-200"
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={applyFilters}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-200 px-4 py-2 text-xs font-semibold text-slate-950"
          >
            <Filter className="size-3.5" /> Apply filters
          </button>
          <button
            type="button"
            onClick={resetFilters}
            className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-300"
          >
            <RotateCcw className="size-3.5" /> Reset
          </button>
          <button
            type="button"
            onClick={() => gridApi.current?.exportDataAsCsv({ fileName: "crucible-episodes.csv" })}
            className="ml-auto inline-flex items-center gap-2 rounded-lg border border-white/10 px-4 py-2 text-xs text-slate-300"
          >
            <Download className="size-3.5" /> Export loaded CSV
          </button>
        </div>
      </section>

      {error ? (
        <p
          role="alert"
          className="rounded-xl border border-rose-800/50 bg-rose-950/20 p-3 text-sm text-rose-200"
        >
          {error}
        </p>
      ) : null}
      <div className="h-[680px] overflow-hidden rounded-2xl border border-white/10">
        <AgGridProvider modules={[AllCommunityModule]}>
          <AgGridReact<Episode>
            theme={crucibleGridTheme}
            columnDefs={columns}
            defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
            rowModelType="infinite"
            cacheBlockSize={25}
            maxBlocksInCache={4}
            pagination
            paginationPageSize={25}
            paginationPageSizeSelector={[25, 50, 100]}
            getRowId={({ data }) => data.episode_id}
            onGridReady={onReady}
            rowHeight={44}
            headerHeight={42}
            animateRows={false}
          />
        </AgGridProvider>
      </div>
      <p className="text-xs leading-5 text-slate-600">
        API-backed: offset, limit, sorting, and the filters above are sent to{" "}
        <code>/world/episodes</code>. “Not exposed” means the list contract has no defensible value
        for that field.
      </p>
    </div>
  );
}
