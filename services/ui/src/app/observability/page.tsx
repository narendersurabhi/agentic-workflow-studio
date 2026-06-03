import { Suspense } from "react";
import ObservabilityScreen from "../features/observability/ObservabilityScreen";

export default function ObservabilityPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-slate-50" />}>
      <ObservabilityScreen />
    </Suspense>
  );
}
