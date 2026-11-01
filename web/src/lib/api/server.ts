import { CrucibleApi } from "./client";
import { publicEnv } from "@/lib/env";

export function serverApi() {
  return new CrucibleApi(publicEnv.NEXT_PUBLIC_API_BASE_URL, publicEnv.NEXT_PUBLIC_DATA_MODE);
}
