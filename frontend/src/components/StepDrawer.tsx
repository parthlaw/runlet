import { AnimatePresence, motion } from "framer-motion";
import { StepDetail } from "./StepDetail";
import type { StepRecord } from "../api";

interface Props {
  runId: string;
  stepRecord: StepRecord | null;
  onClose: () => void;
}

export function StepDrawer({ runId, stepRecord, onClose }: Props) {
  return (
    <AnimatePresence>
      {stepRecord && (
        <>
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.aside
            key="drawer"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="fixed top-0 right-0 z-[60] h-full w-full md:w-[720px] lg:w-[840px] bg-surface-container border-l border-outline-variant shadow-2xl flex flex-col"
          >
            <StepDetail runId={runId} stepRecord={stepRecord} onClose={onClose} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
