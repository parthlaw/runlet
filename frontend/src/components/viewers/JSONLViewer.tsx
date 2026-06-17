import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Search } from "lucide-react";
import { api } from "../../api";
import type { FileViewerProps } from "./types";
import { JSONRecordModal } from "./JSONRecordModal";

export function JSONLViewer({ runId, stepName, fileKey }: FileViewerProps) {
  const [filter, setFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
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

  const selectedRecord =
    selectedIdx !== null && selectedIdx < filtered.length ? filtered[selectedIdx] : null;

  function openRow(index: number) {
    setSelectedIdx(index);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-[#0d0d15]">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-outline-variant/40 shrink-0">
        <span className="text-[11px] font-mono text-on-surface-variant">
          {isLoading
            ? "Loading…"
            : `${filtered.length.toLocaleString()} / ${records.length.toLocaleString()} rows`}
        </span>
        <div className="ml-auto relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-on-surface-variant" />
          <input
            type="text"
            placeholder="Filter rows…"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              if (modalOpen) closeModal();
              setSelectedIdx(null);
            }}
            className="bg-surface border border-outline-variant rounded pl-6 pr-2 py-1 text-xs font-mono text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:border-primary w-44 transition-colors duration-200"
          />
        </div>
      </div>

      {isError && (
        <p className="px-3 py-2 text-error text-xs font-mono">Failed to load file.</p>
      )}

      <div ref={parentRef} className="overflow-y-auto flex-1 min-h-0">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const record = filtered[item.index];
            const isSelected = selectedIdx === item.index && modalOpen;
            const preview = JSON.stringify(record).slice(0, 140);
            return (
              <div
                key={item.key}
                style={{ position: "absolute", top: item.start, width: "100%", height: item.size }}
                className={`flex items-center px-3 border-b border-outline-variant/20 cursor-pointer transition-colors duration-200 text-xs font-mono border-l-2 ${
                  isSelected
                    ? "bg-primary/10 border-l-primary"
                    : "hover:bg-surface-container border-l-transparent"
                }`}
                onClick={() => openRow(item.index)}
              >
                <span className="text-on-surface-variant w-8 shrink-0 text-right mr-3 select-none tabular-nums">
                  {item.index + 1}
                </span>
                <span
                  className={`truncate ${isSelected ? "text-on-surface" : "text-on-surface-variant"}`}
                >
                  {preview}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {selectedRecord && selectedIdx !== null && (
        <JSONRecordModal
          open={modalOpen}
          onClose={closeModal}
          record={selectedRecord}
          rowIndex={selectedIdx}
          totalRows={filtered.length}
        />
      )}
    </div>
  );
}
