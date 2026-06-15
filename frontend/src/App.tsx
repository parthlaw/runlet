import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, GitBranch } from "lucide-react";
import { PipelineList } from "./components/PipelineList";
import { RunList } from "./components/RunList";
import { RunDetail } from "./components/RunDetail";
import { api, Pipeline } from "./api";

function NoPipelinesState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 px-8">
      <GitBranch className="w-10 h-10 text-content-ghost opacity-40" />
      <div className="text-center">
        <p className="text-content text-sm font-semibold">No pipelines configured</p>
        <p className="text-content-muted text-xs mt-1">Add a pipeline using the decorator API:</p>
      </div>
      <pre className="bg-[#0d0d15] border border-outline-strong rounded px-4 py-3 font-mono text-xs text-content-dim leading-relaxed w-full max-w-xs">
        {`from runlet import pipeline, step\n\n@pipeline\ndef my_pipeline():\n    ...`}
      </pre>
    </div>
  );
}

function NoSelectionState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2">
      <Activity className="w-8 h-8 text-content-ghost opacity-20" />
      <p className="text-content-ghost text-xs">Select a pipeline to get started</p>
      <p className="text-content-ghost/60 text-[11px]">Runs and step details will appear here</p>
    </div>
  );
}

export default function App() {
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const { data: pipelines } = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: api.pipelines,
  });

  const { data: pipeline } = useQuery<Pipeline>({
    queryKey: ["pipeline", selectedPipeline],
    queryFn: () => api.pipeline(selectedPipeline!),
    enabled: !!selectedPipeline,
  });

  function handleSelectPipeline(name: string) {
    setSelectedPipeline(name);
    setSelectedRunId(null);
  }

  const hasPipelines = pipelines && pipelines.length > 0;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-surface">
      {/* Top header */}
      <header className="h-11 shrink-0 border-b border-outline-strong bg-surface-low flex items-center px-4 gap-2">
        <Activity className="w-4 h-4 text-primary" />
        <span className="text-sm font-semibold text-content tracking-tight">runlet</span>
        <span className="text-content-ghost text-xs ml-1">pipeline monitor</span>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        <PipelineList selected={selectedPipeline} onSelect={handleSelectPipeline} />

        {!hasPipelines && pipelines !== undefined ? (
          <NoPipelinesState />
        ) : selectedPipeline ? (
          <div className="flex flex-1 overflow-hidden">
            {/* Run list panel */}
            <div
              className={`border-r border-outline-strong overflow-hidden transition-[width] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] ${
                selectedRunId ? "w-72 shrink-0" : "flex-1"
              }`}
            >
              <RunList
                pipeline={selectedPipeline}
                selectedRunId={selectedRunId}
                onSelect={setSelectedRunId}
              />
            </div>

            {/* Run detail panel */}
            <AnimatePresence>
              {selectedRunId && pipeline && (
                <motion.div
                  key={selectedRunId}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 12 }}
                  transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
                  className="flex-1 overflow-hidden"
                >
                  <RunDetail pipeline={pipeline} runId={selectedRunId} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ) : (
          <NoSelectionState />
        )}
      </div>
    </div>
  );
}
