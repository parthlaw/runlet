import { useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import Papa from "papaparse";
import { api } from "../../api";
import type { FileViewerProps } from "./types";

interface ParsedCSV {
  headers: string[];
  rows: string[][];
}

const columnHelper = createColumnHelper<string[]>();

export function CSVViewer({ runId, stepName, fileKey, sizeBytes }: FileViewerProps) {
  const url = api.fileUrl(runId, stepName, fileKey);
  const parentRef = useRef<HTMLDivElement>(null);

  const { data: parsed, isLoading, isError } = useQuery<ParsedCSV>({
    queryKey: ["file", runId, stepName, fileKey],
    queryFn: async () => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const text = await res.text();
      const result = Papa.parse<string[]>(text, { skipEmptyLines: true });
      if (result.data.length === 0) return { headers: [], rows: [] };
      const [headers, ...rows] = result.data;
      return { headers: headers as string[], rows };
    },
    staleTime: Infinity,
  });

  const columns = useMemo(
    () =>
      (parsed?.headers ?? []).map((h, i) =>
        columnHelper.accessor((row) => row[i] ?? "", {
          id: `col-${i}`,
          header: h,
        })
      ),
    [parsed?.headers]
  );

  const table = useReactTable({
    data: parsed?.rows ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const rows = table.getRowModel().rows;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 32,
    overscan: 10,
  });

  if (isLoading) {
    return (
      <div className="p-4 space-y-2">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-7 bg-gray-800 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="px-4 py-3 text-red-400 text-xs">Failed to load file.</p>;
  }

  if (!parsed || parsed.headers.length === 0) {
    return <p className="px-4 py-3 text-gray-500 text-xs">Empty file.</p>;
  }

  const totalRows = parsed.rows.length;
  const totalCols = parsed.headers.length;
  const fileSizeStr = sizeBytes != null ? ` · ${(sizeBytes / 1024).toFixed(1)} KB` : "";

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-gray-500 shrink-0">
        {totalRows.toLocaleString()} rows · {totalCols} columns{fileSizeStr}
      </div>

      <div className="flex-1 min-h-0 overflow-auto" ref={parentRef}>
        <table className="text-xs font-mono border-collapse" style={{ minWidth: "100%" }}>
          <thead className="sticky top-0 z-10 bg-gray-900">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-3 py-2 text-left text-gray-400 font-medium border-b border-r border-gray-800 whitespace-nowrap bg-gray-900"
                    style={{ minWidth: 100 }}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody style={{ position: "relative", height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const row = rows[item.index];
              return (
                <tr
                  key={row.id}
                  style={{ position: "absolute", top: item.start, width: "100%", display: "flex" }}
                  className="border-b border-gray-900/60 hover:bg-gray-800/40 transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-3 py-1 text-gray-300 border-r border-gray-900/60 shrink-0 truncate"
                      style={{ minWidth: 100, flex: "1 0 100px" }}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
