import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import { api, Pipeline } from "../api";

interface Props {
  selected: string | null;
  onSelect: (name: string) => void;
}

export function PipelineList({ selected, onSelect }: Props) {
  const { data, isLoading, isError } = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: api.pipelines,
  });

  return (
    <aside className="w-60 shrink-0 border-r border-outline-strong flex flex-col bg-surface-low">
      {/* Section header */}
      <div className="px-4 py-3 border-b border-outline-strong flex items-center gap-2 shrink-0">
        <GitBranch className="w-3.5 h-3.5 text-content-ghost" />
        <span className="text-[11px] uppercase tracking-widest text-content-muted font-semibold">
          Pipelines
        </span>
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="p-2 space-y-1">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-9 bg-surface-high rounded animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-4 py-3 text-red-400 text-xs font-mono">Failed to load pipelines.</p>
      )}

      {/* Pipeline items */}
      <div className="flex-1 overflow-y-auto p-2 space-y-px">
        {data?.map((p) => (
          <button
            key={p.name}
            onClick={() => onSelect(p.name)}
            className={`w-full text-left px-3 py-2 rounded flex items-center gap-2 transition-all duration-150 ${
              selected === p.name
                ? "bg-primary/10 border-l-2 border-primary text-primary-soft"
                : "text-content-dim hover:bg-surface-high hover:text-content border-l-2 border-transparent"
            }`}
          >
            <span className="font-mono text-xs truncate flex-1">{p.name}</span>
            <span className="shrink-0 text-[10px] text-content-ghost font-mono">
              {p.nodes.length}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
