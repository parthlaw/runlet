import { useQuery } from "@tanstack/react-query";
import { api, RunRecord } from "../api";

const STATUS_CLASSES: Record<string, string> = {
  success: "text-emerald-400",
  failed: "text-red-400",
  running: "text-yellow-400",
  cancelled: "text-gray-500",
};

const STATUS_ICONS: Record<string, string> = {
  success: "✓",
  failed: "✗",
  running: "⟳",
  cancelled: "○",
};

function fmt(iso: string) {
  return new Date(iso).toLocaleString();
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
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 text-xs uppercase tracking-widest text-gray-500">
        Runs — {pipeline}
      </div>
      {isLoading && <p className="px-4 py-3 text-gray-500">Loading…</p>}
      {isError && <p className="px-4 py-3 text-red-400">Failed to load runs</p>}
      <div className="overflow-y-auto flex-1">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500">
              <th className="px-4 py-2 text-left font-normal">Run ID</th>
              <th className="px-4 py-2 text-left font-normal">Status</th>
              <th className="px-4 py-2 text-left font-normal">Duration</th>
              <th className="px-4 py-2 text-left font-normal">Started</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((run) => (
              <tr
                key={run.run_id}
                onClick={() => onSelect(run.run_id)}
                className={`border-b border-gray-900 cursor-pointer hover:bg-gray-800 transition-colors ${
                  selectedRunId === run.run_id ? "bg-gray-800" : ""
                }`}
              >
                <td className="px-4 py-2 text-gray-300 truncate max-w-[180px]">{run.run_id}</td>
                <td className={`px-4 py-2 ${STATUS_CLASSES[run.status] ?? "text-gray-400"}`}>
                  {STATUS_ICONS[run.status]} {run.status}
                </td>
                <td className="px-4 py-2 text-gray-400">{duration(run)}</td>
                <td className="px-4 py-2 text-gray-500">{fmt(run.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
