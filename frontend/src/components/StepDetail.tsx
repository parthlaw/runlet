import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { JsonView, allExpanded, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";
import { Calendar, RefreshCw, Terminal, Timer, X } from "lucide-react";
import { api, isFileUri, type FileInfo, type FileFormat, type StepRecord } from "../api";
import { FileViewer } from "./viewers/FileViewer";
import { StatusBadge } from "./StatusBadge";

const FORMAT_LABEL: Record<FileFormat, string> = {
  jsonl: "data.jsonl",
  json: "data.json",
  csv: "metrics.csv",
  tsv: "data.tsv",
  text: "output.txt",
};

function formatSize(bytes: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

interface Props {
  runId: string;
  stepRecord: StepRecord;
  onClose: () => void;
}

export function StepDetail({ runId, stepRecord, onClose }: Props) {
  const hasFileUris = Object.values(stepRecord.output).some(isFileUri);
  const [activeFileIndex, setActiveFileIndex] = useState(0);

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

  const activeFile = files[activeFileIndex];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <header className="flex-none border-b border-outline-variant p-gutter bg-surface">
        <div className="flex items-center justify-between mb-stack-sm">
          <div className="flex items-center gap-stack-sm min-w-0">
            <Terminal className="w-5 h-5 text-on-surface-variant shrink-0" />
            <h1 className="font-headline-md text-headline-md tracking-tight truncate">
              {stepRecord.step_name}
            </h1>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-stack-xs hover:bg-surface-variant rounded-lg transition-colors duration-200 text-on-surface-variant shrink-0"
            aria-label="Close step detail"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-stack-md">
          <StatusBadge status={stepRecord.status} />
          {stepRecord.duration_seconds != null && (
            <div className="flex items-center gap-stack-xs text-on-surface-variant">
              <Timer className="w-[18px] h-[18px]" />
              <span className="font-body-sm text-body-sm">
                Duration: {Math.round(stepRecord.duration_seconds)}s
              </span>
            </div>
          )}
          {stepRecord.attempt > 0 && (
            <div className="flex items-center gap-stack-xs text-on-surface-variant">
              <RefreshCw className="w-[18px] h-[18px]" />
              <span className="font-body-sm text-body-sm">
                Attempt: {stepRecord.attempt + 1}
              </span>
            </div>
          )}
          <div className="flex items-center gap-stack-xs text-on-surface-variant">
            <Calendar className="w-[18px] h-[18px]" />
            <span className="font-body-sm text-body-sm">
              Started: {new Date(stepRecord.recorded_at).toLocaleString()}
            </span>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-gutter space-y-stack-md bg-surface-container-lowest">
        {stepRecord.error && (
          <section>
            <div className="flex items-center gap-stack-sm mb-stack-sm">
              <span className="font-label-caps text-label-caps text-error">Error Traceback</span>
              <div className="flex-1 h-px bg-error-container/20" />
            </div>
            <div className="bg-error-container/5 border border-error-container/20 rounded p-stack-md overflow-x-auto">
              <pre className="font-code-sm text-code-sm text-error/90 leading-relaxed whitespace-pre-wrap">
                {stepRecord.error}
              </pre>
            </div>
          </section>
        )}

        {hasScalarOutput && (
          <section>
            <div className="flex items-center gap-stack-sm mb-stack-sm">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Output (JSON)
              </span>
              <div className="flex-1 h-px bg-outline-variant" />
            </div>
            <div className="bg-surface border border-outline-variant rounded p-stack-md">
              <JsonView
                data={scalarOutput}
                shouldExpandNode={allExpanded}
                style={{
                  ...defaultStyles,
                  container: "bg-transparent font-code-sm text-code-sm text-on-surface",
                }}
              />
            </div>
          </section>
        )}

        {files.length > 0 && activeFile && (
          <section className="flex-1 flex flex-col min-h-[300px]">
            <div className="flex items-center gap-stack-sm mb-stack-sm">
              <span className="font-label-caps text-label-caps text-on-surface-variant uppercase">
                Artifacts Preview
              </span>
              <div className="flex-1 h-px bg-outline-variant" />
            </div>
            <div className="flex border-b border-outline-variant mb-panel-gap overflow-x-auto">
              {files.map((file, i) => (
                <button
                  key={file.key}
                  type="button"
                  onClick={() => setActiveFileIndex(i)}
                  className={`px-stack-md py-2 border-b-2 font-label-caps text-label-caps whitespace-nowrap transition-colors duration-200 ${
                    i === activeFileIndex
                      ? "border-primary text-primary bg-surface-container-high"
                      : "border-transparent text-on-surface-variant hover:bg-surface-variant"
                  }`}
                >
                  {FORMAT_LABEL[file.format] ?? file.key}
                  {file.size_bytes != null && (
                    <span className="ml-2 text-on-surface-variant font-code-sm text-code-sm normal-case">
                      ({formatSize(file.size_bytes)})
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="flex-1 border border-outline-variant rounded bg-surface overflow-hidden min-h-[280px]">
              <FileViewer
                runId={runId}
                stepName={stepRecord.step_name}
                fileKey={activeFile.key}
                format={activeFile.format}
                sizeBytes={activeFile.size_bytes}
              />
            </div>
          </section>
        )}

        {isEmpty && (
          <div className="flex items-center justify-center py-16 text-on-surface-variant font-body-sm text-body-sm">
            No output recorded.
          </div>
        )}
      </main>
    </div>
  );
}
