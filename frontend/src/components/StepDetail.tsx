import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { JsonView, allExpanded, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";
import {
  CheckCircle2,
  XCircle,
  Loader2,
  MinusCircle,
  Clock,
  ChevronRight,
  ChevronDown,
  FileJson2,
  FileText,
  FileSpreadsheet,
} from "lucide-react";
import { api, isFileUri, type FileInfo, type FileFormat, type StepRecord } from "../api";
import { FileViewer } from "./viewers/FileViewer";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  failed: <XCircle className="w-4 h-4 text-red-400" />,
  running: <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />,
  skipped: <MinusCircle className="w-4 h-4 text-gray-500" />,
  pending: <Clock className="w-4 h-4 text-gray-600" />,
};

const STATUS_BADGE: Record<string, string> = {
  success: "bg-emerald-950/60 text-emerald-400 border-emerald-800/60",
  failed: "bg-red-950/60 text-red-400 border-red-800/60",
  running: "bg-amber-950/60 text-amber-400 border-amber-800/60",
  skipped: "bg-gray-800/60 text-gray-500 border-gray-700/60",
  pending: "bg-gray-900/60 text-gray-600 border-gray-800/60",
};

const FORMAT_ICON: Record<FileFormat, React.ReactNode> = {
  jsonl: <FileJson2 className="w-3.5 h-3.5" />,
  json: <FileJson2 className="w-3.5 h-3.5" />,
  csv: <FileSpreadsheet className="w-3.5 h-3.5" />,
  tsv: <FileSpreadsheet className="w-3.5 h-3.5" />,
  text: <FileText className="w-3.5 h-3.5" />,
};

const FORMAT_COLORS: Record<FileFormat, string> = {
  jsonl: "text-indigo-400 bg-indigo-950/40 border-indigo-800/40",
  json: "text-violet-400 bg-violet-950/40 border-violet-800/40",
  csv: "text-teal-400 bg-teal-950/40 border-teal-800/40",
  tsv: "text-teal-400 bg-teal-950/40 border-teal-800/40",
  text: "text-gray-400 bg-gray-800/40 border-gray-700/40",
};

function formatSize(bytes: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ---------------------------------------------------------------------------
// Collapsible file section
// ---------------------------------------------------------------------------

function FileSection({
  runId,
  stepName,
  file,
}: {
  runId: string;
  stepName: string;
  file: FileInfo;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="border-b border-gray-800/60 last:border-b-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-gray-800/30 transition-colors text-left"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-500 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-500 shrink-0" />
        )}
        <span className={`flex items-center gap-1.5 px-1.5 py-0.5 rounded border text-[10px] font-medium ${FORMAT_COLORS[file.format]}`}>
          {FORMAT_ICON[file.format]}
          {file.format.toUpperCase()}
        </span>
        <span className="text-xs font-mono text-gray-300">{file.key}</span>
        {file.size_bytes != null && (
          <span className="ml-auto text-xs text-gray-600 shrink-0">{formatSize(file.size_bytes)}</span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="h-64 border-t border-gray-800/40 bg-gray-950/40">
              <FileViewer
                runId={runId}
                stepName={stepName}
                fileKey={file.key}
                format={file.format}
                sizeBytes={file.size_bytes}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepDetail
// ---------------------------------------------------------------------------

interface Props {
  runId: string;
  stepRecord: StepRecord;
}

export function StepDetail({ runId, stepRecord }: Props) {
  const hasFileUris = Object.values(stepRecord.output).some(isFileUri);

  const { data: files = [] } = useQuery<FileInfo[]>({
    queryKey: ["files", runId, stepRecord.step_name],
    queryFn: () => api.files(runId, stepRecord.step_name),
    staleTime: Infinity,
    enabled: hasFileUris,
  });

  const scalarOutput = Object.fromEntries(
    Object.entries(stepRecord.output).filter(([, v]) => !isFileUri(v))
  );
  const hasScalarOutput = Object.keys(scalarOutput).length > 0;
  const isEmpty = !hasScalarOutput && files.length === 0 && stepRecord.status !== "running";

  return (
    <motion.div
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="flex flex-col h-full overflow-y-auto"
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 bg-gray-900/50 shrink-0">
        <div className="flex items-center gap-2.5">
          {STATUS_ICON[stepRecord.status]}
          <span className="font-mono text-sm font-semibold text-gray-100 truncate">
            {stepRecord.step_name}
          </span>
          <span className={`ml-auto shrink-0 text-[10px] font-medium px-2 py-0.5 rounded-full border ${STATUS_BADGE[stepRecord.status]}`}>
            {stepRecord.status}
          </span>
          {stepRecord.attempt > 0 && (
            <span className="text-[10px] text-gray-600 shrink-0">#{stepRecord.attempt + 1}</span>
          )}
        </div>

        <div className="flex items-center gap-4 mt-1.5 text-[11px] text-gray-500">
          {stepRecord.duration_seconds != null && (
            <span className="font-mono">{stepRecord.duration_seconds.toFixed(2)}s</span>
          )}
          <span>{new Date(stepRecord.recorded_at).toLocaleString()}</span>
        </div>

        {stepRecord.error && (
          <div className="mt-2 text-xs text-red-300 bg-red-950/30 rounded-lg px-3 py-2 border border-red-900/40 font-mono leading-relaxed">
            {stepRecord.error}
          </div>
        )}
      </div>

      {/* Scalar output */}
      {hasScalarOutput && (
        <div className="border-b border-gray-800/60 shrink-0">
          <div className="px-4 py-2 text-[10px] uppercase tracking-widest text-gray-600 font-medium">
            Output
          </div>
          <div className="px-4 pb-3">
            <JsonView
              data={scalarOutput}
              shouldExpandNode={allExpanded}
              style={{ ...defaultStyles, container: "bg-transparent text-xs font-mono" }}
            />
          </div>
        </div>
      )}

      {/* Files */}
      {files.length > 0 && (
        <div className="shrink-0">
          <div className="px-4 py-2 text-[10px] uppercase tracking-widest text-gray-600 font-medium border-b border-gray-800/60">
            Files
          </div>
          {files.map((file) => (
            <FileSection key={file.key} runId={runId} stepName={stepRecord.step_name} file={file} />
          ))}
        </div>
      )}

      {isEmpty && (
        <div className="flex-1 flex items-center justify-center text-xs text-gray-700">
          No output recorded.
        </div>
      )}
    </motion.div>
  );
}
