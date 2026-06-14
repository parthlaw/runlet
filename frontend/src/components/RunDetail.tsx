import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, XCircle, Loader2, MinusCircle, Clock, MousePointerClick } from "lucide-react";
import { api, type Pipeline, type RunDetail } from "../api";
import { DAGView } from "./DAGView";
import { StepDetail } from "./StepDetail";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed:  <XCircle      className="w-3.5 h-3.5 text-red-400" />,
  running: <Loader2      className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
  skipped: <MinusCircle  className="w-3.5 h-3.5 text-gray-500" />,
  pending: <Clock        className="w-3.5 h-3.5 text-gray-700" />,
};

const STATUS_DOT: Record<string, string> = {
  success: "bg-emerald-500",
  failed:  "bg-red-500",
  running: "bg-amber-400",
  skipped: "bg-gray-600",
  pending: "bg-gray-800",
};

const RUN_STATUS_BADGE: Record<string, string> = {
  success:   "bg-emerald-950/60 text-emerald-400 border-emerald-800/50",
  failed:    "bg-red-950/60 text-red-400 border-red-800/50",
  running:   "bg-amber-950/60 text-amber-400 border-amber-800/50",
  cancelled: "bg-gray-900/60 text-gray-500 border-gray-700/50",
};

// ---------------------------------------------------------------------------
// RunDetail
// ---------------------------------------------------------------------------

interface Props {
  pipeline: Pipeline;
  runId: string;
}

export function RunDetail({ pipeline, runId }: Props) {
  const [selectedStep, setSelectedStep] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<RunDetail>({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => (query.state.data?.run.status === "running" ? 3_000 : false),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col h-full">
        <div className="px-4 py-3 border-b border-gray-800">
          <div className="h-4 w-48 bg-gray-800 rounded animate-pulse" />
        </div>
        <div className="flex-1 flex items-center justify-center text-gray-700 text-xs">
          Loading run…
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-400 text-xs">
        Failed to load run.
      </div>
    );
  }

  const { run, steps } = data;
  const activeStepRecord = steps.find((s) => s.step_name === selectedStep);

  function handleSelectStep(name: string) {
    setSelectedStep((prev) => (prev === name ? null : name));
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Run header */}
      <div className="px-4 py-2.5 border-b border-gray-800 bg-gray-900/40 flex items-center gap-3 shrink-0">
        <span className="font-mono text-xs text-gray-500 truncate">{run.run_id}</span>
        <span
          className={`shrink-0 text-[10px] font-medium px-2 py-0.5 rounded-full border ${
            RUN_STATUS_BADGE[run.status] ?? "bg-gray-900 text-gray-400 border-gray-800"
          }`}
        >
          {run.status}
        </span>
        {run.error && (
          <span className="text-red-400 text-xs truncate max-w-xs" title={run.error}>
            {run.error}
          </span>
        )}
      </div>

      {/* DAG visualization */}
      <div className="shrink-0">
        <DAGView
          pipeline={pipeline}
          steps={steps}
          selectedStep={selectedStep}
          onSelectStep={handleSelectStep}
        />
      </div>

      {/* Step list + detail panel */}
      <div className="flex flex-1 overflow-hidden">
        {/* Step sidebar */}
        <div className="w-44 shrink-0 border-r border-gray-800 overflow-y-auto bg-gray-900/20">
          {steps.map((s) => (
            <button
              key={s.step_name}
              onClick={() => handleSelectStep(s.step_name)}
              className={`w-full text-left px-3 py-2.5 border-b border-gray-900/60 flex items-center gap-2 transition-all ${
                selectedStep === s.step_name
                  ? "bg-indigo-950/30 border-l-2 border-l-indigo-500"
                  : "hover:bg-gray-800/40"
              }`}
            >
              <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${STATUS_DOT[s.status] ?? "bg-gray-700"}`} />
              <span className="truncate text-xs font-mono text-gray-300">{s.step_name}</span>
              {s.duration_seconds != null && (
                <span className="ml-auto text-gray-600 text-[10px] shrink-0 font-mono">
                  {s.duration_seconds.toFixed(1)}s
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Step detail / empty state */}
        <div className="flex-1 overflow-hidden relative">
          <AnimatePresence mode="wait">
            {activeStepRecord ? (
              <motion.div
                key={activeStepRecord.step_name}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 overflow-y-auto"
              >
                <StepDetail runId={runId} stepRecord={activeStepRecord} />
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-gray-700"
              >
                <MousePointerClick className="w-6 h-6 opacity-40" />
                <span className="text-xs">Click a step to inspect it</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
