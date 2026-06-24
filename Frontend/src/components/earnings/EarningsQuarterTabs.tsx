import React from 'react';
import { EarningsQuarterTab } from '../../api/client';

interface EarningsQuarterTabsProps {
  tabs: EarningsQuarterTab[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

const formatMove = (pct?: number | null): string | null => {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return null;
  const prefix = pct > 0 ? '+' : '';
  return `${prefix}${pct.toFixed(2)}%`;
};

const EarningsQuarterTabs: React.FC<EarningsQuarterTabsProps> = ({ tabs, activeIndex, onSelect }) => {
  if (!tabs.length) return null;

  return (
    <div className="eq-tabs-scroll" role="tablist" aria-label="Earnings quarters">
      {tabs.map((tab, i) => {
        const move = formatMove(tab.move_1d_pct);
        const isActive = i === activeIndex;
        const moveClass = tab.move_1d_pct == null
          ? ''
          : tab.move_1d_pct > 0
          ? 'move-positive'
          : tab.move_1d_pct < 0
          ? 'move-negative'
          : 'move-zero';

        return (
          <button
            key={`${tab.label}-${i}`}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`eq-tab ${isActive ? 'is-active' : ''}`}
            onClick={() => onSelect(i)}
          >
            <span className="eq-tab-label">{tab.label}</span>
            {tab.is_future ? (
              <span className="eq-tab-future">upcoming</span>
            ) : move ? (
              <span className={`eq-tab-move ${moveClass}`}>{move}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
};

export default EarningsQuarterTabs;
