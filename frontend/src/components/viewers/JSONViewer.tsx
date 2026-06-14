import { useQuery } from "@tanstack/react-query";
import { JsonView, allExpanded, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";
import { api } from "../../api";
import type { FileViewerProps } from "./types";

export function JSONViewer({ runId, stepName, fileKey }: FileViewerProps) {
  const url = api.fileUrl(runId, stepName, fileKey);

  const { data, isLoading, isError } = useQuery<unknown>({
    queryKey: ["file", runId, stepName, fileKey],
    queryFn: async () => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.json();
    },
    staleTime: Infinity,
  });

  if (isLoading) {
    return (
      <div className="p-4 space-y-2">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-3 bg-gray-800 rounded animate-pulse" style={{ width: `${60 + i * 5}%` }} />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="px-4 py-3 text-red-400 text-xs">Failed to load file.</p>;
  }

  return (
    <div className="p-3 overflow-y-auto h-full">
      <JsonView
        data={data as object}
        shouldExpandNode={allExpanded}
        style={{ ...defaultStyles, container: "bg-transparent text-xs font-mono" }}
      />
    </div>
  );
}
