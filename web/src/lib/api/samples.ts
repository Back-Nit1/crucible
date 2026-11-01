import samples from "@/generated/samples.json";

type SampleEnvelope = { request: string; status: number; body: unknown };
type FixtureName = keyof typeof samples.fixtures;

export const sampleSource = samples.source;

export function getSample(name: FixtureName): SampleEnvelope {
  return samples.fixtures[name] as SampleEnvelope;
}
