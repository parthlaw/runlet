import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";

interface Props {
  open: boolean;
  onClose: () => void;
  record: Record<string, unknown>;
  rowIndex: number;
  totalRows: number;
}

function findMatchOffsets(text: string, query: string): number[] {
  if (!query.trim()) return [];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const offsets: number[] = [];
  let pos = 0;
  while (pos < lowerText.length) {
    const idx = lowerText.indexOf(lowerQuery, pos);
    if (idx === -1) break;
    offsets.push(idx);
    pos = idx + 1;
  }
  return offsets;
}

function HighlightedJson({
  text,
  query,
  activeOffset,
  scrollRef,
}: {
  text: string;
  query: string;
  activeOffset: number | null;
  scrollRef: RefObject<HTMLPreElement>;
}) {
  const markRefs = useRef<Map<number, HTMLSpanElement>>(new Map());

  const parts = useMemo(() => {
    if (!query.trim()) {
      return [{ text, highlight: false, offset: -1 }];
    }
    const offsets = findMatchOffsets(text, query);
    if (offsets.length === 0) {
      return [{ text, highlight: false, offset: -1 }];
    }
    const qLen = query.length;
    const result: { text: string; highlight: boolean; offset: number }[] = [];
    let cursor = 0;
    for (const offset of offsets) {
      if (offset > cursor) {
        result.push({ text: text.slice(cursor, offset), highlight: false, offset: -1 });
      }
      result.push({
        text: text.slice(offset, offset + qLen),
        highlight: true,
        offset,
      });
      cursor = offset + qLen;
    }
    if (cursor < text.length) {
      result.push({ text: text.slice(cursor), highlight: false, offset: -1 });
    }
    return result;
  }, [text, query]);

  useEffect(() => {
    if (activeOffset == null || !scrollRef.current) return;
    const el = markRefs.current.get(activeOffset);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [activeOffset, scrollRef]);

  return (
    <pre
      ref={scrollRef}
      className="font-code-sm text-code-sm text-on-surface leading-relaxed whitespace-pre-wrap break-words"
    >
      {parts.map((part, i) =>
        part.highlight ? (
          <mark
            key={i}
            ref={(el) => {
              if (el && part.offset >= 0) markRefs.current.set(part.offset, el);
            }}
            className={`rounded px-0.5 ${
              part.offset === activeOffset
                ? "bg-primary text-on-primary"
                : "bg-primary/30 text-on-surface"
            }`}
          >
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        )
      )}
    </pre>
  );
}

export function JSONRecordModal({ open, onClose, record, rowIndex, totalRows }: Props) {
  const [search, setSearch] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const scrollRef = useRef<HTMLPreElement>(null);

  const formatted = useMemo(() => JSON.stringify(record, null, 2), [record]);
  const matchOffsets = useMemo(
    () => findMatchOffsets(formatted, search),
    [formatted, search]
  );

  useEffect(() => {
    setMatchIndex(0);
  }, [search, record]);

  useEffect(() => {
    if (!open) {
      setSearch("");
      setMatchIndex(0);
    }
  }, [open]);

  const activeOffset =
    matchOffsets.length > 0 ? matchOffsets[matchIndex] ?? matchOffsets[0] : null;

  function goPrev() {
    if (matchOffsets.length === 0) return;
    setMatchIndex((i) => (i - 1 + matchOffsets.length) % matchOffsets.length);
  }

  function goNext() {
    if (matchOffsets.length === 0) return;
    setMatchIndex((i) => (i + 1) % matchOffsets.length);
  }

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[70] flex flex-col w-[85vw] max-w-[85vw] h-[80vh] max-h-[80vh] -translate-x-1/2 -translate-y-1/2 bg-surface-container border border-outline-variant rounded-xl shadow-2xl overflow-hidden focus:outline-none">
          <div className="shrink-0 flex items-center gap-3 px-gutter py-3 border-b border-outline-variant bg-surface">
            <Dialog.Title className="font-headline-md text-[16px] font-bold text-on-surface shrink-0">
              Row {rowIndex + 1}
              <span className="text-on-surface-variant font-body-sm text-body-sm font-normal ml-2">
                of {totalRows.toLocaleString()}
              </span>
            </Dialog.Title>

            <div className="flex-1 flex items-center gap-2 max-w-md ml-auto">
              <div className="relative flex-1">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search in JSON…"
                  className="w-full bg-surface-variant border border-outline-variant rounded-lg pl-8 pr-3 py-1.5 text-body-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:border-primary"
                />
              </div>
              {search.trim() && (
                <span className="font-code-sm text-code-sm text-on-surface-variant whitespace-nowrap">
                  {matchOffsets.length === 0
                    ? "0 matches"
                    : `${matchIndex + 1} / ${matchOffsets.length}`}
                </span>
              )}
              <button
                type="button"
                onClick={goPrev}
                disabled={matchOffsets.length === 0}
                className="p-1.5 rounded hover:bg-surface-variant disabled:opacity-30 text-on-surface-variant"
                aria-label="Previous match"
              >
                <ChevronUp className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={goNext}
                disabled={matchOffsets.length === 0}
                className="p-1.5 rounded hover:bg-surface-variant disabled:opacity-30 text-on-surface-variant"
                aria-label="Next match"
              >
                <ChevronDown className="w-4 h-4" />
              </button>
            </div>

            <Dialog.Close asChild>
              <button
                type="button"
                className="p-1.5 rounded hover:bg-surface-variant text-on-surface-variant shrink-0"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </Dialog.Close>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-gutter bg-surface-container-lowest">
            <HighlightedJson
              text={formatted}
              query={search}
              activeOffset={activeOffset}
              scrollRef={scrollRef}
            />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
