import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { JsonView, allExpanded, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";
import { Search } from "lucide-react";
import { api } from "../../api";
import type { FileViewerProps } from "./types";

export function JSONLViewer({ runId, stepName, fileKey }: FileViewerProps) {
  const [filter, setFilter] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);
  const url = api.fileUrl(runId, stepName, fileKey);

  const { data: records = [], isLoading, isError } = useQuery<Record<string, unknown>[]>({
    queryKey: ["file", runId, stepName, fileKey],
    queryFn: async () => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const text = await res.text();
      return text.trim().split("\n").filter(Boolean).map((l) => JSON.parse(l));
    },
    staleTime: Infinity,
  });

  const filtered = filter
    ? records.filter((r) => JSON.stringify(r).toLowerCase().includes(filter.toLowerCase()))
    : records;

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 32,
    overscan: 10,
  });

  const selectedRecord = selectedIdx !== null ? filtered[selectedIdx] : null;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-gray-800 shrink-0">
        <span className="text-xs text-gray-500">
          {isLoading ? "Loading…" : `${filtered.length.toLocaleString()} / ${records.length.toLocaleString()} rows`}
        </span>
        <div className="ml-auto relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-600" />
          <input
            type="text"
            placeholder="Filter rows…"
            value={filter}
            onChange={(e) => { setFilter(e.target.value); setSelectedIdx(null); }}
            className="bg-gray-950 border border-gray-700 rounded-md pl-6 pr-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-44 transition-colors"
          />
        </div>
      </div>

      {isError && (
        <p className="px-3 py-2 text-red-400 text-xs">Failed to load file.</p>
      )}

      <div ref={parentRef} className={`overflow-y-auto ${selectedRecord ? "flex-[2]" : "flex-1"} min-h-0`}>
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const record = filtered[item.index];
            const isSelected = selectedIdx === item.index;
            const preview = JSON.stringify(record).slice(0, 140);
            return (
              <div
                key={item.key}
                style={{ position: "absolute", top: item.start, width: "100%", height: item.size }}
                className={`flex items-center px-3 border-b border-gray-900/60 cursor-pointer transition-colors text-xs font-mono ${
                  isSelected ? "bg-indigo-950/40 border-l-2 border-l-indigo-500" : "hover:bg-gray-800/60"
                }`}
                onClick={() => setSelectedIdx(isSelected ? null : item.index)}
              >
                <span className="text-gray-600 w-8 shrink-0 text-right mr-3 select-none">
                  {item.index + 1}
                </span>
                <span className={`truncate ${isSelected ? "text-gray-100" : "text-gray-400"}`}>
                  {preview}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {selectedRecord && (
        <div className="flex-[1] min-h-0 border-t border-indigo-900/40 overflow-y-auto bg-gray-950/60 p-3">
          <JsonView
            data={selectedRecord}
            shouldExpandNode={allExpanded}
            style={{ ...defaultStyles, container: "bg-transparent text-xs font-mono" }}
          />
        </div>
      )}
    </div>
  );
}
