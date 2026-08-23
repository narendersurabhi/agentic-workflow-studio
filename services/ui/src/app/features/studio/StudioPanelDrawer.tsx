import type { ReactNode } from "react";

import StudioWorkbenchIcon from "./StudioWorkbenchIcon";

export type StudioPanelDrawerId = "palette" | "compile" | "setup" | "interface" | "library";

const PANEL_ICON_KIND: Record<
  StudioPanelDrawerId,
  "palette" | "inspect" | "zap" | "library" | "activity" | "menu"
> = {
  palette: "palette",
  compile: "activity",
  setup: "menu",
  interface: "zap",
  library: "library",
};

const PANEL_IDS: StudioPanelDrawerId[] = ["palette", "compile", "setup", "interface", "library"];

export type StudioPanelDrawerDefinition = {
  title: string;
  content: ReactNode;
  panelDomId?: string;
  bodyClassName?: string;
  badge?: string | number | null;
};

export type StudioPanelDrawerProps = {
  /**
   * The drawer's currently open panel. Accepts a wider id space than the
   * icon strip's own `StudioPanelDrawerId` — e.g. `"inspector"`, which is
   * opened programmatically on node selection rather than via an icon — so
   * the drawer can display content the strip itself never links to.
   */
  activePanelId: string | null;
  onSelectPanel: (panelId: StudioPanelDrawerId) => void;
  getPanelTitle: (panelId: StudioPanelDrawerId) => string;
  getPanelBadge: (panelId: StudioPanelDrawerId) => string | number | null | undefined;
  /** The resolved definition for `activePanelId`, or null while closed/loading. */
  activeDefinition: StudioPanelDrawerDefinition | null;
  drawerWidth: number;
  onResizeStart: (event: React.MouseEvent) => void;
  onClose: () => void;
};

export function StudioPanelDrawer({
  activePanelId,
  onSelectPanel,
  getPanelTitle,
  getPanelBadge,
  activeDefinition,
  drawerWidth,
  onResizeStart,
  onClose,
}: StudioPanelDrawerProps) {
  const isOpen = Boolean(activePanelId && activeDefinition);

  return (
    <>
      {/* ── Panel icon strip (left side of stage) ── */}
      <div className="pointer-events-auto absolute left-3 top-3 z-20 flex flex-col gap-1.5">
        {PANEL_IDS.map((panelId) => {
          const isActive = activePanelId === panelId;
          const badge = getPanelBadge(panelId);
          return (
            <button
              key={panelId}
              type="button"
              title={getPanelTitle(panelId)}
              aria-label={getPanelTitle(panelId)}
              className={`relative flex h-9 w-9 items-center justify-center rounded-xl border transition ${
                isActive
                  ? "border-sky-300/40 bg-accent-sky text-text-sky-token shadow-[0_0_0_2px_rgba(56,189,248,0.18)]"
                  : "border-white/12 bg-[rgba(9,16,27,0.65)] text-text-md hover:border-white/20 hover:bg-[rgba(9,16,27,0.85)] hover:text-text-hi"
              } backdrop-blur-sm`}
              onClick={() => onSelectPanel(panelId)}
            >
              <StudioWorkbenchIcon kind={PANEL_ICON_KIND[panelId]} className="h-4 w-4" />
              {badge ? (
                <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border border-white/20 bg-sky-500 text-[8px] font-bold text-white">
                  {badge}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {/* ── Right-side overlay drawer ── */}
      <div
        className={`pointer-events-auto absolute right-0 top-0 z-30 flex h-full flex-col overflow-hidden rounded-r-[24px] border-l border-white/10 bg-[rgba(9,14,23,0.88)] shadow-[-12px_0_40px_rgba(9,14,23,0.4)] backdrop-blur-xl transition-transform duration-200 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        style={{ width: drawerWidth }}
      >
        {/* Left resize handle */}
        <div
          className="absolute left-0 top-0 z-10 h-full w-1 cursor-ew-resize transition hover:bg-sky-300/30 active:bg-sky-300/50"
          onMouseDown={(event) => {
            event.preventDefault();
            onResizeStart(event);
          }}
          title="Drag to resize"
        />
        {activeDefinition ? (
          <>
            {/* Drawer header */}
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/8 bg-[rgba(9,16,27,0.6)] px-4 py-3">
              <div className="flex items-center gap-2">
                <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-text-hi">
                  {activeDefinition.title}
                </div>
                {activeDefinition.badge ? (
                  <span className="rounded-full border border-subtle bg-surface-1 px-2 py-0.5 text-[9px] tracking-[0.14em] text-text-md">
                    {activeDefinition.badge}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                className="flex h-6 w-6 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-text-lo transition hover:bg-white/10 hover:text-text-hi"
                onClick={onClose}
                aria-label="Close panel"
              >
                ✕
              </button>
            </div>
            {/* Drawer content */}
            <div
              id={activeDefinition.panelDomId}
              className={`min-h-0 flex-1 overflow-auto ${activeDefinition.bodyClassName || ""}`.trim()}
            >
              {activeDefinition.content}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

export default StudioPanelDrawer;
