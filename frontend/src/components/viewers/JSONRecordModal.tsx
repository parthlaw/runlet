import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { common, createLowlight } from "lowlight";
import type { Root, Element, Text } from "hast";

// ---------------------------------------------------------------------------
// Lowlight instance (JSON grammar only, tree-shaken)
// ---------------------------------------------------------------------------
const lowlight = createLowlight(common);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Props {
  open: boolean;
  onClose: () => void;
  record: Record<string, unknown>;
  rowIndex: number;
  totalRows: number;
}

/** A flat token produced by walking the lowlight HAST */
interface Token {
  text: string;
  cls: string | null; // e.g. "hljs-attr", "hljs-string", null for whitespace
}

/** A render-ready segment: a contiguous run of characters sharing one (cls, isMatch) pair */
interface Segment {
  text: string;
  cls: string | null;
  isMatch: boolean;
  offset: number; // character offset in the full text — used to identify active mark
}

// ---------------------------------------------------------------------------
// HAST → flat token list
// ---------------------------------------------------------------------------

function flattenHast(nodes: (Element | Text)[], parentCls: string | null): Token[] {
  const result: Token[] = [];
  for (const node of nodes) {
    if (node.type === "text") {
      result.push({ text: node.value, cls: parentCls });
    } else if (node.type === "element") {
      const cls = (node.properties?.className as string[] | undefined)?.[0] ?? parentCls;
      result.push(...flattenHast(node.children as (Element | Text)[], cls));
    }
  }
  return result;
}

/** Tokenize JSON text via lowlight → flat [{text, cls}] list */
function tokenize(text: string): Token[] {
  let tree: Root;
  try {
    tree = lowlight.highlight("json", text);
  } catch {
    return [{ text, cls: null }];
  }
  return flattenHast(tree.children as (Element | Text)[], null);
}

// ---------------------------------------------------------------------------
// Search helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Core: merge token boundaries with search-match boundaries → Segment[]
// ---------------------------------------------------------------------------

function buildSegments(text: string, tokens: Token[], matchOffsets: number[], queryLen: number): Segment[] {
  if (tokens.length === 0) return [];

  // 1. Build a per-character class lookup from tokens
  const charCls: (string | null)[] = new Array(text.length).fill(null);
  let cursor = 0;
  for (const token of tokens) {
    for (let i = 0; i < token.text.length; i++) {
      if (cursor + i < charCls.length) charCls[cursor + i] = token.cls;
    }
    cursor += token.text.length;
  }

  // 2. Build a per-character match set
  const matchSet = new Set<number>();
  for (const off of matchOffsets) {
    for (let i = 0; i < queryLen; i++) {
      matchSet.add(off + i);
    }
  }

  // 3. Walk characters, emit a new segment whenever cls or isMatch changes
  const segments: Segment[] = [];
  let segStart = 0;
  let segCls = charCls[0];
  let segIsMatch = matchSet.has(0);

  for (let i = 1; i < text.length; i++) {
    const cls = charCls[i];
    const isMatch = matchSet.has(i);
    if (cls !== segCls || isMatch !== segIsMatch) {
      segments.push({ text: text.slice(segStart, i), cls: segCls, isMatch: segIsMatch, offset: segStart });
      segStart = i;
      segCls = cls;
      segIsMatch = isMatch;
    }
  }
  // Final segment
  segments.push({ text: text.slice(segStart), cls: segCls, isMatch: segIsMatch, offset: segStart });

  return segments;
}

// ---------------------------------------------------------------------------
// HighlightedJson component
// ---------------------------------------------------------------------------

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
  const markRefs = useRef<Map<number, HTMLElement>>(new Map());

  // Tokenize once per text change (formatted JSON doesn't change per record)
  const tokens = useMemo(() => tokenize(text), [text]);

  const matchOffsets = useMemo(() => findMatchOffsets(text, query), [text, query]);
  const queryLen = query.length;

  const segments = useMemo(
    () => buildSegments(text, tokens, matchOffsets, queryLen),
    [text, tokens, matchOffsets, queryLen],
  );

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
      {segments.map((seg, i) => {
        if (seg.isMatch) {
          // Find the match start offset (first char of this match run)
          const matchStart = matchOffsets.find((o) => o <= seg.offset && seg.offset < o + queryLen) ?? seg.offset;
          const isActive = matchStart === activeOffset;
          return (
            <mark
              key={i}
              ref={(el) => {
                if (el) markRefs.current.set(matchStart, el);
              }}
              className={`rounded px-0.5 ${
                isActive ? "bg-primary text-on-primary" : "bg-primary/30 text-on-surface"
              }`}
            >
              {seg.text}
            </mark>
          );
        }
        return (
          <span key={i} className={seg.cls ?? undefined}>
            {seg.text}
          </span>
        );
      })}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// JSONRecordModal
// ---------------------------------------------------------------------------

export function JSONRecordModal({ open, onClose, record, rowIndex, totalRows }: Props) {
  const [search, setSearch] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const scrollRef = useRef<HTMLPreElement>(null);

  const formatted = useMemo(() => JSON.stringify(record, null, 2), [record]);
  const matchOffsets = useMemo(() => findMatchOffsets(formatted, search), [formatted, search]);

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
