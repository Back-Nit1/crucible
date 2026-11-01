"use client";

import { useCallback, useEffect, useState } from "react";
import { CrucibleApi } from "@/lib/api/client";
import { publicEnv } from "@/lib/env";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";

type ConnectionState = "checking" | "connected" | "disconnected" | "sample";

export function ConnectionIndicator() {
  const [state, setState] = useState<ConnectionState>(
    publicEnv.NEXT_PUBLIC_DATA_MODE === "sample" ? "sample" : "checking",
  );

  const check = useCallback(async () => {
    if (publicEnv.NEXT_PUBLIC_DATA_MODE === "sample") return;
    setState("checking");
    try {
      await new CrucibleApi(
        publicEnv.NEXT_PUBLIC_API_BASE_URL,
        publicEnv.NEXT_PUBLIC_DATA_MODE,
      ).health();
      setState("connected");
    } catch {
      setState("disconnected");
    }
  }, []);

  useEffect(() => {
    if (publicEnv.NEXT_PUBLIC_DATA_MODE === "sample") return;
    const initial = window.setTimeout(() => void check(), 0);
    const timer = window.setInterval(() => void check(), 30_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [check]);

  const label = {
    checking: "Checking API",
    connected: "Live API",
    disconnected: "API disconnected",
    sample: "Sample data",
  }[state];
  const tone: StatusTone =
    state === "connected" ? "positive" : state === "sample" ? "warning" : "danger";

  return (
    <button
      type="button"
      onClick={() => void check()}
      className="rounded-full"
      title={state === "sample" ? "Sanitized static API samples" : "Check API connection"}
    >
      <StatusBadge tone={tone} dot>
        {label}
      </StatusBadge>
    </button>
  );
}
