"use client";

import { Line, OrbitControls, Text } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import { Group, MathUtils, Mesh, Vector3 } from "three";
import type { CrowdEpisode } from "@/lib/api/types";
import type {
  ObservatoryAgent,
  ObservatoryModel,
  ObservatoryProduct,
  ObservatoryShop,
  ObservatoryStep,
} from "./observatory-model";
import { useObservatoryStore } from "./observatory-store";

type Point = [number, number, number];
type ShopPoint = ObservatoryShop & { position: Point; accent: string };
type ProductPoint = ObservatoryProduct & { position: Point; shopId: string };

// Read once per load: honour the OS reduced-motion setting (no idle spin, shopper snaps to place).
const REDUCED_MOTION =
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const SPAWN: Point = [0, 0.35, 4.55];
const DOCK: Point = [0, 0.35, 5.65];
const SEARCH: Point = [0, 0.3, 0];
const CHECKOUT: Point = [-4.6, 0.35, 3.7];
const SHOP_POSITIONS: Point[] = [
  [-4.7, 0.5, -2.8],
  [4.7, 0.5, -2.8],
  [4.7, 0.5, 3.7],
  [0, 0.5, -5.2],
];
const SHOP_COLORS = ["#55d6ff", "#a78bfa", "#ffbe55", "#62f6a4"];

function shopLayout(shops: ObservatoryShop[]): ShopPoint[] {
  return shops.map((shop, index) => ({
    ...shop,
    position:
      SHOP_POSITIONS[index] ?? ([Math.cos(index) * 5, 0.5, Math.sin(index) * 5] satisfies Point),
    accent: SHOP_COLORS[index % SHOP_COLORS.length] ?? "#62f6a4",
  }));
}

function productLayout(products: ObservatoryProduct[], shops: ShopPoint[]): ProductPoint[] {
  const shopByCategory = new Map(shops.map((shop) => [shop.category, shop]));
  return products.map((product) => {
    const shop = shopByCategory.get(product.category) ?? shops[0];
    const inventory = products.filter((item) => item.category === product.category);
    const itemIndex = inventory.findIndex((item) => item.id === product.id);
    const angle = (itemIndex / Math.max(1, inventory.length)) * Math.PI * 2;
    const radius = 1.45 + (itemIndex % 2) * 0.28;
    const origin = shop?.position ?? SEARCH;
    return {
      ...product,
      shopId: shop?.id ?? "unknown-shop",
      position: [
        origin[0] + Math.cos(angle) * radius,
        0.2 + (itemIndex % 3) * 0.16,
        origin[2] + Math.sin(angle) * radius,
      ],
    };
  });
}

function NetworkFloor({ shops }: { shops: ShopPoint[] }) {
  return (
    <group>
      <gridHelper args={[22, 22, "#17463e", "#0b201c"]} position={[0, -0.12, 0]} />
      {shops.map((shop) => (
        <Line
          key={shop.id}
          points={[SEARCH, shop.position]}
          color={shop.accent}
          lineWidth={1}
          transparent
          opacity={0.28}
        />
      ))}
      <Line
        points={[SPAWN, SEARCH, CHECKOUT]}
        color="#79ffc1"
        lineWidth={1.2}
        transparent
        opacity={0.32}
      />
    </group>
  );
}

function SearchExchange() {
  const ring = useRef<Mesh>(null);
  useFrame((_, delta) => {
    if (REDUCED_MOTION) return;
    if (ring.current) ring.current.rotation.z += delta * 0.22;
  });
  return (
    <group position={SEARCH}>
      <mesh>
        <cylinderGeometry args={[0.72, 0.72, 0.16, 32]} />
        <meshStandardMaterial color="#0b2f27" emissive="#3cff9b" emissiveIntensity={0.55} />
      </mesh>
      <mesh ref={ring} rotation-x={Math.PI / 2}>
        <torusGeometry args={[0.98, 0.025, 8, 64]} />
        <meshBasicMaterial color="#72ffc0" toneMapped={false} />
      </mesh>
      <Text position={[0, 0.52, 0]} fontSize={0.18} color="#b8ffcf" anchorX="center">
        SEARCH EXCHANGE
      </Text>
      <Text position={[0, 0.3, 0]} fontSize={0.11} color="#6a9d8e" anchorX="center">
        CATALOG + REVIEWS
      </Text>
    </group>
  );
}

function CheckoutGate() {
  return (
    <group position={CHECKOUT}>
      {[-0.55, 0.55].map((x) => (
        <mesh key={x} position={[x, 0.45, 0]}>
          <boxGeometry args={[0.12, 1, 0.12]} />
          <meshStandardMaterial color="#ffca65" emissive="#ff9d2e" emissiveIntensity={0.8} />
        </mesh>
      ))}
      <mesh position={[0, 0.92, 0]}>
        <boxGeometry args={[1.22, 0.12, 0.12]} />
        <meshStandardMaterial color="#ffca65" emissive="#ff9d2e" emissiveIntensity={0.8} />
      </mesh>
      <Text position={[0, 1.35, 0]} fontSize={0.18} color="#ffd88f" anchorX="center">
        CHECKOUT / REFUSAL
      </Text>
      <Text position={[0, 1.12, 0]} fontSize={0.105} color="#a88146" anchorX="center">
        BUDGET GATE
      </Text>
    </group>
  );
}

function ShopNode({ shop }: { shop: ShopPoint }) {
  const shell = useRef<Mesh>(null);
  const selectedShopId = useObservatoryStore((state) => state.selectedShopId);
  const selectShop = useObservatoryStore((state) => state.selectShop);
  const selected = selectedShopId === shop.id;

  useFrame(({ clock }, delta) => {
    if (!shell.current || REDUCED_MOTION) return;
    shell.current.rotation.y += delta * 0.1;
    shell.current.position.y = Math.sin(clock.elapsedTime * 0.7 + shop.position[0]) * 0.05;
  });

  return (
    <group position={shop.position}>
      <mesh
        ref={shell}
        scale={selected ? 1.12 : 1}
        onClick={(event) => {
          event.stopPropagation();
          selectShop(selected ? null : shop.id);
        }}
      >
        <icosahedronGeometry args={[0.92, 2]} />
        <meshStandardMaterial
          color="#071b18"
          emissive={shop.accent}
          emissiveIntensity={selected ? 1.2 : 0.45}
          roughness={0.32}
          wireframe
        />
      </mesh>
      <mesh rotation-x={Math.PI / 2}>
        <torusGeometry args={[1.12, 0.018, 6, 64]} />
        <meshBasicMaterial color={shop.accent} transparent opacity={0.65} toneMapped={false} />
      </mesh>
      <Text position={[0, 1.45, 0]} fontSize={0.22} color="#eefdf6" anchorX="center">
        {shop.name.toUpperCase()}
      </Text>
      <Text position={[0, 1.16, 0]} fontSize={0.11} color={shop.accent} anchorX="center">
        {`${shop.productIds.length} PRODUCTS · ${shop.visits} VISITS`}
      </Text>
    </group>
  );
}

function Products({
  products,
  activeReferences,
  shops,
}: {
  products: ProductPoint[];
  activeReferences: string[];
  shops: ShopPoint[];
}) {
  const selectedProductId = useObservatoryStore((state) => state.selectedProductId);
  const selectProduct = useObservatoryStore((state) => state.selectProduct);
  const shopById = new Map(shops.map((shop) => [shop.id, shop]));

  return (
    <group>
      {products.map((product, index) => {
        const active = activeReferences.includes(product.id);
        const selected = selectedProductId === product.id;
        const accent = shopById.get(product.shopId)?.accent ?? "#b8ffcf";
        return (
          <mesh
            key={product.id}
            position={product.position}
            scale={selected ? 1.45 : active ? 1.22 : 1}
            onClick={(event: ThreeEvent<MouseEvent>) => {
              event.stopPropagation();
              selectProduct(selected ? null : product.id);
            }}
          >
            {index % 2 ? (
              <boxGeometry args={[0.17, 0.17, 0.17]} />
            ) : (
              <sphereGeometry args={[0.11, 12, 12]} />
            )}
            <meshStandardMaterial
              color={active || selected ? "#ffffff" : accent}
              emissive={active || selected ? "#b8ffcf" : accent}
              emissiveIntensity={active || selected ? 3.5 : 0.9}
              toneMapped={false}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function PopulationDock({ agents }: { agents: ObservatoryAgent[] }) {
  const selectedAgentId = useObservatoryStore((state) => state.selectedAgentId);
  const selectAgent = useObservatoryStore((state) => state.selectAgent);
  return (
    <group position={DOCK}>
      <Text position={[0, 1.15, 0]} fontSize={0.18} color="#b8ffcf" anchorX="center">
        SHOPPER POOL
      </Text>
      <Text position={[0, 0.9, 0]} fontSize={0.105} color="#63877d" anchorX="center">
        CANDIDATE POLICIES
      </Text>
      {agents.map((agent, index) => {
        // A flat grid on the floor: 8 agents make 3 columns, 200 make 15, never a tower.
        const columns = Math.max(4, Math.ceil(Math.sqrt(agents.length)));
        const spacing = agents.length > 40 ? 0.26 : 0.38;
        const column = index % columns;
        const row = Math.floor(index / columns);
        const selected = selectedAgentId === agent.id;
        return (
          <group
            key={agent.id}
            position={[(column - (columns - 1) / 2) * spacing, 0.15, row * spacing]}
            onClick={(event) => {
              event.stopPropagation();
              selectAgent(selected ? null : agent.id);
            }}
          >
            <mesh scale={selected ? 1.35 : 1}>
              <capsuleGeometry args={[0.09, 0.14, 4, 8]} />
              <meshStandardMaterial
                color={agent.survivor ? "#9dffd0" : "#ff5b79"}
                emissive={agent.survivor ? "#45e891" : "#ff244e"}
                emissiveIntensity={selected ? 2.5 : 0.8}
                toneMapped={false}
              />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

function targetForStep(
  step: Pick<ObservatoryStep, "tool" | "references"> | undefined,
  products: ProductPoint[],
  shops: ShopPoint[],
  missionCategory: string,
): Point {
  if (!step || step.tool === "parse_intent") return SPAWN;
  if (step.tool === "search_catalog") return SEARCH;
  if (
    step.tool === "report_no_match" ||
    step.tool.includes("purchase") ||
    step.tool.includes("pay")
  ) {
    return CHECKOUT;
  }
  const referenced = products.find((product) => step.references.includes(product.id));
  if (referenced) return referenced.position;
  return shops.find((shop) => shop.category === missionCategory)?.position ?? SEARCH;
}

function ActiveShopper({
  name,
  step,
  products,
  shops,
  missionCategory,
  visitedSteps,
}: {
  name: string;
  step: ObservatoryStep | undefined;
  products: ProductPoint[];
  shops: ShopPoint[];
  missionCategory: string;
  visitedSteps: ObservatoryStep[];
}) {
  const group = useRef<Group>(null);
  const core = useRef<Mesh>(null);
  const target = useMemo(
    () => new Vector3(...targetForStep(step, products, shops, missionCategory)),
    [missionCategory, products, shops, step],
  );
  const trail = useMemo(() => {
    const points: Point[] = [SPAWN];
    for (const item of visitedSteps) {
      const next = targetForStep(item, products, shops, missionCategory);
      const previous = points[points.length - 1];
      if (!previous || previous[0] !== next[0] || previous[2] !== next[2]) points.push(next);
    }
    return points;
  }, [missionCategory, products, shops, visitedSteps]);

  useFrame((_, delta) => {
    if (group.current)
      group.current.position.lerp(target, REDUCED_MOTION ? 1 : 1 - Math.exp(-delta * 3));
    if (core.current && !REDUCED_MOTION) core.current.rotation.y += delta * 1.2;
  });

  return (
    <group>
      {trail.length > 1 ? (
        <Line points={trail} color="#b8ffcf" lineWidth={2} transparent opacity={0.62} />
      ) : null}
      <group ref={group} position={SPAWN}>
        <mesh ref={core} position={[0, 0.22, 0]}>
          <capsuleGeometry args={[0.16, 0.26, 5, 12]} />
          <meshStandardMaterial
            color="#eafff2"
            emissive="#5bffa3"
            emissiveIntensity={2.5}
            toneMapped={false}
          />
        </mesh>
        <mesh position={[-0.07, 0.28, 0.15]}>
          <sphereGeometry args={[0.028, 8, 8]} />
          <meshBasicMaterial color="#07100f" />
        </mesh>
        <mesh position={[0.07, 0.28, 0.15]}>
          <sphereGeometry args={[0.028, 8, 8]} />
          <meshBasicMaterial color="#07100f" />
        </mesh>
        <pointLight color="#68ffab" intensity={1.8} distance={2.2} />
        <Text position={[0, 0.72, 0]} fontSize={0.15} color="#eafff2" anchorX="center">
          {name}
        </Text>
      </group>
    </group>
  );
}

const CROWD_STEP_SECONDS = 1.7;

// One of up to 30 concurrent shoppers, each replaying its own episode on its own clock (offset so they spread out).
function CrowdShopper({
  episode,
  index,
  products,
  shops,
}: {
  episode: CrowdEpisode;
  index: number;
  products: ProductPoint[];
  shops: ShopPoint[];
}) {
  const group = useRef<Group>(null);
  const clock = useRef(index * 0.37);
  const targets = useMemo(() => {
    const angle = index * 2.399; // golden angle: neighbours never stand on the same spot
    const jitter = 0.25 + (index % 5) * 0.09;
    return (episode.steps.length ? episode.steps : [undefined]).map((step) => {
      const [x, y, z] = targetForStep(step, products, shops, episode.category);
      return new Vector3(x + Math.cos(angle) * jitter, y, z + Math.sin(angle) * jitter);
    });
  }, [episode, index, products, shops]);
  const color = episode.killed
    ? "#ff5b79"
    : episode.checkpoint && !episode.checkpoint.startsWith("scripted")
      ? "#55d6ff"
      : "#9dffd0";

  useFrame((_, delta) => {
    if (!group.current) return;
    clock.current += delta;
    const target = targets[Math.floor(clock.current / CROWD_STEP_SECONDS) % targets.length];
    if (target)
      group.current.position.lerp(target, REDUCED_MOTION ? 1 : 1 - Math.exp(-delta * 2.5));
  });

  return (
    <group ref={group} position={SPAWN}>
      <mesh position={[0, 0.14, 0]}>
        <capsuleGeometry args={[0.07, 0.12, 3, 8]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={1.4}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

function World({ model, crowd }: { model: ObservatoryModel; crowd: CrowdEpisode[] }) {
  const stepIndex = useObservatoryStore((state) => state.stepIndex);
  const playing = useObservatoryStore((state) => state.playing);
  const shops = useMemo(() => shopLayout(model.shops), [model.shops]);
  const products = useMemo(() => productLayout(model.products, shops), [model.products, shops]);
  const activeStep = model.episode.steps[stepIndex] ?? model.episode.steps[0];

  return (
    <>
      <color attach="background" args={["#020a08"]} />
      <fog attach="fog" args={["#020a08", 13, 28]} />
      <ambientLight intensity={0.62} />
      <directionalLight position={[2, 10, 5]} color="#d9ffe9" intensity={1.5} />
      <pointLight position={[0, 4, 0]} color="#55ffc0" intensity={1.2} distance={16} />
      <NetworkFloor shops={shops} />
      <SearchExchange />
      <CheckoutGate />
      {shops.map((shop) => (
        <ShopNode key={shop.id} shop={shop} />
      ))}
      <Products products={products} activeReferences={activeStep?.references ?? []} shops={shops} />
      <PopulationDock agents={model.agents} />
      {crowd
        .filter((item) => item.episode_id !== model.episode.id)
        .map((item, index) => (
          <CrowdShopper
            key={item.episode_id}
            episode={item}
            index={index}
            products={products}
            shops={shops}
          />
        ))}
      <ActiveShopper
        name={`SHOPPER ${model.episode.agentId.replace("genome-", "").slice(0, 8).toUpperCase()}`}
        step={activeStep}
        products={products}
        shops={shops}
        missionCategory={model.episode.category}
        visitedSteps={model.episode.steps.slice(0, stepIndex + 1)}
      />
      <OrbitControls
        makeDefault
        enablePan
        minDistance={8}
        maxDistance={22}
        minPolarAngle={MathUtils.degToRad(30)}
        maxPolarAngle={MathUtils.degToRad(72)}
        target={[0, 0.4, 0]}
        autoRotate={!playing && !REDUCED_MOTION}
        autoRotateSpeed={0.12}
      />
      <EffectComposer multisampling={0}>
        <Bloom mipmapBlur intensity={0.78} luminanceThreshold={0.42} luminanceSmoothing={0.78} />
      </EffectComposer>
    </>
  );
}

export default function ObservatoryScene({
  model,
  crowd = [],
}: {
  model: ObservatoryModel;
  crowd?: CrowdEpisode[];
}) {
  return (
    <Canvas
      camera={{ position: [0, 11, 14], fov: 47, near: 0.1, far: 60 }}
      dpr={[1, 1.75]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={() => {
        useObservatoryStore.getState().selectProduct(null);
        useObservatoryStore.getState().selectAgent(null);
        useObservatoryStore.getState().selectShop(null);
      }}
    >
      <World model={model} crowd={crowd} />
    </Canvas>
  );
}
