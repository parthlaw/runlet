import { useQuery } from "@tanstack/react-query";
import { Activity, Info, X } from "lucide-react";
import { api, type Pipeline, type RunDetail } from "../api";
import { DAGView } from "./DAGView";
import { StepExecutionTree } from "./StepExecutionTree";

interface Props {
  pipeline: Pipeline;
  runId: string;
  onClose: () => void;
  onSelectStep: (stepName: string) => void;
}

export function RunDetail({ pipeline, runId, onClose, onSelectStep }: Props) {
  const { data, isLoading, isError } = useQuery<RunDetail>({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => (query.state.data?.run.status === "running" ? 3_000 : false),
  });

  if (isLoading) {
    return (
      <aside className="fixed top-14 bottom-0 right-0 w-[400px] z-40 bg-surface-container-low border-l border-outline-variant flex flex-col">
        <div className="p-4 border-b border-outline-variant">
          <div className="h-5 w-32 bg-surface-container-high rounded animate-pulse" />
        </div>
        <div className="flex-1 flex items-center justify-center text-on-surface-variant font-code-sm text-code-sm">
          Loading run…
        </div>
      </aside>
    );
  }

  if (isError || !data) {
    return (
      <aside className="fixed top-14 bottom-0 right-0 w-[400px] z-40 bg-surface-container-low border-l border-outline-variant flex items-center justify-center">
        <p className="text-error font-code-sm text-code-sm">Failed to load run.</p>
      </aside>
    );
  }

  const { run, steps } = data;
  const isLive = run.status === "running";

  return (
    <aside className="fixed top-14 bottom-0 right-0 w-[400px] z-40 bg-surface-container-low border-l border-outline-variant flex flex-col">
      <div className="p-4 border-b border-outline-variant flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Info className="w-5 h-5 text-primary" />
          <h2 className="font-headline-md text-[16px] font-bold text-on-surface">Run Detail</h2>
        </div>
        <div className="flex items-center gap-2">
          {isLive && (
            <div className="flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-500 status-pulse" />
              <span className="font-label-caps text-[10px] text-amber-500 tracking-wider">LIVE</span>
            </div>
          )}
          <button
            type="button"
            onClick={onClose}
            className="p-1 hover:bg-surface-variant rounded transition-colors duration-200"
            aria-label="Close run detail"
          >
            <X className="w-5 h-5 text-on-surface-variant" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="bg-surface-container-high/50 p-4">
          <p className="text-on-surface-variant font-label-caps text-[10px] mb-1">RUN UUID</p>
          <p className="font-code-base text-code-base text-primary font-bold break-all">
            {run.run_id}
          </p>
        </div>

        {run.error && (
          <div className="mx-4 mt-4 px-3 py-2 border border-error/30 bg-error/10 rounded">
            <p className="font-code-sm text-code-sm text-error leading-relaxed">{run.error}</p>
          </div>
        )}

        <div className="px-4 mb-8 mt-4">
          <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-4">
            DAG VISUALIZATION
          </h3>
          <DAGView
            pipeline={pipeline}
            steps={steps}
            selectedStep={null}
            onSelectStep={onSelectStep}
            compact
          />
        </div>

        <StepExecutionTree steps={steps} onSelectStep={onSelectStep} />
      </div>

      <div className="p-4 border-t border-outline-variant bg-surface-container flex items-center gap-2 shrink-0">
        <Activity className="w-4 h-4 text-emerald-400" />
        <span className="text-body-sm text-on-surface-variant">
          {steps.filter((s) => s.status === "success").length}/{steps.length} steps complete
        </span>
      </div>
    </aside>
  );
}
