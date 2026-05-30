import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
    <div className="flex h-screen overflow-hidden">
      <PipelineList selected={selectedPipeline} onSelect={handleSelectPipeline} />

      {selectedPipeline ? (
        <div className="flex flex-1 overflow-hidden">
          {/* Run list panel */}
          <div
            className={`border-r border-gray-800 overflow-hidden transition-all ${
              selectedRunId ? "w-80 shrink-0" : "flex-1"
            }`}
          >
            <RunList
              pipeline={selectedPipeline}
              selectedRunId={selectedRunId}
              onSelect={setSelectedRunId}
            />
          </div>

          {/* Run detail panel */}
          {selectedRunId && pipeline && (
            <div className="flex-1 overflow-hidden">
              <RunDetail pipeline={pipeline} runId={selectedRunId} />
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-600 text-xs">
          Select a pipeline
        </div>
      )}
    </div>
  );
}
