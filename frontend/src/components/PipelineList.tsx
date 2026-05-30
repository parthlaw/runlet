import { useQuery } from "@tanstack/react-query";
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
    <aside className="w-52 shrink-0 border-r border-gray-800 flex flex-col">
      <div className="px-4 py-3 border-b border-gray-800 text-xs uppercase tracking-widest text-gray-500">
        Pipelines
      </div>
      {isLoading && <p className="px-4 py-3 text-gray-500">Loading…</p>}
      {isError && <p className="px-4 py-3 text-red-400">Failed to load</p>}
      {data?.map((p) => (
        <button
          key={p.name}
          onClick={() => onSelect(p.name)}
          className={`w-full text-left px-4 py-2 truncate hover:bg-gray-800 transition-colors ${
            selected === p.name ? "bg-gray-800 text-white" : "text-gray-400"
          }`}
        >
          {p.name}
        </button>
      ))}
    </aside>
  );
}
