"use client";

import {
  Bot,
  ChevronRight,
  CircleDollarSign,
  Cpu,
  Pause,
  Play,
  ShieldX,
  Store,
  Target,
  Trophy,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo } from "react";
import type { ObservatoryModel, ObservatoryStep } from "./observatory-model";
import { useObservatoryStore } from "./observatory-store";
import styles from "./observatory.module.css";

const ObservatoryScene = dynamic(() => import("./observatory-scene"), {
  ssr: false,
  loading: () => <div className={styles.fallback}>Building the commerce internet…</div>,
});

const rewards = [
  "Complete the shopper's real goal",
  "Use catalog and review evidence",
  "Keep the total inside the wallet",
  "Refuse when no safe purchase exists",
];

const trainingStages = [
  { label: "Run the world", detail: "Agents attempt shopping missions", needsModel: false },
  { label: "Score behavior", detail: "Fitness and kill rules fire", needsModel: false },
  { label: "Select survivors", detail: "Survivor traces become training data", needsModel: false },
  { label: "Train Qwen", detail: "LoRA SFT, then GRPO, on survivor traces", needsModel: true },
  { label: "Redeploy", detail: "The new checkpoint re-enters the world", needsModel: true },
];

function stepLanguage(step: ObservatoryStep | undefined) {
  const language: Record<string, { title: string; objective: string }> = {
    parse_intent: {
      title: "Understand the shopper",
      objective: "Turn a messy request into a mission, constraints, and a wallet.",
    },
    search_catalog: {
      title: "Search the commerce internet",
      objective: "Choose a marketplace query and retrieve only real catalog candidates.",
    },
    get_product: {
      title: "Enter a shop and inspect",
      objective: "Open the listing and check price, variants, and identity before any purchase.",
    },
    get_reviews: {
      title: "Read the evidence layer",
      objective: "Check real shopper reviews for the concern that matters to this mission.",
    },
    summarize_review_evidence: {
      title: "Ground the recommendation",
      objective: "Attach review IDs to every claim the agent wants to make.",
    },
    compare: {
      title: "Compare viable options",
      objective: "Place opened listings side by side without dropping hard constraints.",
    },
    report_no_match: {
      title: "Refuse the impossible purchase",
      objective: "Earn reward by refusing instead of inventing a product or overspending.",
    },
    propose_purchase: {
      title: "Approach the checkout gate",
      objective: "Propose one verified item while the budget guard checks the total.",
    },
    confirm_and_pay: {
      title: "Wait for human approval",
      objective: "Payment is allowed only after explicit confirmation and a fresh quote.",
    },
  };
  return (
    language[step?.tool ?? ""] ?? {
      title: step?.tool.replaceAll("_", " ") ?? "Awaiting world event",
      objective: step?.summary ?? "The world has not emitted a decision yet.",
    }
  );
}

function shortId(value: string) {
  return value.replace("genome-", "").slice(0, 8);
}

export function ObservatoryClient({ model, sample }: { model: ObservatoryModel; sample: boolean }) {
  const stepIndex = useObservatoryStore((state) => state.stepIndex);
  const playing = useObservatoryStore((state) => state.playing);
  const speed = useObservatoryStore((state) => state.speed);
  const selectedProductId = useObservatoryStore((state) => state.selectedProductId);
  const selectedAgentId = useObservatoryStore((state) => state.selectedAgentId);
  const selectedShopId = useObservatoryStore((state) => state.selectedShopId);
  const setStep = useObservatoryStore((state) => state.setStep);
  const togglePlaying = useObservatoryStore((state) => state.togglePlaying);
  const setPlaying = useObservatoryStore((state) => state.setPlaying);
  const setSpeed = useObservatoryStore((state) => state.setSpeed);
  const reset = useObservatoryStore((state) => state.reset);
  const steps = model.episode.steps;
  const activeStep = steps[stepIndex] ?? steps[0];
  const narrative = stepLanguage(activeStep);

  useEffect(() => {
    reset();
  }, [model.episode.id, reset]);

  useEffect(() => {
    if (!playing || steps.length < 2) return;
    const timer = window.setTimeout(() => {
      const next = stepIndex + 1;
      setStep(next >= steps.length ? 0 : next);
    }, 1700 / speed);
    return () => window.clearTimeout(timer);
  }, [playing, setStep, speed, stepIndex, steps.length]);

  const selectedProduct = useMemo(
    () => model.products.find((product) => product.id === selectedProductId) ?? null,
    [model.products, selectedProductId],
  );
  const selectedAgent = useMemo(
    () => model.agents.find((agent) => agent.id === selectedAgentId) ?? null,
    [model.agents, selectedAgentId],
  );
  const selectedShop = useMemo(
    () => model.shops.find((shop) => shop.id === selectedShopId) ?? null,
    [model.shops, selectedShopId],
  );

  return (
    <section className={styles.shell} aria-label="Crucible commerce training world">
      <div className={styles.canvas} aria-hidden="true">
        <ObservatoryScene model={model} />
      </div>
      <div className={styles.scanlines} />

      <header className={styles.topbar}>
        <div className={styles.brandLockup}>
          <span className={styles.brandMark}>
            <span />
          </span>
          <div>
            <p className={styles.brand}>Crucible</p>
            <p className={styles.brandSub}>Commerce agent training ground</p>
          </div>
        </div>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>The RL world</p>
          <h1>
            A proving ground where shopping agents <span>earn trust with money.</span>
          </h1>
          <p>Every action is scored. Cheating, overspending or inventing evidence ends the run.</p>
        </div>
        <div className={styles.topActions}>
          <span className={styles.liveBadge}>
            <span /> Recorded mission
          </span>
          <Link href="/world" className={styles.dashboardLink}>
            Evidence dashboard <ChevronRight size={13} />
          </Link>
        </div>
      </header>

      <aside
        className={`${styles.panel} ${styles.missionPanel}`}
        aria-label="Current shopping mission"
      >
        <div className={styles.panelHeading}>
          <span>
            <Target size={14} /> Current mission
          </span>
          <span className={styles.stepCount}>
            {stepIndex + 1}/{steps.length}
          </span>
        </div>
        <div className={styles.agentIdentity}>
          <span className={styles.agentAvatar}>
            <Bot size={17} />
          </span>
          <div>
            <strong>Shopper {shortId(model.episode.agentId)}</strong>
            <small>checkpoint {model.training.currentCheckpoint}</small>
          </div>
          <span className={styles.agentState}>{playing ? "acting" : "paused"}</span>
        </div>
        <blockquote>“{model.mission.request}”</blockquote>
        <div className={styles.walletRow}>
          <span>
            <CircleDollarSign size={14} /> Shopper wallet
          </span>
          <strong>{model.mission.budget ? `$${model.mission.budget}` : "Not published"}</strong>
        </div>
        <div className={styles.objective}>
          <p>{narrative.title}</p>
          <span>{narrative.objective}</span>
        </div>
      </aside>

      <aside className={`${styles.panel} ${styles.rulesPanel}`} aria-label="Reward contract">
        <div className={styles.panelHeading}>
          <span>
            <Trophy size={14} /> Reward contract
          </span>
          <span className={styles.finalReward}>
            fitness {model.episode.fitness?.toFixed(2) ?? "—"}
          </span>
        </div>
        <div className={styles.ruleColumns}>
          <div>
            <p className={styles.earnLabel}>Earn fitness</p>
            <ul>
              {rewards.map((reward) => (
                <li key={reward}>
                  <span>+</span>
                  {reward}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className={styles.failLabel}>Instant kill</p>
            <ul>
              {model.rules.map((rule) => (
                <li key={rule.id} title={rule.description}>
                  <span>×</span>
                  {rule.label}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>

      <aside className={`${styles.panel} ${styles.learningPanel}`} aria-label="Learning loop">
        <div className={styles.panelHeading}>
          <span>
            <Cpu size={14} /> How the model learns
          </span>
        </div>
        {selectedShop ? (
          <div className={styles.selectionDetail}>
            <Store size={20} />
            <p>Virtual shop</p>
            <h2>{selectedShop.name}</h2>
            <span>
              {selectedShop.productIds.length} products · {selectedShop.visits} recorded visits
            </span>
          </div>
        ) : selectedProduct ? (
          <div className={styles.selectionDetail}>
            <Target size={20} />
            <p>Real catalog listing</p>
            <h2>{selectedProduct.id}</h2>
            <span>
              {selectedProduct.category.replaceAll("_", " ")} · referenced{" "}
              {selectedProduct.mentions}×
            </span>
          </div>
        ) : selectedAgent ? (
          <div className={styles.selectionDetail}>
            <Bot size={20} />
            <p>Candidate shopper policy</p>
            <h2>Shopper {shortId(selectedAgent.id)}</h2>
            <span>
              {selectedAgent.variant} · {selectedAgent.survivor ? "survived" : "culled"} · reward{" "}
              {selectedAgent.fitness?.toFixed(2) ?? "—"}
            </span>
          </div>
        ) : (
          <>
            <ol className={styles.learningLoop}>
              {trainingStages.map((stage, index) => (
                <li key={stage.label} data-active={index === 0}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{stage.label}</strong>
                    <small>
                      {stage.needsModel && model.scripted ? "Not run yet · " : ""}
                      {stage.detail}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
            <div className={styles.modelCard}>
              <span>{model.scripted ? "This replay" : "Model checkpoint"}</span>
              <strong>{model.training.currentCheckpoint}</strong>
              <small>
                {model.scripted
                  ? "Scripted shopper, no model. Target model: Qwen2.5 Instruct, not trained yet."
                  : "Qwen2.5 Instruct with a LoRA adapter on Modal"}
              </small>
            </div>
          </>
        )}
      </aside>

      <div className={styles.populationSummary} aria-label="Generation outcome">
        <span>
          <Bot size={13} />
          <strong>{model.populationSize}</strong> shoppers entered
        </span>
        <ChevronRight size={12} />
        <span>
          <Trophy size={13} />
          <strong>{model.survivors}</strong> survived
        </span>
        <ChevronRight size={12} />
        <span>
          <ShieldX size={13} />
          <strong>{model.culled}</strong> culled
        </span>
        <ChevronRight size={12} />
        <span>
          <Cpu size={13} /> {model.survivors > 0 ? "survivor traces" : "no training data"}
        </span>
      </div>

      <div className={styles.timeline}>
        <button
          type="button"
          className={styles.playButton}
          onClick={() => (steps.length > 1 ? togglePlaying() : setPlaying(false))}
          aria-label={playing ? "Pause mission replay" : "Play mission replay"}
        >
          {playing ? (
            <Pause size={17} fill="currentColor" />
          ) : (
            <Play size={17} fill="currentColor" />
          )}
        </button>
        <div className={styles.timelineCopy}>
          <p>
            <span>World event {String(stepIndex + 1).padStart(2, "0")}</span>
            {narrative.title}
          </p>
          <small>{activeStep?.summary ?? "No world event"}</small>
        </div>
        <div className={styles.speedControls} aria-label="Playback speed">
          {[0.5, 1, 2].map((value) => (
            <button
              key={value}
              type="button"
              data-active={speed === value}
              onClick={() => setSpeed(value)}
              aria-label={`${value} times speed`}
            >
              {value}×
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={Math.max(steps.length - 1, 0)}
          value={Math.min(stepIndex, Math.max(steps.length - 1, 0))}
          onChange={(event) => {
            setPlaying(false);
            setStep(Number(event.currentTarget.value));
          }}
          aria-label="Mission replay step"
        />
      </div>

      <div className={styles.truthLabel}>
        {model.scripted ? "WORLD ENGINE REPLAY · NOT QWEN PERFORMANCE" : "QWEN MODEL ROLLOUT"}
        {sample ? " · SANITIZED SAMPLE" : ""}
      </div>
    </section>
  );
}
