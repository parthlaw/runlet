import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { JsonView, allExpanded, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";
import { fetchArtifacts } from "../api";

interface Props {
  runId: string;
  step: string;
}

export function ArtifactViewer({ runId, step }: Props) {
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [filter, setFilter] = useState("");
  const parentRef = useRef<HTMLDivElement>(null);

  const { data: records = [], isLoading, isError } = useQuery<Record<string, unknown>[]>({
    queryKey: ["artifacts", runId, step],
    queryFn: () => fetchArtifacts(runId, step),
    staleTime: Infinity,
  });

  const filtered = filter
    ? records.filter((r) => JSON.stringify(r).toLowerCase().includes(filter.toLowerCase()))
    : records;

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 28,
    overscan: 10,
  });

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-800">
        <span className="text-xs text-gray-500">
          {isLoading ? "Loading…" : `${filtered.length} / ${records.length} records`}
        </span>
        <input
          type="text"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-48"
        />
      </div>

      {isError && <p className="px-4 py-3 text-red-400 text-xs">Failed to load artifacts</p>}

      <div ref={parentRef} className="flex-1 overflow-y-auto">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const record = filtered[item.index];
            const preview = JSON.stringify(record).slice(0, 120);
            return (
              <div
                key={item.key}
                style={{ position: "absolute", top: item.start, width: "100%", height: item.size }}
                className="flex items-center px-4 border-b border-gray-900 hover:bg-gray-800 cursor-pointer transition-colors"
                onClick={() => setSelected(record)}
              >
                <span className="text-gray-500 w-10 shrink-0 text-right mr-3">
                  {item.index + 1}
                </span>
                <span className="truncate text-gray-300">{preview}</span>
              </div>
            );
          })}
        </div>
      </div>

      <Dialog.Root open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/70 z-40" />
          <Dialog.Content className="fixed inset-0 flex items-center justify-center z-50 p-6">
            <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-3xl max-h-[80vh] flex flex-col shadow-2xl">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
                <Dialog.Title className="text-sm text-gray-300">Record detail</Dialog.Title>
                <Dialog.Close className="text-gray-500 hover:text-gray-200 text-lg leading-none">
                  ✕
                </Dialog.Close>
              </div>
              <div className="overflow-y-auto p-4">
                {selected && (
                  <JsonView
                    data={selected}
                    shouldExpandNode={allExpanded}
                    style={{
                      ...defaultStyles,
                      container: "bg-gray-900 text-xs font-mono",
                    }}
                  />
                )}
              </div>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
