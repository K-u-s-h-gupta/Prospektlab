import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Filter,
  RefreshCw,
} from 'lucide-react';
import {
  EarningsCalendarDay,
  EarningsCompaniesResponse,
  EarningsCompanyItem,
  getEarningsCalendar,
  getEarningsCompanies,
} from '../../api/client';
import EarningsResultDetail from './EarningsResultDetail';
import './earnings.css';

// ── date utils ────────────────────────────────────────────────────────────────

const toDateKey = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
};

const parseDateKey = (s: string): Date => {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};

const addDays = (d: Date, n: number): Date => {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
};

const addMonths = (d: Date, n: number): Date => {
  const r = new Date(d);
  r.setMonth(r.getMonth() + n, 1);
  return r;
};

const startOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);
const endOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0);

const buildCalendarCells = (month: Date): Date[] => {
  const ms = startOfMonth(month);
  const me = endOfMonth(month);
  const startWD = (ms.getDay() + 6) % 7; // Mon=0
  const cells: Date[] = [];
  for (let i = 0; i < startWD; i++) cells.push(addDays(ms, i - startWD));
  for (let d = 0; d < me.getDate(); d++) cells.push(addDays(ms, d));
  while (cells.length % 7 !== 0) cells.push(addDays(cells[cells.length - 1], 1));
  return cells;
};

// ── formatters ────────────────────────────────────────────────────────────────

const dayFmt = new Intl.DateTimeFormat('en-IN', { weekday: 'short' });
const stripFmt = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short' });
const monthFmt = new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' });

// ── constants ─────────────────────────────────────────────────────────────────

const STRIP_RADIUS = 7; // days on each side of today
const PAGE_SIZE = 30;
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// ── helpers ───────────────────────────────────────────────────────────────────

const isPastDate = (dateKey: string): boolean => dateKey < toDateKey(new Date());

const timingLabel = (timing: string): string => {
  const map: Record<string, string> = {
    'Pre-market': 'Pre-mkt',
    'During-market': 'During-mkt',
    'Post-market': 'Post-mkt',
    TAS: 'TAS',
  };
  return map[timing] || timing;
};

const daysFromNow = (dateKey: string): number => {
  const target = parseDateKey(dateKey);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86400000);
};

// ── main component ────────────────────────────────────────────────────────────

type Workspace = 'calendar' | 'detail';

const EarningsWorkspace: React.FC = () => {
  const today = new Date();
  const todayKey = toDateKey(today);

  // view state
  const [workspace, setWorkspace] = useState<Workspace>('calendar');
  const [selectedDate, setSelectedDate] = useState(todayKey);
  const [visibleMonth, setVisibleMonth] = useState(startOfMonth(today));
  const [calendarOpen, setCalendarOpen] = useState(false);

  // selected company for detail view
  const [detailCompany, setDetailCompany] = useState<{ symbol: string; name: string; date: string } | null>(null);

  // calendar data
  const calSeq = useRef(0);
  const [calDays, setCalDays] = useState<EarningsCalendarDay[]>([]);
  const [calLoading, setCalLoading] = useState(true);
  const [calError, setCalError] = useState('');

  // companies list data
  const coSeq = useRef(0);
  const [companies, setCompanies] = useState<EarningsCompaniesResponse | null>(null);
  const [coLoading, setCoLoading] = useState(true);
  const [coError, setCoError] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  // build strip: STRIP_RADIUS days before+after selected date anchor
  const stripAnchor =
    Math.abs((parseDateKey(selectedDate).getTime() - today.getTime()) / 86400000) <= STRIP_RADIUS * 2
      ? today
      : parseDateKey(selectedDate);
  const stripDays = Array.from({ length: STRIP_RADIUS * 2 + 1 }, (_, i) =>
    addDays(stripAnchor, i - STRIP_RADIUS),
  );

  const calMap = Object.fromEntries(calDays.map((d) => [d.date, d]));
  const calCells = buildCalendarCells(visibleMonth);
  const activeDay = calMap[selectedDate];

  // ── data loading ────────────────────────────────────────────────────────────

  const loadCalendar = useCallback(async (month: Date) => {
    const seq = ++calSeq.current;
    setCalLoading(true);
    setCalError('');
    const rangeStart = addDays(startOfMonth(month), -7);
    const rangeEnd = addDays(endOfMonth(month), 21);
    try {
      const payload = await getEarningsCalendar(toDateKey(rangeStart), toDateKey(rangeEnd));
      if (calSeq.current !== seq) return;
      setCalDays(payload.dates || []);
    } catch (err: any) {
      if (calSeq.current !== seq) return;
      setCalError(err?.message || 'Failed to load calendar.');
      setCalDays([]);
    } finally {
      if (calSeq.current === seq) setCalLoading(false);
    }
  }, []);

  const loadCompanies = useCallback(async (date: string, page = 1) => {
    const seq = ++coSeq.current;
    setCoLoading(true);
    setCoError('');
    try {
      const payload = await getEarningsCompanies({ date, page, pageSize: PAGE_SIZE });
      if (coSeq.current !== seq) return;
      setCompanies(payload);
    } catch (err: any) {
      if (coSeq.current !== seq) return;
      setCoError(err?.message || 'Failed to load companies.');
      setCompanies(null);
    } finally {
      if (coSeq.current === seq) setCoLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCalendar(visibleMonth);
  }, [visibleMonth, loadCalendar]);

  useEffect(() => {
    loadCompanies(selectedDate, currentPage);
  }, [selectedDate, currentPage, loadCompanies]);

  // ── handlers ────────────────────────────────────────────────────────────────

  const selectDate = (day: Date) => {
    const key = toDateKey(day);
    setVisibleMonth(startOfMonth(day));
    setSelectedDate(key);
    setCurrentPage(1);
    setCalendarOpen(false);
    setWorkspace('calendar');
  };

  const openDetail = (company: EarningsCompanyItem) => {
    setDetailCompany({ symbol: company.symbol, name: company.name, date: selectedDate });
    setWorkspace('detail');
  };

  const backToCalendar = () => {
    setWorkspace('calendar');
    setDetailCompany(null);
  };

  // ── detail view ─────────────────────────────────────────────────────────────

  if (workspace === 'detail' && detailCompany) {
    return (
      <EarningsResultDetail
        symbol={detailCompany.symbol}
        date={detailCompany.date}
        companyName={detailCompany.name}
        onBack={backToCalendar}
      />
    );
  }

  // ── calendar / list view ─────────────────────────────────────────────────────

  const items = companies?.items || [];
  const totalPages = Math.max(1, Math.ceil((companies?.total || 0) / PAGE_SIZE));
  const dateLabel = stripFmt.format(parseDateKey(selectedDate));

  return (
    <div className="ew-root">

      {/* ── Date strip ── */}
      <div className="ew-strip-bar">
        <div className="ew-strip" role="tablist" aria-label="Earnings dates">
          {stripDays.map((day) => {
            const key = toDateKey(day);
            const entry = calMap[key];
            const count = entry?.company_count || 0;
            const selected = key === selectedDate;
            const densityClass = count === 0 ? '' : count <= 3 ? 'density-low' : count <= 8 ? 'density-mid' : 'density-high';
            return (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selected}
                className={`ew-strip-day ${selected ? 'is-selected' : ''} ${densityClass}`}
                onClick={() => selectDate(day)}
              >
                <span className="ew-strip-wd">{dayFmt.format(day)}</span>
                <span className="ew-strip-date">{stripFmt.format(day)}</span>
                {count > 0 && <span className="ew-strip-count">{count}</span>}
              </button>
            );
          })}
        </div>

        {/* Filter / calendar toggle */}
        <button
          type="button"
          className={`ew-calendar-toggle ${calendarOpen ? 'is-open' : ''}`}
          onClick={() => setCalendarOpen((v) => !v)}
          aria-label="Toggle monthly calendar"
          title="Monthly view"
        >
          <Filter size={14} />
        </button>
      </div>

      {/* ── Monthly calendar (collapsible) ── */}
      <div className={`ew-calendar-shell ${calendarOpen ? 'is-open' : ''}`}>
        <div className="ew-calendar-inner">
          <div className="ew-cal-head">
            <button
              type="button"
              className="ew-icon-btn"
              onClick={() => setVisibleMonth(addMonths(visibleMonth, -1))}
              aria-label="Previous month"
            >
              <ChevronLeft size={15} />
            </button>
            <span className="ew-month-label">{monthFmt.format(visibleMonth)}</span>
            <button
              type="button"
              className="ew-icon-btn"
              onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}
              aria-label="Next month"
            >
              <ChevronRight size={15} />
            </button>
          </div>

          {calLoading ? (
            <div className="ew-cal-grid">
              {Array.from({ length: 35 }, (_, i) => (
                <div key={i} className="ew-cal-cell is-loading">
                  <span className="ew-skeleton" />
                </div>
              ))}
            </div>
          ) : calError ? (
            <div className="ew-inline-state">
              <AlertCircle size={14} />
              <span>{calError}</span>
              <button type="button" className="ew-ghost-btn" onClick={() => loadCalendar(visibleMonth)}>
                Retry
              </button>
            </div>
          ) : (
            <>
              <div className="ew-weekdays">
                {WEEKDAYS.map((l) => <span key={l}>{l}</span>)}
              </div>
              <div className="ew-cal-grid">
                {calCells.map((day) => {
                  const key = toDateKey(day);
                  const entry = calMap[key];
                  const count = entry?.company_count || 0;
                  const selected = key === selectedDate;
                  const muted = day.getMonth() !== visibleMonth.getMonth();
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`ew-cal-cell ${selected ? 'is-selected' : ''} ${muted ? 'is-muted' : ''} ${count > 0 ? 'has-data' : ''}`}
                      onClick={() => selectDate(day)}
                      aria-label={`${key}: ${count} companies`}
                    >
                      <span className="ew-cal-num">{day.getDate()}</span>
                      {count > 0 && <span className="ew-cal-badge">{count}</span>}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Company list ── */}
      <div className="ew-list-section">
        <div className="ew-list-header">
          <span className="ew-list-title">
            <CalendarDays size={14} />
            {activeDay?.company_count
              ? `${activeDay.company_count} companies · ${dateLabel}`
              : `${dateLabel}`}
          </span>
          <button
            type="button"
            className="ew-ghost-btn"
            onClick={() => loadCompanies(selectedDate, currentPage)}
            aria-label="Refresh"
          >
            <RefreshCw size={13} />
          </button>
        </div>

        {coLoading ? (
          <div className="ew-list">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="ew-company-card is-loading">
                <span className="ew-skeleton title" />
                <span className="ew-skeleton line" />
              </div>
            ))}
          </div>
        ) : coError ? (
          <div className="ew-inline-state">
            <AlertCircle size={14} />
            <span>{coError}</span>
            <button type="button" className="ew-ghost-btn" onClick={() => loadCompanies(selectedDate, currentPage)}>
              Retry
            </button>
          </div>
        ) : items.length === 0 ? (
           <div className="ew-empty-state">
             <Clock3 size={20} />
             <p>No earnings scheduled for {dateLabel}</p>
             <span>Try selecting another date.</span>
           </div>
         ) : (
           <div className="ew-list">
             {items.map((company) => {
               const past = isPastDate(company.date);
               const days = daysFromNow(company.date);
               const hasEpsData = company.eps_actual !== null && company.eps_actual !== undefined;
               const beatMiss = company.eps_surprise_pct !== null && company.eps_surprise_pct !== undefined
                 ? company.eps_surprise_pct > 0 ? 'beat' : company.eps_surprise_pct < 0 ? 'miss' : 'in-line'
                 : null;
               return (
                 <div key={company.event_uid} className={`ew-company-card ${past ? 'is-past' : 'is-upcoming'}`}>
                   <div className="ew-card-main">
                     <div className="ew-card-info">
                       <div className="ew-card-name">{company.name}</div>
                       <div className="ew-card-meta">
                         <span className="ew-meta-chip sym">{company.symbol}</span>
                         {company.index && company.index !== 'All' && (
                           <span className="ew-meta-chip">{company.index}</span>
                         )}
                         {company.sector && (
                           <span className="ew-meta-chip">{company.sector}</span>
                         )}
                       </div>
                       {/* EPS row for past results */}
                       {past && hasEpsData && (
                         <div className="ew-card-eps">
                           <span className="ew-eps-label">{company.fiscal_quarter || 'Q?'}</span>
                           <span className="ew-eps-actual">EPS ₹{company.eps_actual?.toFixed(2) || '—'}</span>
                           {company.eps_estimated && (
                             <>
                               <span className="ew-sep">vs est.</span>
                               <span className="ew-eps-estimated">₹{company.eps_estimated.toFixed(2)}</span>
                             </>
                           )}
                           {beatMiss && (
                             <span className={`ew-beat-miss ${beatMiss}`}>
                               {beatMiss === 'beat' && `+${company.eps_surprise_pct?.toFixed(2)}%`}
                               {beatMiss === 'miss' && `${company.eps_surprise_pct?.toFixed(2)}%`}
                               {beatMiss === 'in-line' && 'In line'}
                             </span>
                           )}
                           {company.post_earnings_move_1d !== null && company.post_earnings_move_1d !== undefined && (
                             <span className={`ew-move-1d ${company.post_earnings_move_1d > 0 ? 'up' : company.post_earnings_move_1d < 0 ? 'down' : 'flat'}`}>
                               1D: {company.post_earnings_move_1d > 0 ? '+' : ''}{company.post_earnings_move_1d.toFixed(2)}%
                             </span>
                           )}
                         </div>
                       )}
                       {/* Fallback: fiscal quarter + timing for upcoming or when no EPS */}
                       {!(past && hasEpsData) && (
                         <div className="ew-card-sub">
                           <span>{company.fiscal_quarter || 'Quarter TBD'}</span>
                           <span className="ew-sep">·</span>
                           <span>{timingLabel(company.timing)}</span>
                           <span className="ew-sep">·</span>
                           <span>{company.date}</span>
                         </div>
                       )}
                     </div>
                     <div className="ew-card-action">
                       {past ? (
                         <button
                           type="button"
                           className="ew-view-btn"
                           onClick={() => openDetail(company)}
                         >
                           View results →
                         </button>
                       ) : (
                         <span className="ew-scheduled-pill">
                           Scheduled
                           {days > 0 && <span className="ew-days-away"> · {days}d</span>}
                         </span>
                       )}
                     </div>
                   </div>
                 </div>
               );
             })}

             {totalPages > 1 && (
               <div className="ew-pagination">
                 <button
                   type="button"
                   className="ew-ghost-btn"
                   disabled={currentPage <= 1}
                   onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                 >
                   <ChevronLeft size={13} /> Prev
                 </button>
                 <span>{currentPage} / {totalPages}</span>
                 <button
                   type="button"
                   className="ew-ghost-btn"
                   disabled={currentPage >= totalPages}
                   onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                 >
                   Next <ChevronRight size={13} />
                 </button>
               </div>
             )}
           </div>
         )}
      </div>
    </div>
  );
};

export default EarningsWorkspace;
