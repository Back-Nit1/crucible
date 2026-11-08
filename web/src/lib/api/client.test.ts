import { ApiError, CrucibleApi } from "./client";

describe("CrucibleApi", () => {
  it("validates and returns the sanitized generation sample", async () => {
    const api = new CrucibleApi("http://unused.test", "sample");
    const result = await api.generations();

    expect(result.total).toBe(1);
    expect(result.items[0]?.generation_id).toBe("gen-20261101-p8-t12");
    expect(result.items[0]?.runner).toBe("local");
  });

  it("parses the sample snapshot in sample mode", async () => {
    const api = new CrucibleApi("http://unused.test", "sample");
    const snap = await api.snapshot("any");
    expect(snap.episodes.length).toBe(snap.limits.episodes_included);
    expect(snap.episodes.length).toBeGreaterThan(0);
    expect(snap.limits.sampled).toBe(false);
    expect(snap.episodes[0]?.path[0]).toEqual([0, -1]);
  });

  it("replays the sanitized buyer contract without issuing a request", async () => {
    const api = new CrucibleApi("http://unused.test", "sample");
    const run = await api.startBuyerRun("find a headset");
    expect(run.status).toBe("awaiting_confirmation");
    expect(run.events.some((event) => event.type === "quote")).toBe(true);
  });

  it("calls the global fetch unbound, as browsers require (no 'Illegal invocation')", async () => {
    const strictFetch = vi.fn(function (this: unknown) {
      if (this !== undefined && this !== globalThis) throw new TypeError("Illegal invocation");
      return Promise.resolve(
        new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", strictFetch);
    try {
      const api = new CrucibleApi("https://api.example.test", "live");
      await expect(api.generations()).resolves.toMatchObject({ total: 0 });
      expect(strictFetch).toHaveBeenCalledOnce();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("preserves structured live API errors", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "model_unavailable", message: "not configured" } }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    );
    const api = new CrucibleApi("https://api.example.test", "live", fetcher);

    await expect(api.startBuyerRun("find a headset")).rejects.toEqual(
      new ApiError("model_unavailable", "not configured", 503),
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
