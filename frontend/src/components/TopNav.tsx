import { Search } from "lucide-react";

interface Props {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  searchEnabled: boolean;
}

export function TopNav({ searchQuery, onSearchChange, searchEnabled }: Props) {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-gutter h-14 bg-surface border-b border-outline-variant">
      <span className="font-headline-md text-headline-md font-bold text-primary">Runlet</span>

      <div className="flex items-center gap-stack-md">
        <div className="flex items-center bg-surface-variant rounded-lg px-2 h-9 border border-outline-variant">
          <Search className="w-5 h-5 text-on-surface-variant mr-1 shrink-0" />
          <input
            disabled={!searchEnabled}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="bg-transparent border-none focus:ring-0 text-body-sm w-48 text-on-surface placeholder:text-on-surface-variant disabled:opacity-40 disabled:cursor-not-allowed"
            placeholder={searchEnabled ? "Search run IDs…" : "Select a pipeline first"}
            type="text"
          />
        </div>
        <div className="w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center border border-outline-variant overflow-hidden">
          <span className="font-label-caps text-label-caps text-on-secondary-container text-[10px]">
            U
          </span>
        </div>
      </div>
    </header>
  );
}
