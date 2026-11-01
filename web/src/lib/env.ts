import { z } from "zod";

const publicEnvSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.url(),
  NEXT_PUBLIC_DATA_MODE: z.enum(["live", "sample"]).default("live"),
});

export type DataMode = z.infer<typeof publicEnvSchema>["NEXT_PUBLIC_DATA_MODE"];

export const publicEnv = publicEnvSchema.parse({
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_DATA_MODE: process.env.NEXT_PUBLIC_DATA_MODE,
});
