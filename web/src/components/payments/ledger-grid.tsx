"use client";

import { AllCommunityModule, type ColDef } from "ag-grid-community";
import { AgGridProvider, AgGridReact } from "ag-grid-react";
import { useMemo } from "react";
import type { LedgerRow } from "@/lib/api/types";
import { crucibleGridTheme } from "@/components/grid/theme";
import { StatusBadge } from "@/components/ui/status-badge";

function ModeCell({ value }: { value?: "mock" | "sandbox" }) {
  return (
    <StatusBadge tone={value === "sandbox" ? "warning" : "info"}>
      {value?.toUpperCase() ?? "UNKNOWN"}
    </StatusBadge>
  );
}

export function LedgerGrid({ rows }: { rows: LedgerRow[] }) {
  const columns = useMemo<ColDef<LedgerRow>[]>(
    () => [
      { field: "mode", pinned: "left", width: 115, cellRenderer: ModeCell, filter: true },
      { field: "episode_id", headerName: "Episode", minWidth: 310, filter: true },
      { field: "event", headerName: "Ledger event", minWidth: 150, filter: true },
      {
        field: "product_id",
        headerName: "Product",
        minWidth: 135,
        valueFormatter: ({ value }) => value ?? "Not recorded",
      },
      { field: "amount", width: 115, valueFormatter: ({ value }) => value ?? "Not recorded" },
      { headerName: "Currency", valueGetter: () => "Not exposed", width: 115 },
      {
        field: "references",
        headerName: "Order / capture references",
        minWidth: 320,
        valueFormatter: ({ value }) => (Array.isArray(value) ? value.join(" · ") : "Not recorded"),
      },
      { headerName: "Idempotency", valueGetter: () => "Not exposed", minWidth: 130 },
      { headerName: "Latency", valueGetter: () => "Not exposed", minWidth: 115 },
      { headerName: "Status", valueGetter: () => "See event", minWidth: 110 },
    ],
    [],
  );
  return (
    <div className="h-[620px] overflow-hidden rounded-2xl border border-white/10">
      <AgGridProvider modules={[AllCommunityModule]}>
        <AgGridReact<LedgerRow>
          theme={crucibleGridTheme}
          rowData={rows}
          columnDefs={columns}
          defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: false }}
          pagination
          paginationPageSize={25}
          paginationPageSizeSelector={[25, 50, 100]}
          getRowId={({ data }) => `${data.episode_id}:${data.event}:${data.references.join(":")}`}
          rowHeight={44}
          headerHeight={42}
        />
      </AgGridProvider>
    </div>
  );
}
