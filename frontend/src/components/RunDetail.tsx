import { useQuery } from "@tanstack/react-query";
import { api, type Pipeline, type RunDetail } from "../api";
import { DAGView } from "./DAGView";
import { ArtifactViewer } from "./ArtifactViewer";
import { useState } from "react";

const STATUS_CLASSES: Record<string, string> = {
  success: "text-emerald-400",
  failed: "text-red-400",
  running: "text-yellow-400",
  skipped: "text-gray-500",
  pending: "text-gray-600",
};

interface Props {
  pipeline: Pipeline;
  runId: string;
}

export function RunDetail({ pipeline, runId }: Props) {
  const [selectedStep, setSelectedStep] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<RunDetail>({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    // Keep refetching while the run is active
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === "running" ? 3_000 : false;
    },
  });

  if (isLoading) return <p className="p-4 text-gray-500">Loading…</p>;
  if (isError || !data) return <p className="p-4 text-red-400">Failed to load run</p>;

  const { run, steps } = data;
  const activeStep = selectedStep ?? null;
  const activeStepRecord = steps.find((s) => s.step_name === activeStep);

  return (
    <div className="flex flex-col h-full">
      {/* Run header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-4">
        <span className="text-gray-400">{run.run_id}</span>
        <span className={STATUS_CLASSES[run.status]}>{run.status}</span>
        {run.error && (
          <span className="text-red-400 text-xs truncate max-w-xs" title={run.error}>
            {run.error}
          </span>
        )}
      </div>

      {/* DAG */}
      <DAGView
        pipeline={pipeline}
        steps={steps}
        selectedStep={selectedStep}
        onSelectStep={setSelectedStep}
      />

      {/* Step list + artifact panel */}
      <div className="flex flex-1 overflow-hidden">
        {/* Step sidebar */}
        <div className="w-48 shrink-0 border-r border-gray-800 overflow-y-auto">
          {steps.map((s) => (
            <button
              key={s.step_name}
              onClick={() => setSelectedStep(s.step_name)}
              className={`w-full text-left px-3 py-2 border-b border-gray-900 hover:bg-gray-800 transition-colors flex items-center gap-2 ${
                selectedStep === s.step_name ? "bg-gray-800" : ""
              }`}
            >
              <span className={`shrink-0 ${STATUS_CLASSES[s.status]}`}>●</span>
              <span className="truncate text-xs text-gray-300">{s.step_name}</span>
              {s.duration_seconds != null && (
                <span className="ml-auto text-gray-600 text-xs shrink-0">
                  {s.duration_seconds.toFixed(1)}s
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Artifact viewer */}
        <div className="flex-1 overflow-hidden">
          {activeStep && activeStepRecord ? (
            Object.keys(activeStepRecord.paths).length > 0 ? (
              <ArtifactViewer runId={runId} step={activeStep} />
            ) : (
              <div className="p-4 text-gray-500 text-xs">
                {activeStepRecord.status === "skipped"
                  ? "Step was skipped — no artifacts."
                  : "No artifacts recorded for this step."}
              </div>
            )
          ) : (
            <div className="p-4 text-gray-500 text-xs">
              Click a step in the DAG or list to view artifacts.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
