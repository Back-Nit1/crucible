# Architecture

Diagrams copied from `prompt.md` sections 6 and 9. Keep in sync with code at each milestone.

## System context

```mermaid
flowchart LR
  user([Shopper]) -->|raw request| chat[Shopping Chat<br/>Next.js on Render]
  judge([Judge]) --> chat
  judge --> dash[World + Model Dashboards<br/>AG Grid on Render]
  chat -->|tool calls| api[Agent API<br/>FastAPI on Render]
  api --> model[Fine-tuned Qwen ~7-8B<br/>served on Modal]
  api --> catalog[(Catalog Provider<br/>Channel3 / Elastic / Best Buy)]
  api --> pp[PayPal Sandbox<br/>Orders v2]
  api --> es[(Elastic<br/>catalog + reviews + traces)]
  world[Crucible World<br/>Modal, headless] --> es
  world --> ppmock[PayPal Mock]
  world --> pp
  world --> train[LoRA SFT on Modal]
  train --> model
  api -.deploy/monitor.-> astro[Astropods]
  api -.notifications.-> zap[Zapier]
  pp -.sandbox approval.-> kernel[KERNEL cloud browser]
```

## Catalog provider selection

```mermaid
flowchart TD
  start[Day-1 checks] --> c3{Channel3: storage terms OK<br/>and attribute coverage OK?}
  c3 -->|yes| live1[Live chat: Channel3Provider]
  c3 -->|no| bb{Best Buy API key<br/>+ terms OK?}
  bb -->|yes| live2[Live chat: BestBuyProvider for electronics<br/>+ ElasticCatalogProvider for the rest]
  bb -->|no| live3[Live chat: ElasticCatalogProvider only<br/>labelled 'snapshot data']
  start --> train[Training/eval catalog:<br/>ALWAYS a frozen snapshot in Elastic]
  train --> src{Snapshot source}
  src -->|reviews + products joined| amz[Amazon Reviews 2023<br/>McAuley Lab]
  src -->|extra eval| ws[WebShop]
  src -->|if allowed| c3snap[Channel3 snapshot]
  live1 & live2 & live3 --> kern{Need live page data on a site<br/>whose terms allow automated access?}
  kern -->|yes, allowlisted| k[KernelBrowseProvider]
  kern -->|no| skip[Do not browse]
```

## One episode

```mermaid
sequenceDiagram
  participant T as Task Bank
  participant A as Agent (genome)
  participant C as Catalog Tools (Elastic)
  participant R as Review Index (Elastic)
  participant P as PayPal Layer (mock/sandbox)
  participant S as Scorer + Kill Rules
  T->>A: raw shopping message
  A->>A: parse_intent()
  A->>C: search_catalog(query, filters)
  A->>C: get_product(id) x N
  A->>R: get_reviews(id, focus="heavier runners durability")
  A->>C: compare(ids)
  alt feasible
    A->>P: propose_purchase(id, variant, total)
    P-->>A: pending order (budget guard passed)
    A->>P: confirm_and_pay(order)
  else nothing fits
    A->>S: report_no_match(reason, closest)
  end
  A->>S: final answer + trace
  S-->>T: fitness, kill reason (if any)
```

## Evolution loop

```mermaid
flowchart LR
  pop[Population 24-48 genomes] --> run[Run seeded task batch]
  run --> score[Score: G x Q - efficiency]
  score --> kill{Instant-kill rule hit?}
  kill -->|yes| dead[Killed + logged]
  kill -->|no| rank[Rank survivors]
  rank --> cull[Cull bottom 25%]
  cull --> hunt[Loophole Hunter audits top traces]
  hunt -->|new pattern confirmed| rules[(Versioned kill rules)]
  rules --> kill
  cull --> breed[Mutate top survivors]
  breed --> pop
  rank --> sft[(High-fitness traces -> SFT dataset)]
```

## Checkout

```mermaid
sequenceDiagram
  participant U as Buyer (web chat or Postman)
  participant API as Crucible API
  participant PP as PayPal Sandbox (Orders v2)
  participant K as KERNEL browser (automated checks only)
  U->>API: shopping message
  API->>API: research, verified quote, budget check on quote.total
  API->>PP: create order (intent=CAPTURE, PayPal-Request-Id)
  PP-->>API: order id + approval link (PAYER_ACTION_REQUIRED)
  API-->>U: recommendation + quote + approval link (nothing charged)
  alt judge or demo
    U->>PP: approve with the sandbox buyer login
  else automated check
    API->>K: open approval link, log in as sandbox buyer, approve
    K->>PP: approve
  end
  U->>API: confirm (user_confirmed true)
  API->>API: re-quote, a stale or changed quote refuses
  API->>PP: capture order (same PayPal-Request-Id on retry)
  PP-->>API: capture record (sandbox ledger is the source of truth)
  API-->>U: receipt (order id, capture id, amount)
```

## Training and evaluation

```mermaid
flowchart LR
  traces[(Elastic traces)] --> filter[Filter: survived, high fitness,<br/>grounded reviews, no test leakage]
  filter --> ds[SFT dataset + manifest hash]
  ds --> lora[LoRA SFT, Qwen ~7-8B, Modal GPU]
  lora --> ckpt[(Checkpoint, versioned)]
  ckpt --> evalh[Eval harness]
  evalh --> held[Held-out tasks + held-out categories]
  evalh --> passk[pass^k]
  evalh --> webshop[WebShop benchmark]
  evalh --> sandbox[PayPal sandbox ledger checks]
  held & passk & webshop & sandbox --> report[(Model Dashboard + README tables)]
  ckpt -->|new genome option| world[Crucible World]
```

## Deployment topology

```mermaid
flowchart TB
  subgraph Render
    web[web: Next.js app]
    apisvc[api: FastAPI agent service]
  end
  subgraph Modal
    worldfn[world runner, scheduled + resumable]
    trainfn[LoRA training job]
    evalfn[eval job]
    serve[model inference endpoint]
  end
  subgraph Elastic_Cloud
    idx1[(products index)]
    idx2[(reviews index, vectors)]
    idx3[(traces index)]
    idx4[(kill_rules, generations)]
  end
  subgraph External
    paypal[PayPal Sandbox]
    c3[Channel3 API/MCP]
    bby[Best Buy API]
    kern[KERNEL browsers]
    astro[Astropods]
    zap[Zapier webhook]
  end
  web --> apisvc
  apisvc --> serve
  apisvc --> Elastic_Cloud
  apisvc --> paypal
  apisvc --> c3
  apisvc --> bby
  apisvc --> kern
  apisvc -.-> zap
  worldfn --> Elastic_Cloud
  worldfn --> paypal
  worldfn --> kern
  trainfn --> Elastic_Cloud
  astro -.deploys/monitors.-> apisvc
```

## Data model

```mermaid
erDiagram
  PRODUCT ||--o{ VARIANT : has
  PRODUCT ||--o{ REVIEW : has
  TASK ||--o{ EPISODE : runs_in
  AGENT ||--o{ EPISODE : plays
  GENERATION ||--o{ AGENT : contains
  AGENT ||--o| AGENT : parent_of
  EPISODE ||--o{ TOOL_CALL : contains
  EPISODE ||--o| PAYMENT : may_create
  EPISODE ||--o| KILL : may_end_in
  KILL_RULE ||--o{ KILL : triggers
  CHECKPOINT ||--o{ AGENT : powers
  PRODUCT { string id string title string brand string category float price string currency json attributes string source datetime as_of }
  REVIEW { string id string product_id float rating string text datetime date int helpful_votes bool verified json reviewer_context }
  TASK { string id string raw_message json hard_constraints json implied_needs json feasible_set json review_signals string split bool is_impossible bool is_review_trap }
  EPISODE { string id string task_id string agent_id float fitness float G float Q string final_answer }
  PAYMENT { string paypal_order_id string capture_id float amount string status string idempotency_key }
  KILL_RULE { string id int version string description datetime added_at int kills }
```

## Platform wiring (release-final)
```mermaid
flowchart LR
  api[api.main FastAPI] --> router[catalog.router ProviderRouter]
  api --> guards[payments.guards GuardedPayments]
  router -->|training / eval / default live| es[ElasticCatalogProvider]
  router -.->|opt-in live, fallback to snapshot| c3[Channel3Provider<br/>no reviews]
  router -. disabled .-> bb[BestBuy]
  es --> elastic[(Elastic Serverless<br/>products, reviews, traces)]
  guards --> mock[MockPayments]
  guards --> sbx[SandboxPayments<br/>PayPal Orders v2]
  sbx -.automated checks only.-> kern[KernelApprover]
  mem[memory.TraceRepository] --> elastic
  snap[scripts.build_snapshot<br/>Amazon Reviews 2023 stream] --> elastic
```
Implemented: provider interface + router (source/as_of/snapshot stamps), Elastic hybrid retrieval, Channel3 live provider,
PayPal sandbox backend with guards and mock parity, memory retrieval with test-split exclusion, typed API.
Added in release-final: the sandbox backend carries a sanitized in-process `PaymentLedger` served read-only at `/payments/ledger`;
`PaymentUnavailable` maps to HTTP 503; `CORS_ALLOW_ORIGINS`; `DEMO_MODE=1` brand masking (`api/masking.py`); the model is attached only when
`CRUCIBLE_MODEL_BACKEND=qwen` and the human-set Modal gates exist. Live status per service is in the README table; nothing is deployed to Render yet,
and Astropods and Zapier were not built.

## Operational world
```mermaid
flowchart LR
  subgraph Frozen snapshot
    es[(Elastic: products, reviews)]
  end
  es -->|"iter_products(category, manifest_hash)<br/>get_review_ids"| prov[ElasticCatalogProvider<br/>FrozenCatalogProvider]
  prov --> cache[FrozenCache]
  cache --> tg[world.taskgen<br/>feasible / impossible / review-sensitive]
  tg --> run[world.runtime.run_generation]
  pop[world.runtime.build_population<br/>honest + fixture genomes] --> run
  run -->|"ScriptedPolicy -> agents.runner.run_episode"| eng["state machine + tools<br/>GuardedPayments(MockPayments, Quote)<br/>scoring + kill rules"]
  eng --> mem[memory.episodes.RepositoryMemoryProvider]
  mem -->|"full EpisodeRecord + split, catalog hash,<br/>seed, genome, kills"| traces[(Elastic traces)]
  run --> store[world.store.GenerationStore<br/>atomic checkpoint + lease]
  store -.Modal Volume.-> vol[(crucible-world-checkpoints)]
  run --> fin[finalize: cull + survivors]
  fin --> lh[Loophole Hunter proposals]
  fin --> cur[training.curation -> SFT manifest]
  fin --> pub[world.publish -> Elastic generations / kill_rules]
  traces --> rd[api.readers.ElasticReader] --> apiw[api.world: /world/*, /models/*, /payments/ledger]
  modal["modal_app.world_runner<br/>run, resume, status, opt-in schedule"] --> run
```
Quote path: `GuardedPayments` asks a `QuoteProvider` for a `Quote` (subtotal, shipping, tax, discounts, total, currency, expiry), budgets and
creates the order from `quote.total`, re-quotes before capture and invalidates the pending order on any change. Frozen training uses
`ItemPriceQuotes` (labelled `item_price_only`); `REQUIRE_ALL_IN_QUOTE=1` refuses it.
