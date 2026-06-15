import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
  Lock,
  MinusCircle,
  XCircle,
} from "lucide-react";
import type { StepRecord } from "../api";

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-[18px] h-[18px] text-emerald-400 shrink-0" />,
  failed: <XCircle className="w-[18px] h-[18px] text-error shrink-0" />,
  running: <Loader2 className="w-[18px] h-[18px] text-tertiary-container shrink-0 animate-spin" />,
  skipped: <MinusCircle className="w-[18px] h-[18px] text-on-surface-variant shrink-0" />,
  pending: <Clock className="w-[18px] h-[18px] text-on-surface-variant shrink-0" />,
};

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

interface Props {
  steps: StepRecord[];
  onSelectStep: (name: string) => void;
}

export function StepExecutionTree({ steps, onSelectStep }: Props) {
  const runningStep = steps.find((s) => s.status === "running")?.step_name ?? null;
  const [expanded, setExpanded] = useState<string | null>(runningStep);

  useEffect(() => {
    if (runningStep) setExpanded(runningStep);
  }, [runningStep]);

  return (
    <div className="px-4">
      <h3 className="font-label-caps text-label-caps text-on-surface-variant mb-4">
        STEP EXECUTION TREE
      </h3>
      <div className="flex flex-col gap-panel-gap">
        {steps.map((step, index) => {
          const isRunning = step.status === "running";
          const isPending = step.status === "pending";
          const isExpanded = expanded === step.step_name;
          const borderClass = isRunning
            ? "border-tertiary-container/30"
            : "border-outline-variant";

          return (
            <div
              key={step.step_name}
              className={`flex flex-col bg-surface border ${borderClass} rounded-lg overflow-hidden mb-2 ${
                isPending ? "opacity-60" : ""
              } ${isRunning ? "bg-tertiary-container/5" : ""}`}
            >
              <button
                type="button"
                onClick={() => {
                  if (isExpanded) {
                    setExpanded(null);
                  } else {
                    setExpanded(step.step_name);
                  }
                  onSelectStep(step.step_name);
                }}
                className={`flex items-center justify-between p-3 w-full text-left transition-colors duration-200 ${
                  !isRunning ? "hover:bg-surface-variant cursor-pointer" : ""
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  {STATUS_ICON[step.status] ?? STATUS_ICON.pending}
                  <span className="font-body-sm text-body-sm font-semibold truncate">
                    {index + 1}. {step.step_name}
                  </span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span
                    className={`font-code-sm text-code-sm ${
                      isRunning ? "text-tertiary-container" : "text-on-surface-variant"
                    }`}
                  >
                    {formatDuration(step.duration_seconds)}
                  </span>
                  {isPending ? (
                    <Lock className="w-5 h-5 text-on-surface-variant" />
                  ) : isExpanded ? (
                    <ChevronUp className="w-5 h-5 text-on-surface-variant" />
                  ) : (
                    <ChevronDown className="w-5 h-5 text-on-surface-variant" />
                  )}
                </div>
              </button>

              {isExpanded && step.error && (
                <div className="px-4 pb-3 border-t border-outline-variant">
                  <pre className="font-code-sm text-code-sm text-error/90 whitespace-pre-wrap mt-3 leading-relaxed">
                    {step.error}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
