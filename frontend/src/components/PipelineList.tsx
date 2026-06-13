import { useQuery } from "@tanstack/react-query";
import { Workflow } from "lucide-react";
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
    <aside className="w-52 shrink-0 border-r border-gray-800 flex flex-col bg-gray-900/30">
      <div className="px-4 py-3.5 border-b border-gray-800 flex items-center gap-2 shrink-0">
        <Workflow className="w-3.5 h-3.5 text-indigo-400" />
        <span className="text-[10px] uppercase tracking-widest text-gray-500 font-medium">
          Pipelines
        </span>
      </div>

      {isLoading && (
        <div className="px-3 py-3 space-y-1.5">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-8 bg-gray-800/50 rounded-lg animate-pulse" />
          ))}
        </div>
      )}
      {isError && <p className="px-4 py-3 text-red-400 text-xs">Failed to load.</p>}

      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {data?.map((p) => (
          <button
            key={p.name}
            onClick={() => onSelect(p.name)}
            className={`w-full text-left px-3 py-2 rounded-lg text-xs font-mono truncate transition-all ${
              selected === p.name
                ? "bg-indigo-600/20 text-indigo-300 border border-indigo-700/40"
                : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
            }`}
          >
            {p.name}
          </button>
        ))}
      </div>
    </aside>
  );
}
