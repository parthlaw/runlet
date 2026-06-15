import { Bell, HelpCircle, Search } from "lucide-react";

const NAV_ITEMS = [
  { label: "Dashboard", active: true },
  { label: "Workflows", active: false },
  { label: "Scheduler", active: false },
  { label: "Settings", active: false },
];

export function TopNav() {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-gutter h-14 bg-surface border-b border-outline-variant">
      <div className="flex items-center gap-stack-md">
        <span className="font-headline-md text-headline-md font-bold text-primary">Runlet</span>
        <nav className="hidden md:flex items-center gap-stack-md ml-stack-md">
          {NAV_ITEMS.map((item) => (
            <span
              key={item.label}
              aria-disabled="true"
              className={
                item.active
                  ? "font-body-base text-body-base text-primary border-b-2 border-primary py-4 px-2 cursor-default"
                  : "font-body-base text-body-base text-on-surface-variant px-2 py-1 rounded cursor-default opacity-60"
              }
            >
              {item.label}
            </span>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-stack-md pointer-events-none opacity-80">
        <div className="flex items-center bg-surface-variant rounded-lg px-2 h-9 border border-outline-variant">
          <Search className="w-5 h-5 text-on-surface-variant mr-1 shrink-0" />
          <input
            disabled
            className="bg-transparent border-none focus:ring-0 text-body-sm w-48 text-on-surface placeholder:text-on-surface-variant"
            placeholder="Search resources..."
            type="text"
          />
        </div>
        <button
          type="button"
          disabled
          className="p-2 text-on-surface-variant rounded"
          aria-label="Notifications"
        >
          <Bell className="w-5 h-5" />
        </button>
        <button
          type="button"
          disabled
          className="p-2 text-on-surface-variant rounded"
          aria-label="Help"
        >
          <HelpCircle className="w-5 h-5" />
        </button>
        <div className="w-8 h-8 rounded-full bg-secondary-container flex items-center justify-center border border-outline-variant overflow-hidden">
          <span className="font-label-caps text-label-caps text-on-secondary-container text-[10px]">
            U
          </span>
        </div>
      </div>
    </header>
  );
}
