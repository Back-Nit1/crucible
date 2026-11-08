"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import { Color, type InstancedMesh, Object3D } from "three";
import type { GenerationSnapshot } from "@/lib/api/types";
import { BUDGET, buildLayout, selectRendered, writePositions } from "./motion";

const OUTCOME = {
  success: new Color("#62f6a4"),
  refusal: new Color("#55d6ff"),
  killed: new Color("#ff5b79"),
  other: new Color("#9aa7a3"),
};

function outcomeColor(e: GenerationSnapshot["episodes"][number]) {
  if (e.killed) return OUTCOME.killed;
  if (e.termination === "success") return OUTCOME.success;
  if (e.termination === "no_match") return OUTCOME.refusal;
  return OUTCOME.other;
}

function Crowd({
  snapshot,
  playing,
  onFps,
}: {
  snapshot: GenerationSnapshot;
  playing: boolean;
  onFps: (fps: number) => void;
}) {
  const layout = useMemo(() => buildLayout(snapshot), [snapshot]);
  const rendered = useMemo(() => selectRendered(snapshot.episodes), [snapshot]);
  const positions = useMemo(() => new Float32Array(rendered.length * 3), [rendered]);
  const shoppers = useRef<InstancedMesh>(null);
  const products = useRef<InstancedMesh>(null);
  const shops = useRef<InstancedMesh>(null);
  const clock = useRef(0);
  const fps = useRef({ frames: 0, elapsed: 0 });
  const dummy = useMemo(() => new Object3D(), []);
  const shopCount = snapshot.worlds.length * snapshot.categories.length;

  useLayoutEffect(() => {
    rendered.forEach((e, i) => shoppers.current?.setColorAt(i, outcomeColor(snapshot.episodes[e]!)));
    if (shoppers.current?.instanceColor) shoppers.current.instanceColor.needsUpdate = true;
    for (let i = 0; i < layout.productSlots.size; i++) {
      dummy.position.set(
        layout.productPositions[i * 3]!,
        layout.productPositions[i * 3 + 1]!,
        layout.productPositions[i * 3 + 2]!,
      );
      dummy.updateMatrix();
      products.current?.setMatrixAt(i, dummy.matrix);
    }
    if (products.current) products.current.instanceMatrix.needsUpdate = true;
    let s = 0;
    snapshot.worlds.forEach((_, w) =>
      snapshot.categories.forEach((__, c) => {
        dummy.position.set(
          layout.worldCenters[w * 3]! + layout.shopOffsets[c * 3]!,
          0.5,
          layout.worldCenters[w * 3 + 2]! + layout.shopOffsets[c * 3 + 2]!,
        );
        dummy.updateMatrix();
        shops.current?.setMatrixAt(s++, dummy.matrix);
      }),
    );
    if (shops.current) shops.current.instanceMatrix.needsUpdate = true;
  }, [dummy, layout, rendered, snapshot]);

  useFrame((_, delta) => {
    if (playing) clock.current += delta;
    writePositions(snapshot, layout, rendered, clock.current, positions);
    const mesh = shoppers.current;
    if (mesh) {
      for (let i = 0; i < rendered.length; i++) {
        dummy.position.set(positions[i * 3]!, positions[i * 3 + 1]!, positions[i * 3 + 2]!);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
    }
    fps.current.frames += 1;
    fps.current.elapsed += delta;
    if (fps.current.elapsed >= 2) {
      onFps(Math.round(fps.current.frames / fps.current.elapsed));
      fps.current = { frames: 0, elapsed: 0 };
    }
  });

  return (
    <>
      <instancedMesh ref={shoppers} args={[undefined, undefined, rendered.length]} frustumCulled={false}>
        <sphereGeometry args={[0.09, 6, 6]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      <instancedMesh
        ref={products}
        args={[undefined, undefined, Math.max(1, layout.productSlots.size)]}
        frustumCulled={false}
      >
        <boxGeometry args={[0.12, 0.12, 0.12]} />
        <meshBasicMaterial color="#c8d6d1" />
      </instancedMesh>
      <instancedMesh ref={shops} args={[undefined, undefined, Math.max(1, shopCount)]} frustumCulled={false}>
        <icosahedronGeometry args={[0.6, 1]} />
        <meshBasicMaterial color="#2c6b5c" wireframe />
      </instancedMesh>
    </>
  );
}

export default function CrowdScene({
  snapshot,
  playing,
  onFps,
}: {
  snapshot: GenerationSnapshot;
  playing: boolean;
  onFps: (fps: number) => void;
}) {
  return (
    <Canvas
      camera={{ position: [0, 40, 55], fov: 50, near: 0.1, far: 400 }}
      dpr={[1, BUDGET.MAX_DPR]}
      frameloop={playing ? "always" : "demand"}
      gl={{ antialias: true, powerPreference: "high-performance" }}
    >
      <color attach="background" args={["#020a08"]} />
      <Crowd snapshot={snapshot} playing={playing} onFps={onFps} />
      <OrbitControls makeDefault enablePan maxDistance={200} />
    </Canvas>
  );
}
