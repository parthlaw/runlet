import { useQuery } from "@tanstack/react-query";
import { api, type Pipeline, type RunDetail } from "../api";
import { DAGView } from "./DAGView";
import { StatusBadge } from "./StatusBadge";

function shortRunId(runId: string): string {
  if (runId.length <= 20) return runId;
  return `${runId.slice(0, 8)}…${runId.slice(-6)}`;
}

interface Props {
  pipeline: Pipeline;
  runId: string;
  selectedStep: string | null;
  onSelectStep: (stepName: string) => void;
}

export function RunDAGPanel({ pipeline, runId, selectedStep, onSelectStep }: Props) {
  const { data, isLoading, isError } = useQuery<RunDetail>({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => (query.state.data?.run.status === "running" ? 3_000 : false),
  });

  const run = data?.run;
  const steps = data?.steps ?? [];
  const isLive = run?.status === "running";

  return (
    <main className="fixed top-14 left-60 right-[400px] bottom-0 z-30 flex flex-col bg-surface-container-lowest border-r border-outline-variant">
      <div className="shrink-0 px-gutter py-3 border-b border-outline-variant bg-surface-container-low flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="font-label-caps text-label-caps text-on-surface-variant mb-0.5">
            {pipeline.name}
          </div>
          {isLoading ? (
            <div className="h-5 w-40 bg-surface-container-high rounded animate-pulse" />
          ) : run ? (
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className="font-code-base text-code-base text-primary truncate"
                title={run.run_id}
              >
                {shortRunId(run.run_id)}
              </span>
              <StatusBadge status={run.status} />
            </div>
          ) : null}
        </div>
        {isLive && (
          <div className="flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full shrink-0">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 status-pulse" />
            <span className="font-label-caps text-[10px] text-amber-500 tracking-wider">LIVE</span>
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant font-code-sm text-code-sm">
            Loading DAG…
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex items-center justify-center text-error font-code-sm text-code-sm">
            Failed to load run.
          </div>
        )}
        {data && (
          <DAGView
            pipeline={pipeline}
            steps={steps}
            selectedStep={selectedStep}
            onSelectStep={onSelectStep}
            fillHeight
          />
        )}
      </div>
    </main>
  );
}
