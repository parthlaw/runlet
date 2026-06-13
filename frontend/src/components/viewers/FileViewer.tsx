import type { FileFormat } from "../../api";
import type { FileViewerProps } from "./types";
import { JSONLViewer } from "./JSONLViewer";
import { JSONViewer } from "./JSONViewer";
import { CSVViewer } from "./CSVViewer";
import { TextViewer } from "./TextViewer";

const VIEWERS: Record<FileFormat, React.ComponentType<FileViewerProps>> = {
  jsonl: JSONLViewer,
  json: JSONViewer,
  csv: CSVViewer,
  tsv: CSVViewer,
  text: TextViewer,
};

export function FileViewer(props: FileViewerProps) {
  const Viewer = VIEWERS[props.format] ?? TextViewer;
  return <Viewer {...props} />;
}
