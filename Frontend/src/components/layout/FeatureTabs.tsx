import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  LayoutDashboard,
  Briefcase,
  Star,
  SlidersHorizontal,
  CalendarClock,
  ShieldCheck,
  LucideIcon,
} from 'lucide-react';

export type FeatureTabId =
  | 'overview'
  | 'portfolio'
  | 'watchlist'
  | 'screener'
  | 'earnings'
  | 'governance';

interface TabDef {
  id: FeatureTabId;
  label: string;
  icon: LucideIcon;
  comingSoon?: boolean;
}

const TABS: TabDef[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
  { id: 'watchlist', label: 'Watchlist', icon: Star },
  { id: 'screener', label: 'Screener', icon: SlidersHorizontal },
  { id: 'earnings', label: 'Earnings', icon: CalendarClock, comingSoon: true },
  { id: 'governance', label: 'Governance', icon: ShieldCheck, comingSoon: true },
];

interface FeatureTabsProps {
  active: FeatureTabId;
  onChange: (id: FeatureTabId) => void;
}

export const FeatureTabs: React.FC<FeatureTabsProps> = ({ active, onChange }) => {
  const listRef = useRef<HTMLDivElement>(null);
  const btnRefs = useRef<Partial<Record<FeatureTabId, HTMLButtonElement | null>>>({});
  const [indicator, setIndicator] = useState<{ left: number; width: number }>({ left: 0, width: 0 });

  const syncIndicator = () => {
    const btn = btnRefs.current[active];
    const list = listRef.current;
    if (!btn || !list) return;
    setIndicator({ left: btn.offsetLeft, width: btn.offsetWidth });
  };

  useLayoutEffect(() => {
    syncIndicator();
    // Keep the active tab in view on mobile when it changes.
    btnRefs.current[active]?.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' });
  }, [active]);

  useEffect(() => {
    const onResize = () => syncIndicator();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [active]);

  return (
    <div className="feature-tabs" role="tablist" aria-label="ProspektLab terminal sections">
      <div className="feature-tabs-list" ref={listRef}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = active === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              ref={(el) => { btnRefs.current[tab.id] = el; }}
              className={`feature-tab ${isActive ? 'active' : ''}`}
              onClick={() => onChange(tab.id)}
            >
              <Icon size={15} strokeWidth={2.2} />
              <span>{tab.label}</span>
              {tab.comingSoon && <span className="feature-tab-soon">Soon</span>}
            </button>
          );
        })}
        <span
          className="feature-tab-indicator"
          style={{ transform: `translateX(${indicator.left}px)`, width: `${indicator.width}px` }}
        />
      </div>
    </div>
  );
};

export default FeatureTabs;
