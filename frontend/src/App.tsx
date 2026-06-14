import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Activity } from "lucide-react";
import { PipelineList } from "./components/PipelineList";
import { RunList } from "./components/RunList";
import { RunDetail } from "./components/RunDetail";
import { api, Pipeline } from "./api";

export default function App() {
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const { data: pipeline } = useQuery<Pipeline>({
    queryKey: ["pipeline", selectedPipeline],
    queryFn: () => api.pipeline(selectedPipeline!),
    enabled: !!selectedPipeline,
  });

  function handleSelectPipeline(name: string) {
    setSelectedPipeline(name);
    setSelectedRunId(null);
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top header */}
      <header className="h-10 shrink-0 border-b border-gray-800 bg-gray-900/60 flex items-center px-4 gap-2">
        <Activity className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-semibold text-gray-200 tracking-tight">runlet</span>
        <span className="text-gray-700 text-xs ml-1">pipeline monitor</span>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        <PipelineList selected={selectedPipeline} onSelect={handleSelectPipeline} />

        {selectedPipeline ? (
          <div className="flex flex-1 overflow-hidden">
            {/* Run list panel */}
            <div
              className={`border-r border-gray-800 overflow-hidden transition-[width] duration-300 ${
                selectedRunId ? "w-72 shrink-0" : "flex-1"
              }`}
            >
              <RunList
                pipeline={selectedPipeline}
                selectedRunId={selectedRunId}
                onSelect={setSelectedRunId}
              />
            </div>

            {/* Run detail panel — animated entry */}
            <AnimatePresence>
              {selectedRunId && pipeline && (
                <motion.div
                  key={selectedRunId}
                  initial={{ opacity: 0, x: 16 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 16 }}
                  transition={{ duration: 0.2, ease: "easeOut" }}
                  className="flex-1 overflow-hidden"
                >
                  <RunDetail pipeline={pipeline} runId={selectedRunId} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-700">
            <Activity className="w-8 h-8 opacity-20" />
            <span className="text-xs">Select a pipeline to get started</span>
          </div>
        )}
      </div>
    </div>
  );
}
