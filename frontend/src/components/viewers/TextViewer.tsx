import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { FileViewerProps } from "./types";

export function TextViewer({ runId, stepName, fileKey }: FileViewerProps) {
  const url = api.fileUrl(runId, stepName, fileKey);

  const { data: text, isLoading, isError } = useQuery<string>({
    queryKey: ["file", runId, stepName, fileKey],
    queryFn: async () => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      return res.text();
    },
    staleTime: Infinity,
  });

  if (isLoading) {
    return (
      <div className="p-4 space-y-2">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-3 bg-gray-800 rounded animate-pulse" style={{ width: `${50 + i * 10}%` }} />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="px-4 py-3 text-red-400 text-xs">Failed to load file.</p>;
  }

  return (
    <div className="h-full overflow-auto p-3">
      <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words">{text}</pre>
    </div>
  );
}
