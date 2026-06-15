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
  success: <CheckCircle2 className="w-3.5 h-3.5 text-status-success" />,
  failed:  <XCircle      className="w-3.5 h-3.5 text-status-failed" />,
  running: <Loader2      className="w-3.5 h-3.5 text-status-running animate-spin" />,
  skipped: <MinusCircle  className="w-3.5 h-3.5 text-content-ghost" />,
  pending: <Clock        className="w-3.5 h-3.5 text-content-ghost/50" />,
};

const STATUS_DOT: Record<string, string> = {
  success: "bg-status-success",
  failed:  "bg-status-failed",
  running: "bg-status-running",
  skipped: "bg-content-ghost",
  pending: "bg-surface-high",
};

const RUN_STATUS_BADGE: Record<string, string> = {
  success:   "bg-emerald-950/60 text-emerald-400 border-emerald-900/50",
  failed:    "bg-red-950/60 text-red-400 border-red-900/50",
  running:   "bg-amber-950/60 text-amber-400 border-amber-900/50",
  cancelled: "bg-surface-high text-content-ghost border-outline-strong",
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
      <div className="flex flex-col h-full bg-surface">
        <div className="px-4 py-3 border-b border-outline-strong bg-surface-low">
          <div className="h-4 w-48 bg-surface-high rounded animate-pulse" />
        </div>
        <div className="flex-1 flex items-center justify-center text-content-ghost text-xs font-mono">
          Loading run…
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-400 text-xs font-mono">
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
    <div className="flex flex-col h-full overflow-hidden bg-surface">
      {/* Run header */}
      <div className="shrink-0 border-b border-outline-strong bg-surface-low">
        <div className="px-4 py-2.5 flex items-center gap-3">
          <span className="font-mono text-[11px] text-content-muted truncate flex-1">{run.run_id}</span>
          <span className="text-[10px] text-content-ghost font-mono shrink-0">
            {new Date(run.created_at).toLocaleString(undefined, {
              month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit",
            })}
          </span>
          <span
            className={`shrink-0 text-[10px] font-semibold px-2 py-px rounded border ${
              RUN_STATUS_BADGE[run.status] ?? "bg-surface-high text-content-ghost border-outline-strong"
            }`}
          >
            {run.status}
          </span>
        </div>

        {/* Error banner — full width below header */}
        {run.error && (
          <div className="px-4 py-2 border-t border-red-900/40 bg-red-950/20">
            <p className="text-red-300 font-mono text-xs leading-relaxed">{run.error}</p>
          </div>
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
        <div className="w-44 shrink-0 border-r border-outline-strong overflow-y-auto bg-surface-low">
          {steps.map((s) => (
            <button
              key={s.step_name}
              onClick={() => handleSelectStep(s.step_name)}
              className={`w-full text-left px-3 py-2.5 border-b border-outline-strong/30 flex items-center gap-2 transition-all duration-150 border-l-2 ${
                selectedStep === s.step_name
                  ? "bg-surface-high border-l-primary"
                  : "hover:bg-surface-mid border-l-transparent"
              }`}
            >
              <span
                className={`shrink-0 w-1.5 h-1.5 rounded-full ${STATUS_DOT[s.status] ?? "bg-content-ghost"} ${
                  s.status === "running" ? "status-pulse" : ""
                }`}
              />
              <span className="truncate text-xs font-mono text-content-dim flex-1">{s.step_name}</span>
              {s.duration_seconds != null && (
                <span className="ml-auto text-content-ghost text-[10px] shrink-0 font-mono">
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
                className="absolute inset-0 flex flex-col items-center justify-center gap-2"
              >
                <MousePointerClick className="w-6 h-6 text-content-ghost opacity-30" />
                <span className="text-xs text-content-ghost">Click a step to inspect it</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
