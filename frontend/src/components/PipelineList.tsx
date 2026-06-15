import { useQuery } from "@tanstack/react-query";
import { AlertCircle, GitBranch, PlayCircle } from "lucide-react";
import { api, Pipeline, RunRecord } from "../api";

interface Props {
  selected: string | null;
  onSelect: (name: string) => void;
}

const SPARKLINE_HEIGHTS = [60, 80, 40, 90, 100];
const SPARKLINE_NEUTRAL = [30, 50, 70, 20, 40];

function statusDotClass(status: RunRecord["status"] | undefined): string {
  switch (status) {
    case "success":
      return "bg-emerald-400";
    case "failed":
      return "bg-error";
    case "running":
      return "bg-tertiary-container status-pulse";
    default:
      return "bg-outline";
  }
}

function PipelineIcon({ status }: { status: RunRecord["status"] | undefined }) {
  if (status === "failed") return <AlertCircle className="w-[18px] h-[18px] shrink-0" />;
  if (status === "running") return <PlayCircle className="w-[18px] h-[18px] shrink-0" />;
  return <GitBranch className="w-[18px] h-[18px] shrink-0" />;
}

function Sparkline({ selected }: { selected: boolean }) {
  const heights = selected ? SPARKLINE_HEIGHTS : SPARKLINE_NEUTRAL;
  const barClass = selected
    ? "bg-on-secondary-container/30"
    : "bg-outline-variant";

  return (
    <div className="h-6 flex items-end gap-0.5 px-1">
      {heights.map((h, i) => (
        <div
          key={i}
          className={`w-full rounded-t-sm ${barClass}`}
          style={{ height: `${h}%` }}
        />
      ))}
    </div>
  );
}

function PipelineCard({
  pipeline,
  selected,
  onSelect,
}: {
  pipeline: Pipeline;
  selected: boolean;
  onSelect: () => void;
}) {
  const { data: latestRun } = useQuery<RunRecord[]>({
    queryKey: ["runs", pipeline.name, "latest"],
    queryFn: () => api.runs(pipeline.name, 1),
    staleTime: 5_000,
  });

  const status = latestRun?.[0]?.status;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group flex flex-col p-2 rounded-lg cursor-pointer transition-all duration-200 ease-in-out w-full text-left ${
        selected
          ? "bg-secondary-container text-on-secondary-container"
          : "text-on-surface-variant hover:bg-surface-variant"
      }`}
    >
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <PipelineIcon status={status} />
          <span className={`font-body-sm truncate ${selected ? "font-semibold" : ""}`}>
            {pipeline.name}
          </span>
        </div>
        {status && (
          <div className={`w-2 h-2 rounded-full shrink-0 ${statusDotClass(status)}`} />
        )}
      </div>
      <Sparkline selected={selected} />
    </button>
  );
}

export function PipelineList({ selected, onSelect }: Props) {
  const { data, isLoading, isError } = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: api.pipelines,
  });

  return (
    <aside className="fixed top-14 left-0 bottom-0 z-40 flex flex-col py-stack-md px-stack-sm gap-stack-sm bg-surface-container-low border-r border-outline-variant w-60 overflow-y-auto">
      <div className="px-2 mb-stack-md">
        <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-2">
          PIPELINES
        </h3>
      </div>

      {isLoading && (
        <div className="px-2 space-y-1">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 bg-surface-container-high rounded-lg animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-2 py-3 text-error font-code-sm text-code-sm">Failed to load pipelines.</p>
      )}

      <nav className="flex flex-col gap-1 px-2">
        {data?.map((p) => (
          <PipelineCard
            key={p.name}
            pipeline={p}
            selected={selected === p.name}
            onSelect={() => onSelect(p.name)}
          />
        ))}
      </nav>
    </aside>
  );
}
