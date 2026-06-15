import type { RunRecord, StepRecord } from "../api";

type Status = RunRecord["status"] | StepRecord["status"];

const BADGE: Record<string, { pill: string; dot: string; label: string }> = {
  success: {
    pill: "bg-emerald-500/10 border-emerald-500/30",
    dot: "bg-emerald-400",
    label: "text-emerald-400",
  },
  failed: {
    pill: "bg-error/10 border-error/30",
    dot: "bg-error",
    label: "text-error",
  },
  running: {
    pill: "bg-tertiary-container/10 border-tertiary-container/30",
    dot: "bg-tertiary-container status-pulse",
    label: "text-tertiary",
  },
  cancelled: {
    pill: "bg-outline/10 border-outline/30",
    dot: "bg-outline",
    label: "text-on-surface-variant",
  },
  skipped: {
    pill: "bg-outline/10 border-outline/30",
    dot: "bg-outline",
    label: "text-on-surface-variant",
  },
  pending: {
    pill: "bg-outline/10 border-outline/30",
    dot: "bg-outline",
    label: "text-on-surface-variant",
  },
};

interface Props {
  status: Status;
  className?: string;
}

export function StatusBadge({ status, className = "" }: Props) {
  const cfg = BADGE[status] ?? BADGE.pending;
  return (
    <div
      className={`inline-flex items-center gap-2 px-2 py-0.5 rounded-full border ${cfg.pill} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
      <span className={`font-label-caps text-label-caps uppercase ${cfg.label}`}>
        {status}
      </span>
    </div>
  );
}
