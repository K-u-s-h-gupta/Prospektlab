# ProspektLab -- Watchlist Tab: Complete Architecture

---

## Table of Contents

1. [System Context](#1-system-context)
2. [Route & Entry Points](#2-route--entry-points)
   - [2.1 Dashboard Route](#21-dashboard-route)
   - [2.2 Onboarding Route](#22-onboarding-route)
3. [Frontend Architecture](#3-frontend-architecture)
   - [3.1 Primary Component](#31-primary-component)
   - [3.2 Legacy Card Component](#32-legacy-card-component)
   - [3.3 Onboarding Component](#33-onboarding-component)
   - [3.4 Internal Types & Constants](#34-internal-types--constants)
   - [3.5 Utility Functions](#35-utility-functions)
4. [UI Structure & Data Displayed](#4-ui-structure--data-displayed)
   - [4.1 Header](#41-header)
   - [4.2 Watchlist Movers Panel](#42-watchlist-movers-panel)
   - [4.3 Notable Price Movement Panel](#43-notable-price-movement-panel)
   - [4.4 Watchlist News Panel](#44-watchlist-news-panel)
   - [4.5 Empty State](#45-empty-state)
   - [4.6 Watchlist Management Modal](#46-watchlist-management-modal)
5. [State Management](#5-state-management)
6. [Data Flow & API Calls](#6-data-flow--api-calls)
7. [Chart Data Transformation](#7-chart-data-transformation)
   - [7.1 Historical Data Normalization](#71-historical-data-normalization)
   - [7.2 1D Intraday Data](#72-1d-intraday-data)
   - [7.3 Chart.js Options](#73-chartjs-options)
8. [Real-Time Price Feed](#8-real-time-price-feed)
9. [Procedural Cover Art](#9-procedural-cover-art)
10. [Backend Architecture](#10-backend-architecture)
    - [10.1 Gateway Route](#101-gateway-route)
    - [10.2 Helper Functions](#102-helper-functions)
11. [TypeScript Types](#11-typescript-types)
12. [Persistence](#12-persistence)
13. [Error Handling & Loading States](#13-error-handling--loading-states)
14. [File Index](#14-file-index)

---

## 1. System Context

ProspektLab is a full-stack Indian stock market research and portfolio analytics platform. The Watchlist tab is one of seven feature tabs accessible from `/dashboard/:featureTab`.

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 18.3.1 (Vite + TypeScript) |
| **Routing** | React Router DOM v6 (clean URLs) |
| **State** | React Context API (`AuthContext`) + component-local `useState` |
| **State Parent** | `Dashboard.tsx` holds `watchlistSymbols[]` and `watchlistStocks[]` |
| **Charting** | Chart.js 4 + react-chartjs-2 (registered: CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend) |
| **Icons** | lucide-react (Search, Settings2, TrendingUp, TrendingDown, X, ExternalLink) |
| **Backend** | FastAPI (Python) at `backend/finagent/` |
| **Real-time** | Upstox WebSocket relay (`/ws/market`) with HTTP polling fallback |
| **Data lookups** | `INDIAN_STOCKS` (14,142 lines), `POPULAR_MUTUAL_FUNDS` |
| **Styling** | Inline styles (no separate CSS file) |

---

## 2. Route & Entry Points

### 2.1 Dashboard Route

**Route:** `/dashboard/watchlist`

**Page component:** `frontend/src/pages/DashboardWatchlistPage.tsx` (8 lines)

```tsx
import React from 'react';
import Dashboard from './Dashboard';

export const DashboardWatchlistPage: React.FC = () => {
  return <Dashboard initialFeatureTab="watchlist" />;
};

export default DashboardWatchlistPage;
```

This renders the main `Dashboard` component which holds the watchlist state (`watchlistSymbols`, `watchlistStocks`) and renders `<WatchlistWorkspace>` with the appropriate props.

### 2.2 Onboarding Route

**Route:** `/onboarding/watchlist`

**Page component:** `frontend/src/pages/WatchlistStep.tsx` (273 lines)

A standalone page in the onboarding flow: `Get Started → Manual/Upload → Watchlist → Dashboard`.

This allows new users to build their initial watchlist before entering the dashboard. Unlike the dashboard watchlist, this component has its own search (client-side against `INDIAN_STOCKS` + `POPULAR_MUTUAL_FUNDS`) and its own symbol selection logic.

**Legacy default watchlist detection:**
```typescript
const LEGACY_DEFAULT_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK',
  'TATAMOTORS', 'ASIANPAINT', 'ZOMATO', 'ITC'];
```
If the user's watchlist exactly matches this default set, it's cleared so they can choose their own.

**On completion:** Saves to localStorage, calls `setOnboarded(true)`, fires telemetry event, navigates to `/dashboard`.

---

## 3. Frontend Architecture

### 3.1 Primary Component

**File:** `frontend/src/components/dashboard/WatchlistWorkspace.tsx` (1235+ lines)

**Props:**
```typescript
interface WatchlistWorkspaceProps {
  symbols: string[];                       // Current watchlist symbol strings
  stocks: WatchlistStock[];                // Stock price/change data
  onChangeSymbols: (next: string[]) => void;   // Update watchlist in parent state
  onSelectStock: (symbol: string) => void;     // Navigate to stock detail/screener
  onAskStock?: (symbol: string) => void;       // Open AI chat for this stock
}
```

The parent (`Dashboard.tsx`) manages `symbols` and `stocks` in its local state and passes them down. `WatchlistWorkspace` never directly writes to localStorage -- it calls `onChangeSymbols` which the parent handles.

### 3.2 Legacy Card Component

**File:** `frontend/src/components/dashboard/WatchlistCard.tsx` (219 lines)

An older "Smart Watchlist" view used in an earlier version of the dashboard. Exports the `WatchlistStock` interface.

```typescript
export interface WatchlistStock {
  symbol: string;
  name: string;
  price: string;
  change: string;
  changePct: number;
}
```

Features:
- Header with "My Smart Watchlist" title + stock count badge
- Inline "Add ticker" form (text input + submit button)
- Stock rows: Symbol, name, price (Rs), change (arrow + %), Ask button, Remove button
- Mouse hover effects on rows

This component is imported by `WatchlistWorkspace` only for its type definition.

### 3.3 Onboarding Component

**File:** `frontend/src/pages/WatchlistStep.tsx` (273 lines)

A full-page onboarding step with:
- ProspektLab branding (logo + name)
- Beta badge
- Custom search input with live suggestions from `INDIAN_STOCKS` + `POPULAR_MUTUAL_FUNDS`
- Suggestions show: symbol, name, type badge (Stock/Mutual Fund), add/remove toggle
- Selected chips: removable pill badges
- "Watchlist targets active: N Assets" counter
- Back (to upload) / "Open Dashboard" navigation

**Storage key:**
```typescript
const watchlistStorageKey = user?.email
  ? `prospektlab_watchlist:${user.email.toLowerCase()}`
  : 'prospektlab_watchlist';
```

### 3.4 Internal Types & Constants

```typescript
// Chart range options
type MoversRange = '1D' | '1M' | '6M' | 'YTD' | '1Y' | '5Y' | 'MAX';
const RANGE_OPTIONS: MoversRange[] = ['1D', '1M', '6M', 'YTD', '1Y', '5Y', 'MAX'];

// Chart colors (up to 8 stocks simultaneously)
const LINE_COLORS = ['#38bdf8', '#f97316', '#facc15', '#c084fc',
                     '#22c55e', '#ef4444', '#2dd4bf', '#fb7185'];

// Default symbols shown when watchlist is empty
const WATCHLIST_ONBOARDING_SYMBOLS = ['RELIANCE', 'TCS', 'INFY',
                                       'HDFCBANK', 'ICICIBANK', 'SBIN'];

// Internal interfaces
interface WatchlistNewsItem {
  id: string;        symbol: string;       headline: string;
  source: string;    time: string;         url: string;
  image: string;     fallbackImage: string;
}

interface SymbolHistory {
  symbol: string;
  dates: string[];
  prices: number[];
}

interface MovementEvent {
  key: string;        symbol?: string;     dateIso?: string;
  dateLabel: string;  priceLabel: string;  pctLabel: string;
  direction: 'up' | 'down';                summary: string;
  sourceCount: number;
}

interface LiveQuoteSnapshot {
  symbol: string;
  name: string;
  price: number;
  changePct: number;
}

interface IntradayPoint {
  ts: number;    // Unix timestamp in ms
  price: number;
}
```

### 3.5 Utility Functions

| Function | Purpose |
|----------|---------|
| `normalizeSymbol(value)` | Strips exchange suffix (`.NS`, `.BO`), uppercases, trims. e.g., `"RELIANCE.NS" → "RELIANCE"` |
| `normalizeNewsUrl(raw)` | Sanitizes URLs: handles `//` prefixes, strips hashes |
| `historyPeriodForRange(range)` | Maps `1D` → `1M`, `5Y` → `MAX`, else identity (fixes backend period mismatch) |
| `parseIsoDate(value)` | Parses ISO date string to Unix timestamp; returns 0 on failure |
| `filterSeriesForRange(dates, prices, range)` | Trims data to match selected range (1D=last 24 points, 5Y=last 5 years of data) |
| `formatDateShort(iso)` | `DD Mon` format (Indian locale) |
| `formatDateLong(iso)` | `D Mon` format (Indian locale) |
| `parseDisplayPrice(value)` | Extracts numeric price from string/number, stripping non-numeric chars |
| `formatSignedNumber(value, digits)` | `+1.23` or `-0.45` format |
| `formatIntradayLabel(ts)` | Timestamp → time string (`HH:MM`, Indian locale) |
| `formatMovementLabel(ts)` | Timestamp → `DD Mon, HH:MM` format (Indian locale) |
| `toINR(value)` | Formats number as INR with Indian locale: `Rs 3,121.45` |
| `fallbackCover(seed, title, symbol, source)` | Generates procedurally-generated SVG cover image (see §9) |
| `findDisplayName(symbol, fallbackName)` | Looks up display name in `INDIAN_STOCKS` then `POPULAR_MUTUAL_FUNDS` |

---

## 4. UI Structure & Data Displayed

### 4.1 Header

Top-right: "Manage watchlist" button with Settings2 icon. Always visible.

Auto-opens the manage modal when `symbols` becomes empty (user removed all stocks).

### 4.2 Watchlist Movers Panel

```
┌─────────────────────────────────────────────────────────┐
│ Watchlist movers              [1D] [1M] [6M] [YTD] ...  │
│─────────────────────────────────────────────────────────│
│                                                         │
│              (280px line chart)                          │
│                                                         │
│─────────────────────────────────────────────────────────│
│ (R) Reliance Industries    Rs 3,121.45   +42.45  +1.38% │
│     RELIANCE                                    [Ask][X]│
│                                                         │
│ (T) TCS                    Rs 4,201.00   -15.30  -0.36% │
│     TCS                                         [Ask][X]│
│                                                         │
│ ...more stocks...                                        │
└─────────────────────────────────────────────────────────┘
```

#### Range Selector

7 pill buttons: `1D` `1M` `6M` `YTD` `1Y` `5Y` `MAX`

Active button gets cyan highlight (`rgba(56,189,248,0.14)` background, `rgba(56,189,248,0.45)` border). Inactive buttons are muted.

#### Chart

- **Height:** 280px
- **Library:** Chart.js `Line` component
- **Rendering:**
  - **1D range:** Uses built-up `intradaySeries` data (1-min bucketed prices, up to 240 points). Falls back to history chart if < 2 renderable points.
  - **Other ranges:** Uses `histories` data from `/watchlist/snapshot`, filtered to selected range.
- **Y-axis:** Shows % change from period start (allows multi-stock comparison regardless of absolute price levels)
- **Labels:** Date-formatted for history, time-formatted for intraday
- **Lines:** One per stock, unique color, spanGaps enabled, tension 0.25
- **Data gaps:** `null` values allowed (spanned across via `spanGaps`)
- **Loading:** "Loading movers chart..." for history ranges; "Waiting for live price updates..." for 1D

#### Stock Rows Grid

Below the chart, each stock displays as a row:

| Column | Content | Style |
|--------|---------|-------|
| **Identity** | Initial icon (colored square) + Name + Symbol | Clickable → `onSelectStock(symbol)` |
| **Price** | `Rs {price}` | Monospace, right-aligned |
| **Change Value** | `+42.45` or `-15.30` | Color-coded (green/red) |
| **Change %** | Pill badge with arrow icon + `1.38%` | Green/red border + background |
| **Actions** | Ask button + Remove (X) button | Ask = cyan, Remove = red |

### 4.3 Notable Price Movement Panel

```
┌─────────────────────────────────────────────────────────┐
│ Notable price movement            [RELIANCE  ▾]         │
│─────────────────────────────────────────────────────────│
│                                                         │
│  25 Jun                │ Rs 3,121.45    +2.38%          │
│                        │ News flow: RIL signs $10B      │
│                        │ green energy deal with Qatar.   │
│                        │ 2 sources                      │
│                                                         │
│  24 Jun                │ Rs 3,049.10    -1.52%          │
│                        │ News flow: SEBI issues notice   │
│                        │ on subsidiary listing delay.    │
│                        │ 1 source                       │
│                                                         │
│  ...more movements...                                    │
└─────────────────────────────────────────────────────────┘
```

#### Symbol Selector

Dropdown (`<select>`) to choose which watchlist symbol to analyze. Auto-selects the top mover (by absolute `changePct`) on mount and when the current selection becomes invalid.

#### Movement Timeline

Scrollable container (max 420px height).

**Data source priority:**
1. `dailyMovementSummaries` from backend (daily notable movements with news correlation) -- up to 35 items
2. Intraday movement events (if no daily summaries) -- top 3 biggest moves from `intradaySeries`
3. History-based movement events (if no intraday) -- top 3 biggest daily moves from `histories`
4. Fallback: current stock change as a single movement entry

**Each movement event displays:**
- **Date:** `DD Mon` format (e.g., "25 Jun")
- **Price:** Large monospace display (e.g., "Rs 3,121.45")
- **% Change:** Large color-coded display (e.g., "+2.38%" in green or "-1.52%" in red)
- **Summary:** Free-text explanation, usually news-correlated (e.g., "News flow: RIL signs $10B green energy deal with Qatar.")
- **Source count:** e.g., "2 sources" or "No linked sources yet"

**News correlation logic:** When backend provides `daily_summaries`, each has a `summary` field + `sources` array. When falling back to local computation, the frontend matches movements to `watchlistNews` items by symbol and uses adjacent headlines as the "News flow:" lead-in.

### 4.4 Watchlist News Panel

```
┌─────────────────────────────────────────────────────────┐
│ Watchlist news                     SYMBOL-FOCUSED        │
│─────────────────────────────────────────────────────────│
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ [cover]   │  │ [cover]   │  │ [cover]   │             │
│  │           │  │           │  │           │             │
│  │ RELIANCE  │  │ TCS Quick  │  │ INFY      │             │
│  │ ET Bureau │  │ Mint       │  │ CNBC      │             │
│  │ RIL's green│  │ TCS Q1 rev │  │ Infosys    │             │
│  │ energy push│  │ beats est. │  │ wins $2B  │             │
│  │ 25 Jun    │  │ 24 Jun     │  │ 24 Jun     │             │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

**Layout:** Responsive CSS grid with `auto-fill, minmax(230px, 1fr)`.

**Each news card:**
- **Cover image:** 118px height, procedurally generated SVG via `buildProspektCover()` (see §9). Error fallback: `onError` handler replaces with `fallbackImage`.
- **Symbol badge:** Cyan text, bold, top-left
- **Source:** Gray text, top-right
- **Headline:** 3-line clamp via `-webkit-line-clamp: 3`
- **Footer:** Time + external link icon
- **Click:** Opens `item.url` in new tab with `noopener,noreferrer`

**Up to 18 items** are displayed. News items with empty headlines are filtered out.

### 4.5 Empty State

When `symbols.length === 0`:

```
┌─────────────────────────────────────────────────────────┐
│ Build your watchlist        ADD SYMBOLS TO START LIVE    │
│                              TRACKING                    │
│─────────────────────────────────────────────────────────│
│                                                         │
│ Your watchlist is currently empty. Add symbols to        │
│ unlock live movers, notable price movement, and          │
│ watchlist-specific news.                                 │
│                                                         │
│ [+ RELIANCE] [+ TCS] [+ INFY] [+ HDFCBANK] [+ ICICI]    │
│ [+ SBIN]                                                │
│                                                         │
│ Open full watchlist manager                              │
└─────────────────────────────────────────────────────────┘
```

Quick-add buttons for 6 recommended symbols (`WATCHLIST_ONBOARDING_SYMBOLS`). Clicking adds the symbol directly. "Open full watchlist manager" opens the manage modal with 3 pre-selected symbols.

### 4.6 Watchlist Management Modal

Rendered via `ReactDOM.createPortal` to `document.body`. This avoids z-index and overflow issues with the main dashboard layout.

```
┌─────────────────────────────────────────────────────────┐ (backdrop: dark + blur)
│  ┌───────────────────────────────────────────────────┐  │
│  │ Manage watchlist                               [X]│  │
│  │───────────────────────────────────────────────────│  │
│  │                                                   │  │
│  │ Search symbols                                    │  │
│  │ (🔍) [Type ticker or company name         ]       │  │
│  │                                                   │  │
│  │ Selected (3)                                      │  │
│  │ [RELIANCE x] [TCS x] [INFY x]                     │  │
│  │                                                   │  │
│  │ Suggestions                                       │  │
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐           │  │
│  │ │ HDFCBANK │ │ ICICIBANK │ │ SBIN     │           │  │
│  │ │ HDFC Bank│ │ ICICI Bank│ │ State ...│           │  │
│  │ └──────────┘ └──────────┘ └──────────┘           │  │
│  │ ...more suggestions...                            │  │
│  │                                                   │  │
│  │                              [Cancel]  [Save]     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Modal dimensions:** `min(920px, 100%)` wide, `max 84vh` height, scrollable.

**Close behavior:**
- Close button (X) in header
- Click backdrop
- Cancel button
- All discard changes (revert `draftSymbols` to original `symbols`)

**Search:**
```typescript
const symbolOptions = useMemo(() => {
  const items = [...INDIAN_STOCKS.slice(0, 2400), ...POPULAR_MUTUAL_FUNDS];
  const query = manageQuery.trim().toLowerCase();
  if (!query) return items.slice(0, 40);
  return items
    .filter((row) => row.symbol.toLowerCase().includes(query) || row.name.toLowerCase().includes(query))
    .slice(0, 80);
}, [manageQuery]);
```

- Default: first 40 stocks (no search query)
- With query: up to 80 filtered results matching symbol or name
- Source: First 2400 entries of `INDIAN_STOCKS` + all `POPULAR_MUTUAL_FUNDS`

**Selection:** Click a suggestion to toggle in/out of `draftSymbols`. Click a selected chip to remove.

**Save:** Deduplicates, calls `onChangeSymbols(next)`, closes modal.

---

## 5. State Management

All state lives in `WatchlistWorkspace` via `useState`. The parent `Dashboard.tsx` holds `watchlistSymbols` and `watchlistStocks` arrays and passes them as props.

| State Variable | Type | Initial | Purpose |
|---------------|------|---------|---------|
| `range` | `MoversRange` | `'1D'` | Selected chart time range |
| `isManageOpen` | `boolean` | `false` | Manage modal visibility |
| `manageQuery` | `string` | `''` | Search text in modal |
| `draftSymbols` | `string[]` | `symbols` | Editable symbol list in modal |
| `histories` | `Record<string, SymbolHistory>` | `{}` | Price history per symbol (from snapshot) |
| `historyLoading` | `boolean` | `false` | History fetch in progress |
| `historyError` | `string \| null` | `null` | History error message |
| `watchlistNews` | `WatchlistNewsItem[]` | `[]` | Cached news items with cover images |
| `newsLoading` | `boolean` | `false` | News fetch in progress |
| `newsError` | `string \| null` | `null` | News error message |
| `selectedMovementSymbol` | `string` | First symbol or `''` | Symbol selected for movement panel |
| `liveQuotes` | `Record<string, LiveQuoteSnapshot>` | `{}` | Merged live prices (WS + HTTP) |
| `intradaySeries` | `Record<string, IntradayPoint[]>` | `{}` | Built-up intraday price history |
| `dailyMovementSummaries` | `MovementEvent[]` | `[]` | Daily notable movements from backend |
| `refreshNonce` | `number` | `0` | Auto-refresh counter (drives re-fetch) |

**Computed values** (via `useMemo`):
- `symbolOptions` -- filtered search suggestions for modal
- `normalizedStocks` -- `WatchlistStock[]` with liveQuotes overlaid on stocks prop
- `normalizedSeries` -- Chart.js data object from histories + intraday series
- `topMoverSymbol` -- symbol with highest absolute `changePct`
- `movementEvents` -- filtered notable movements for selected symbol

**Auto-refresh:**
```typescript
useEffect(() => {
  if (symbols.length === 0) return;
  const intervalMs = range === '1D' ? 45000 : 90000;
  const interval = window.setInterval(() => {
    setRefreshNonce((prev) => prev + 1);
  }, intervalMs);
  return () => window.clearInterval(interval);
}, [symbols, range]);
```

- 1D range: refreshes every 45 seconds
- Other ranges: refreshes every 90 seconds
- Each increment triggers a new `getWatchlistSnapshot()` call

**Auto-open manage modal:**
```typescript
useEffect(() => {
  if (symbols.length > 0) {
    autoPromptRef.current = false;
    return;
  }
  if (autoPromptRef.current) return;
  autoPromptRef.current = true;
  setDraftSymbols([]);
  setManageQuery('');
  setIsManageOpen(true);
}, [symbols]);
```

When all stocks are removed, the modal auto-opens exactly once (guarded by `autoPromptRef`).

**Auto-select movement symbol:**
```typescript
useEffect(() => {
  if (!selectedMovementSymbol && topMoverSymbol) {
    setSelectedMovementSymbol(topMoverSymbol);
  }
}, [selectedMovementSymbol, topMoverSymbol]);
```

On mount or when symbols change, auto-selects the stock with the largest absolute price change.

---

## 6. Data Flow & API Calls

### Primary Data Fetch

```
Component mount / symbols change / range change / refreshNonce increments
   |
   v
getWatchlistSnapshot(symbols.slice(0, 12), period)
   |
   v
GET /watchlist/snapshot?symbols=RELIANCE,TCS,INFY&period=1M
   |
   v   (15s timeout)
Returns WatchlistSnapshotResponse
   |
   +--> quotes[]        → setLiveQuotes (merge with existing)
   |     On failure: fallback to getMarketQuotes(symbols.slice(0, 20))
   |
   +--> histories{}     → setHistories (filtered by range)
   |
   +--> news[]          → setWatchlistNews
   |     └── Each item gets a procedurally-generated cover image
   |         via fallbackCover().
   |
   +--> daily_summaries[]  → setDailyMovementSummaries
         └── Sorted by date descending (most recent first)
```

### Real-Time Price Overlay

```typescript
const { prices: liveFeedPrices } = useMarketFeed(symbols, { includeIndices: false });

useEffect(() => {
  if (!liveFeedPrices || Object.keys(liveFeedPrices).length === 0) return;
  setLiveQuotes((prev) => {
    const next = { ...prev };
    for (const sym of symbols) {
      const tick = liveFeedPrices[sym.toUpperCase()];
      if (!tick || !Number.isFinite(Number(tick.price)) || Number(tick.price) <= 0) continue;
      const key = normalizeSymbol(sym);
      next[key] = {
        symbol: key,
        name: prev[key]?.name || tick.company_name || findDisplayName(key, key),
        price: Number(tick.price),
        changePct: Number.isFinite(Number(tick.change_pct))
          ? Number(tick.change_pct)
          : (prev[key]?.changePct ?? 0),
      };
    }
    return next;
  });
}, [liveFeedPrices, symbols]);
```

The WebSocket feed overlays the snapshot poll data. Price is updated immediately; name is carried forward from either the previous snapshot or the tick's `company_name` field.

### Intraday Data Build-Up

```typescript
useEffect(() => {
  if (symbols.length === 0) {
    setIntradaySeries({});
    return;
  }
  const active = new Set(symbols.map((row) => normalizeSymbol(row)));
  const now = Date.now();
  const cutoff = now - 24 * 60 * 60 * 1000;
  setIntradaySeries((prev) => {
    let changed = false;
    const next: Record<string, IntradayPoint[]> = {};
    active.forEach((symbol) => {
      const base = (prev[symbol] || []).filter((row) => row.ts >= cutoff);
      const stock = normalizedStocks.find((row) => normalizeSymbol(row.symbol) === symbol);
      const price = parseDisplayPrice(stock?.price ?? 0);
      if (!Number.isFinite(price) || price <= 0) {
        if (base.length > 0) next[symbol] = base;
        return;
      }
      const last = base[base.length - 1];
      const shouldAppend = !last || Math.abs(last.price - price) > 0.0001 || now - last.ts >= 60_000;
      const updated = shouldAppend ? [...base, { ts: now, price }] : base;
      if (shouldAppend || updated.length !== (prev[symbol] || []).length) changed = true;
      next[symbol] = updated.slice(-360);
    });
    if (!changed && Object.keys(prev).length === Object.keys(next).length) return prev;
    return next;
  });
}, [symbols, normalizedStocks]);
```

Key behaviors:
- **24-hour cutoff:** Points older than 24 hours are purged
- **Max 360 points:** Oldest points dropped when limit exceeded
- **Deduplication:** Points within same price (0.0001 tolerance) and < 60 seconds apart are skipped
- **Immutable update:** Returns `prev` if nothing changed, avoiding unnecessary re-renders
- **Empty state:** Cleared when `symbols` becomes empty

### API Error Recovery

```typescript
try {
  const snapshot = await getWatchlistSnapshot(symbols.slice(0, 12), period);
  // ... process snapshot ...
} catch (err: any) {
  const message = err?.message || 'Unable to load watchlist intelligence snapshot.';
  // Fallback: try getMarketQuotes for live prices
  try {
    const fallbackQuotes = await getMarketQuotes(symbols.slice(0, 20));
    // ... process fallback quotes ...
  } catch { /* ignore */ }
  setHistoryError('Detailed watchlist history is temporarily unavailable. Showing live quotes.');
  setNewsError(message);
}
```

When the snapshot endpoint fails, the component:
1. Attempts a fallback `getMarketQuotes()` call for live prices
2. Shows a graceful error message in the history section
3. Shows the backend error in the news section
4. Live prices continue to display via the fallback

---

## 7. Chart Data Transformation

### 7.1 Historical Data Normalization

All historical data from `/watchlist/snapshot` is normalized to **% change from first data point** for fair multi-stock comparison:

```typescript
const firstPrice = row.prices.find((value) => Number.isFinite(value) && value > 0) || 0;
if (firstPrice <= 0) return null;  // Skip this stock

let lastPrice: number | null = null;
const data = labels.map((date) => {
  const price = byDate.get(date);
  if (typeof price === 'number' && Number.isFinite(price) && price > 0) {
    lastPrice = price;
  }
  if (lastPrice === null) return null;
  return Number((((lastPrice - firstPrice) / firstPrice) * 100).toFixed(2));
});
```

Features:
- All dates across all stocks are merged into a single sorted label array
- Missing dates for a stock get `null` (spanned via `spanGaps: true`)
- Stocks with < 2 valid data points are excluded from the chart
- Single-point datasets get `pointRadius: 2.5` for visibility

### 7.2 1D Intraday Data

For the 1D range, intraday data is bucketed and normalized:

```typescript
if (range === '1D') {
  const labelKeys = new Set<number>();
  const seriesRows = symbols
    .map((symbol) => {
      const normalized = normalizeSymbol(symbol);
      const points = (intradaySeries[normalized] || []).slice(-240);
      if (points.length < 2) return null;
      const bucketed = new Map<number, number>();
      points.forEach((row) => {
        const bucket = Math.floor(row.ts / 60000) * 60000;
        bucketed.set(bucket, row.price);
        labelKeys.add(bucket);
      });
      return { symbol: normalized, bucketed };
    })
    .filter(Boolean);
  // ... same % change normalization from first bucket price ...
}
```

**Bucketing:** Prices grouped into 1-minute buckets (`Math.floor(ts / 60000) * 60000`). Last price in each bucket wins.

**Fallback to history:** If intraday data has < 2 renderable points (e.g., tab just opened, no data accumulated yet), falls back to the historical 1M chart.

### 7.3 Chart.js Options

```typescript
const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      display: true,
      labels: { color: '#9ca3af', boxWidth: 12, usePointStyle: true, pointStyle: 'line' }
    },
    tooltip: {
      backgroundColor: 'rgba(15,23,42,0.98)',
      borderColor: 'rgba(148,163,184,0.35)',
      borderWidth: 1,
      titleColor: '#e2e8f0',
      bodyColor: '#cbd5e1',
      callbacks: {
        label: (context) => `${context.dataset.label}: ${Number(context.parsed.y || 0).toFixed(2)}%`
      }
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(148,163,184,0.12)' },
      ticks: { color: '#94a3b8', maxTicksLimit: 6 }
    },
    y: {
      grid: { color: 'rgba(148,163,184,0.12)' },
      ticks: { color: '#94a3b8', callback: (value) => `${Number(value).toFixed(0)}%` }
    }
  }
};
```

Dark theme styling consistent with the ProspektLab dashboard.

---

## 8. Real-Time Price Feed

The Watchlist tab uses the shared `useMarketFeed` hook for live prices:

```typescript
const { prices: liveFeedPrices } = useMarketFeed(symbols, { includeIndices: false });
```

**Architecture** (`frontend/src/hooks/useMarketFeed.ts`, 455 lines):

```
Browser Tab
   |
   v
useMarketFeed(symbols, { includeIndices: false })
   |
   +--> WebSocket connection to /ws/market (Upstox relay)
   |     - On connect: receives full snapshot of all known prices
   |     - On tick: receives individual price updates
   |     - On disconnect: schedules reconnection with exponential backoff
   |       (1s, 2s, 4s, 8s, 15s)
   |     - Sends subscribe message with symbol list on connect
   |
   +--> HTTP polling fallback (every 5s via getMarketQuotes)
         - Activated when: WS connection fails, tab hidden,
           or WS disconnect > 5s
         - Deactivated when WS is live
```

**Return value:**
```typescript
interface MarketFeedState {
  prices: Record<string, PriceSnapshot>;    // SYMBOL → live price
  indexData: Record<string, IndexSnapshot[]>; // (not used by watchlist)
  connected: boolean;
  feedSource: 'websocket' | 'polling';
  lastUpdateAge: number;
}

interface PriceSnapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  company_name?: string;
  sector?: string;
  source?: string;
  timestamp?: number;
}
```

**Tab visibility handling:** When `document.visibilityState` becomes `visible`, the hook reconnects the WebSocket and refreshes data.

**Symbol resubscription:** When `symbols` changes, the hook sends a new subscribe message over the active WebSocket, or triggers an HTTP fetch in fallback mode.

**Watchlist integration:** The `liveFeedPrices` are merged into `liveQuotes` in a `useEffect`, preserving existing names while updating prices and change percentages. The `liveQuotes` then feed into `normalizedStocks` which drives the display rows and intraday data build-up.

---

## 9. Procedural Cover Art

News cards use procedurally generated SVG images rather than external image URLs. This avoids broken images, external dependencies, and network requests.

**File:** `frontend/src/utils/coverArt.ts` (441 lines)

```typescript
const fallbackCover = (seed: string, title = '', symbol = '', source = '') =>
  buildProspektCover({
    seed,
    title: title || seed,
    source,
    symbol,
    kind: 'watchlist',
    label: 'Watchlist Brief',
  });
```

**`buildProspektCover()` generates:**
- **SVG data URI** (`data:image/svg+xml;charset=utf-8,...`)
- **1200×675** viewBox (social-media-friendly aspect ratio)
- **Deterministic output:** Same seed always produces the same image (hash-based)
- **Layered design:**
  - Dark gradient background
  - Grid pattern overlay
  - Decorative circle orbs
  - Sparkline waveform
  - PL brand mark (top-left)
  - "INTEL" label
  - Eyebrow text (e.g., "WATCHLIST BRIEF")
  - Symbol/source label
  - Title panel (bottom, up to 2 lines)
  - "LIVE SIGNAL" badge
- **Color palette:** Rotated based on seed hash from 5 predefined palettes
- **Variants:** 3 visual variants (candlestick chart, bar chart, sparkline-only)

**Error handling in news cards:**
```typescript
onError={(event) => {
  const target = event.currentTarget;
  target.onerror = null;
  target.src = item.fallbackImage;
}}
```

Each news item has both `image` and `fallbackImage` (generated with slightly different seeds). If the primary image fails to load, the fallback replaces it.

---

## 10. Backend Architecture

### 10.1 Gateway Route

Unlike the Screener tab (which has a dedicated `backend/finagent/screener/` package with service, scoring, and schema files), the Watchlist backend logic is implemented **entirely inline** within `backend/finagent/gateway/run.py` (lines ~2332-2720).

**Endpoint:** `GET /watchlist/snapshot`

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `symbols` | string (comma-separated) | Yes | Watchlist symbol list (max 12 processed) |
| `period` | string | No (default: `1M`) | History period (`1M`, `3M`, `6M`, `YTD`, `1Y`, `MAX`) |

**Response shape** (`WatchlistSnapshotResponse`):
```typescript
{
  as_of: string;
  period: MarketHistoryPeriod;
  refresh_after_ms: number;
  quotes: WatchlistSnapshotQuote[];
  movers: WatchlistSnapshotQuote[];
  histories: Record<string, WatchlistSnapshotHistory>;
  daily_summaries: WatchlistSnapshotSummary[];
  notable_movements: WatchlistSnapshotSummary[];
  news: WatchlistSnapshotNewsItem[];
  source_health: {
    quotes: 'ok' | 'stale' | 'unavailable';
    history: 'ok' | 'stale' | 'unavailable';
    news: 'ok' | 'stale' | 'unavailable';
    official: 'ok' | 'stale' | 'unavailable';
  };
}
```

### 10.2 Helper Functions

All defined in `backend/finagent/gateway/run.py`:

| Function | Purpose |
|----------|---------|
| `_watchlist_clean_symbol(value: str) -> str` | Strips `.NS`, `.BO`, `.NSE`, `.BSE` suffixes; uppercases; trims |
| `_watchlist_find_quote(quotes_payload, symbol) -> dict \| None` | Finds a quote in the response payload by symbol, with fallback resolution |
| `_watchlist_format_price(value: float) -> str` | Formats price as INR with Indian number locale (`Rs 3,121.45`) |
| `_watchlist_source_tier(url: str, source: str = "") -> int` | Ranks news source credibility on a numeric scale (lower = more authoritative) |
| `_watchlist_normalize_url(raw: str) -> str` | Sanitizes news URLs: adds `https:` to `//`-prefixed URLs, strips tracking params |
| `_watchlist_parse_published(value: str) -> datetime \| None` | Parses various date formats to a datetime object |
| `_watchlist_age_label(published_dt: datetime \| None) -> str` | Human-readable age: "2h ago", "1d ago", "Just now" |
| `_watchlist_day_label(day_iso: str) -> str` | Formats ISO date to display label (e.g., "25 Jun 2025") |
| `_watchlist_related_sources(symbol, date_range, news_items) -> list` | Finds news sources correlated with specific price movement dates -- used for Notable Movement summaries |
| `_watchlist_history_for_symbol(symbol: str, period: str) -> dict \| None` | Fetches and normalizes OHLCV price history for a single symbol from market data providers |

---

## 11. TypeScript Types

From `frontend/src/api/client.ts`:

```typescript
interface WatchlistStock {
  symbol: string;
  name: string;
  price: string;
  change: string;
  changePct: number;
}

interface WatchlistSnapshotQuote {
  symbol: string;
  name: string;
  price: number;
  price_label: string;        // Formatted: "Rs 3,121.45"
  change: number;
  change_label: string;       // Formatted: "+42.45"
  change_pct: number;
  change_pct_label: string;   // Formatted: "+1.38%"
  direction: 'up' | 'down';
  source: string;             // Price data source
  source_url?: string;
  isin?: string;
}

interface WatchlistSnapshotHistory {
  symbol: string;
  name: string;
  dates: string[];            // ISO date strings
  prices: number[];           // Corresponding close prices
  source?: string;
  as_of?: string;
}

interface WatchlistSnapshotSummarySource {
  headline: string;
  url: string;
  source: string;
  published: string;
  category: string;
  source_tier: number;
}

interface WatchlistSnapshotSummary {
  key: string;
  symbol: string;
  name: string;
  date: string;               // ISO date
  date_label: string;         // Formatted date
  price: number;
  price_label: string;        // Formatted price
  pct: number;
  pct_label: string;          // Formatted percentage
  direction: 'up' | 'down';
  summary: string;            // News-correlated explanation
  source_count: number;
  sources: WatchlistSnapshotSummarySource[];
}

interface WatchlistSnapshotNewsItem {
  id: string;
  symbol: string;
  headline: string;
  source: string;
  published: string;
  time: string;
  url: string;
  image?: string;
  source_tier: number;        // Source credibility rank
  category: string;           // News category
}

interface WatchlistSnapshotResponse {
  as_of: string;
  period: MarketHistoryPeriod;
  refresh_after_ms: number;
  quotes: WatchlistSnapshotQuote[];
  movers: WatchlistSnapshotQuote[];
  histories: Record<string, WatchlistSnapshotHistory>;
  daily_summaries: WatchlistSnapshotSummary[];
  notable_movements: WatchlistSnapshotSummary[];
  news: WatchlistSnapshotNewsItem[];
  source_health: {
    quotes: 'ok' | 'stale' | 'unavailable';
    history: 'ok' | 'stale' | 'unavailable';
    news: 'ok' | 'stale' | 'unavailable';
    official: 'ok' | 'stale' | 'unavailable';
  };
}
```

**API functions:**
```typescript
getWatchlistSnapshot(symbols: string[], period = '1M'): Promise<WatchlistSnapshotResponse>
// 15s timeout
// GET /watchlist/snapshot?symbols=s1,s2,s3&period=1M

getMarketQuotes(symbols: string[]): Promise<any>
// Used as fallback when snapshot endpoint fails
// Returns Record<string, { price, change_pct, company_name, ... }>
```

---

## 12. Persistence

Watchlist symbols are persisted in `localStorage`:

| Key | Scope | Content |
|-----|-------|---------|
| `prospektlab_watchlist` | Guest (not logged in) | `JSON.stringify(string[])` |
| `prospektlab_watchlist:{email}` | Authenticated user | `JSON.stringify(string[])` (lowercased email) |

**Where writes happen:** The parent `Dashboard.tsx` component handles persistence. `WatchlistWorkspace` calls `onChangeSymbols()` which triggers the parent to update both state and localStorage.

**Where reads happen:** The parent `Dashboard.tsx` reads from localStorage on mount and initializes `watchlistSymbols`.

**Onboarding persistence:** `WatchlistStep.tsx` writes directly to localStorage before calling `setOnboarded(true)`.

**Note:** The Screener tab does NOT persist any state. Only the Watchlist tab's symbol list is persisted.

---

## 13. Error Handling & Loading States

| State | UI Display |
|-------|-----------|
| **History loading (non-1D)** | "Loading movers chart..." centered in chart area |
| **1D loading / no intraday data** | "Waiting for live price updates..." in chart area |
| **No chart data (history)** | "History is unavailable for selected symbols." |
| **Snapshot API error** | Backend error message in news section + fallback message in history: "Detailed watchlist history is temporarily unavailable. Showing live quotes." |
| **Snapshot fallback quotes** | Attempts `getMarketQuotes()` silently; if it succeeds, live quotes display. If it fails, ignored. |
| **News loading** | "Loading watchlist news..." |
| **News error** | Backend error message from the caught exception |
| **No news available** | "No watchlist news found right now." |
| **Empty watchlist** | Onboarding message + quick-add buttons |
| **No movement data** | "Not enough movement data yet." |
| **Image load error** | `onError` handler replaces with `fallbackImage` |
| **Modal backdrop click** | Closes modal (discards changes) |
| **Search timeout** | Backend timeout, caught by `fetchWithTimeout` wrapper |

**Graceful degradation strategy:**
1. Try `/watchlist/snapshot` for full data
2. On failure: fallback to `getMarketQuotes()` for live prices
3. On quote failure: use existing `liveQuotes` from `useMarketFeed` WebSocket
4. On WebSocket failure: `useMarketFeed` falls back to HTTP polling internally
5. Result: the user almost always sees live prices, even when backend services are partially down

---

## 14. File Index

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/src/pages/DashboardWatchlistPage.tsx` | 8 | Route page wrapper |
| `frontend/src/pages/WatchlistStep.tsx` | 273 | Onboarding watchlist builder |
| `frontend/src/components/dashboard/WatchlistWorkspace.tsx` | 1235+ | Main watchlist dashboard UI |
| `frontend/src/components/dashboard/WatchlistCard.tsx` | 219 | Legacy "Smart Watchlist" card component |
| `frontend/src/hooks/useMarketFeed.ts` | 455 | Shared real-time price feed |
| `frontend/src/api/client.ts` | 2574 | API functions + shared types (watchlist section) |
| `frontend/src/data/indianStocks.ts` | 14,142 | Indian stock + mutual fund lookup data |
| `frontend/src/utils/coverArt.ts` | 441 | Procedural SVG cover image generation |
| `backend/finagent/gateway/run.py` | 3200+ | FastAPI gateway (watchlist route + helpers: lines ~2332-2720) |
