import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Loader2, Ban } from "lucide-react";
import { api, RunRecord } from "../api";

const STATUS_ICON: Record<string, React.ReactNode> = {
  success:   <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed:    <XCircle      className="w-3.5 h-3.5 text-red-400" />,
  running:   <Loader2      className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
  cancelled: <Ban          className="w-3.5 h-3.5 text-gray-500" />,
};

const STATUS_BADGE: Record<string, string> = {
  success:   "bg-emerald-950/60 text-emerald-400 border-emerald-900/60",
  failed:    "bg-red-950/60 text-red-400 border-red-900/60",
  running:   "bg-amber-950/60 text-amber-400 border-amber-900/60",
  cancelled: "bg-gray-900/60 text-gray-500 border-gray-800/60",
};

function fmt(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function duration(run: RunRecord) {
  const ms = new Date(run.updated_at).getTime() - new Date(run.created_at).getTime();
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

interface Props {
  pipeline: string;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}

export function RunList({ pipeline, selectedRunId, onSelect }: Props) {
  const { data, isLoading, isError } = useQuery<RunRecord[]>({
    queryKey: ["runs", pipeline],
    queryFn: () => api.runs(pipeline),
    refetchInterval: 5_000,
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 flex items-baseline gap-2 shrink-0">
        <span className="text-[10px] uppercase tracking-widest text-gray-600 font-medium">Runs</span>
        <span className="text-xs text-gray-500 truncate">{pipeline}</span>
      </div>

      {isLoading && (
        <div className="px-4 py-3 space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-10 bg-gray-800/50 rounded-lg animate-pulse" />
          ))}
        </div>
      )}
      {isError && <p className="px-4 py-3 text-red-400 text-xs">Failed to load runs.</p>}

      <div className="overflow-y-auto flex-1">
        {data?.map((run) => (
          <button
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            className={`w-full text-left px-4 py-3 border-b border-gray-900/60 transition-all ${
              selectedRunId === run.run_id
                ? "bg-indigo-950/25 border-l-2 border-l-indigo-500"
                : "hover:bg-gray-800/40"
            }`}
          >
            <div className="flex items-center gap-2">
              {STATUS_ICON[run.status]}
              <span
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${
                  STATUS_BADGE[run.status] ?? "text-gray-500 border-gray-700"
                }`}
              >
                {run.status}
              </span>
              <span className="ml-auto text-gray-600 text-[10px] font-mono shrink-0">
                {duration(run)}
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-[11px] font-mono text-gray-400 truncate">{run.run_id}</span>
              <span className="ml-auto text-[10px] text-gray-600 shrink-0">{fmt(run.created_at)}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
