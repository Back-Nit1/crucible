"use client";

import { ErrorState } from "@/components/ui/data-state";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <ErrorState
      title="This view could not be rendered"
      message="No data was substituted. Check the API connection and try again."
      onRetry={reset}
    />
  );
}
