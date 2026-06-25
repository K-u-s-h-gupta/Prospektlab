import React, { useRef, useState, useEffect } from 'react';
import { EarningsQuarterTab } from '../../api/client';
import { ChevronLeft, ChevronRight } from 'lucide-react';

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
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showLeft, setShowLeft] = useState(false);
  const [showRight, setShowRight] = useState(false);

  const checkScroll = () => {
    if (scrollRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current;
      setShowLeft(scrollLeft > 0);
      setShowRight(Math.ceil(scrollLeft + clientWidth) < scrollWidth);
    }
  };

  useEffect(() => {
    checkScroll();
    window.addEventListener('resize', checkScroll);
    return () => window.removeEventListener('resize', checkScroll);
  }, [tabs]);

  const scroll = (direction: 'left' | 'right') => {
    if (scrollRef.current) {
      const amount = 200;
      scrollRef.current.scrollBy({ left: direction === 'left' ? -amount : amount, behavior: 'smooth' });
    }
  };

  if (!tabs.length) return null;

  return (
    <div className="eq-tabs-wrapper">
      {showLeft && (
        <button
          className="eq-tab-scroll-btn"
          onClick={() => scroll('left')}
          aria-label="Scroll left"
        >
          <ChevronLeft size={16} />
        </button>
      )}

      <div 
        className="eq-tabs-scroll" 
        role="tablist" 
        aria-label="Earnings quarters"
        ref={scrollRef}
        onScroll={checkScroll}
      >
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

      {showRight && (
        <button
          className="eq-tab-scroll-btn"
          onClick={() => scroll('right')}
          aria-label="Scroll right"
        >
          <ChevronRight size={16} />
        </button>
      )}
    </div>
  );
};

export default EarningsQuarterTabs;
