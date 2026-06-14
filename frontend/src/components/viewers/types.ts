import type { FileFormat } from "../../api";

export interface FileViewerProps {
  runId: string;
  stepName: string;
  fileKey: string;
  format: FileFormat;
  sizeBytes: number | null;
}
