# ProspektLab -- Screener Tab: Complete Architecture

---

## Table of Contents

1. [System Context](#1-system-context)
2. [Route & Entry Point](#2-route--entry-point)
3. [Frontend Architecture](#3-frontend-architecture)
   - [3.1 Primary Component](#31-primary-component)
   - [3.2 Internal Types](#32-internal-types)
   - [3.3 Utility Functions](#33-utility-functions)
   - [3.4 Error Boundary](#34-error-boundary)
4. [UI Structure & Data Displayed](#4-ui-structure--data-displayed)
   - [4.1 Search Bar](#41-search-bar)
   - [4.2 Quick Screener Row](#42-quick-screener-row)
   - [4.3 Company Header Card](#43-company-header-card)
   - [4.4 Tab Bar](#44-tab-bar)
   - [4.5 Freshness Row](#45-freshness-row)
   - [4.6 Overview Tab](#46-overview-tab)
   - [4.7 Fundamentals Tab](#47-fundamentals-tab)
   - [4.8 Technicals Tab](#48-technicals-tab)
   - [4.9 Governance Tab](#49-governance-tab)
   - [4.10 Events Tab](#410-events-tab)
   - [4.11 Footer](#411-footer)
5. [State Management](#5-state-management)
6. [Data Flow & API Calls](#6-data-flow--api-calls)
7. [Real-Time Price Feed](#7-real-time-price-feed)
8. [Export Functionality](#8-export-functionality)
9. [Backend Architecture](#9-backend-architecture)
   - [9.1 Service Layer](#91-service-layer)
   - [9.2 Scoring Engine](#92-scoring-engine)
   - [9.3 Schemas](#93-schemas)
   - [9.4 Gateway Routes](#94-gateway-routes)
10. [TypeScript Types](#10-typescript-types)
11. [Error Handling & Loading States](#11-error-handling--loading-states)
12. [Testing](#12-testing)
13. [File Index](#13-file-index)

---

## 1. System Context

ProspektLab is a full-stack Indian stock market research and portfolio analytics platform. The Screener tab is one of seven feature tabs accessible from `/dashboard/:featureTab`.

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 18.3.1 (Vite + TypeScript) |
| **Routing** | React Router DOM v6 |
| **State** | React Context API (`AuthContext`) + component-local `useState` |
| **Backend** | FastAPI (Python) at `backend/finagent/` |
| **Real-time** | Upstox WebSocket relay (`/ws/market`) with HTTP polling fallback |
| **Styling** | CSS (`screener.css`) |

---

## 2. Route & Entry Point

**Route:** `/dashboard/screener`

**Page component:** `frontend/src/pages/DashboardScreenerPage.tsx` (8 lines)

```tsx
import React from 'react';
import { ScreenerWorkspace } from '../components/screener/ScreenerWorkspace';

export const DashboardScreenerPage: React.FC = () => {
  return <ScreenerWorkspace />;
};

export default DashboardScreenerPage;
```

This is a thin wrapper. All real work happens inside `ScreenerWorkspace`.

---

## 3. Frontend Architecture

### 3.1 Primary Component

**File:** `frontend/src/components/screener/ScreenerWorkspace.tsx` (1068+ lines)

**Props:**
```typescript
interface ScreenerWorkspaceProps {
  embedded?: boolean;   // true when used inside chat panel (renders without AppShell wrapper)
}
```

**Styles:** `frontend/src/styles/screener.css` (940 lines)

When `embedded` is `true`, the workspace renders without the `<AppShell>` layout wrapper and adds the `.embedded` CSS class for adjusted padding.

### 3.2 Internal Types

```typescript
type ScreenerViewTab = 'overview' | 'fundamentals' | 'technicals' | 'governance' | 'events';
type FundamentalSegment = 'ratios' | 'income_statement' | 'balance_sheet' | 'cash_flow';
```

**Quick screener queries** (pre-built natural language queries):
```typescript
const QUICK_SCREENER_QUERIES = [
  { id: 'quality', label: 'Quality Leaders',
    query: 'quality companies with high roe and low debt' },
  { id: 'growth', label: 'Growth Leaders',
    query: 'high growth companies with improving profit and revenue momentum' },
  { id: 'value', label: 'Value Picks',
    query: 'profitable undervalued companies with reasonable pe' },
] as const;
```

**Default symbol:** The workspace auto-loads `RELIANCE` on first mount if no company is selected:
```typescript
const DEFAULT_SCREENER_SYMBOL = 'RELIANCE';
```

**Search debounce:** 250ms (`SEARCH_DEBOUNCE_MS`)

### 3.3 Utility Functions

All formatters are defined inline (not imported from shared utilities):

| Function | Purpose |
|----------|---------|
| `fmtNum(value, digits)` | Format number to fixed decimal places; returns "Unavailable" for NaN/Inf |
| `fmtPct(value, digits)` | Format as percentage string |
| `fmtInr(value, digits)` | Format as INR with Indian locale number formatting |
| `fmtCrore(value, digits)` | Format as INR crore with Indian locale |
| `trendTone(value)` | Returns 'up'/'down'/'neutral' based on sign |
| `getArray(value)` | Safely returns array (empty array if value is not array) |
| `formatSuggestionConfidence(value)` | Formats confidence score as percentage |
| `formatRatioValue(item)` | Formats ratio based on unit (%, crore, INR, or number) |
| `formatFreshnessStatus(value)` | Maps backend status strings to display labels (Live/Fresh/Stale/Aging/OK/Unavailable) |
| `displayText(value, fallback)` | Safe string display with fallback ("Not disclosed") |
| `sentimentTone(value)` | Maps sentiment labels to CSS classes (positive/negative/neutral) |
| `formatEventPublished(value)` | Formats event published time |
| `formatAge(value, unit)` | Formats freshness age (seconds or hours) |

**File export utilities:**
```typescript
downloadTextFile(filename, content, mimeType)
// Creates a Blob, generates object URL, programmatically clicks an anchor tag,
// then revokes the URL. Used for JSON and CSV downloads.

toCsv(rows: Array<Array<string | number | null | undefined>>)
// Escapes CSV values properly (quotes cells with commas, newlines, or double-quotes;
// doubles internal double-quotes).
```

**Sparkline component:**
```typescript
const Sparkline: React.FC<{ prices: number[] }>
```
An inline SVG component (360x84 viewBox) that renders a line + area chart from a price array. Auto-colors green/red based on first-to-last comparison. Shows "No chart history" for < 2 data points.

### 3.4 Error Boundary

```typescript
class ScreenerRenderBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
>
```

A class-based React error boundary that wraps the entire screener content. If any child component throws during render, it catches the error, logs to console, and displays: "Screener view encountered a rendering error. Please refresh."

---

## 4. UI Structure & Data Displayed

### 4.1 Search Bar

```
┌──────────────────────────────────────────────────┐
│ (Search icon) [Search company name, symbol...]    │
└──────────────────────────────────────────────────┘
```

- Text input with lucide-react `Search` icon
- 250ms debounced API call to `GET /screener/search?q={text}&limit=8`
- On focus: shows dropdown if suggestions exist
- On submit: selects first suggestion or loads raw symbol
- Shows "Searching..." status during API call

**Search dropdown items** display:
- Symbol (monospace, cyan) + Sector (right-aligned)
- Company name
- Source tag + confidence percentage
- `onMouseDown` handler uses `preventDefault()` to avoid blur-before-click race

### 4.2 Quick Screener Row

Three pill-shaped buttons for pre-built natural language queries. Clicking triggers `POST /screener/query` with that query string and a limit of 20.

**Loading state:** "Running screener query..."

**Result cards:** Up to 12 clickable cards showing symbol + company name. Clicking loads that company into full analysis.

**Empty result:** "No stocks matched this query yet."

### 4.3 Company Header Card

```
┌──────────────────────────────────────────────────────┐
│ (Building icon) RELIANCE                             │
│ Reliance Industries Limited                          │
│ Sector | CIN: L17110MH1973PLC019786 | ISIN: INE002.. │
│                                                      │
│ Rs 3,121.45        (up arrow) +1.23%                 │
│ (Gauge) Score 7.3 (B+)    Quote source: upstox_ws    │
│ [Export Snapshot] [Export Ratios]                     │
└──────────────────────────────────────────────────────┘
```

Displays:
- **Identity:** Symbol, full company name, sector, CIN, ISIN
- **Live price:** From `useMarketFeed` WebSocket tick, fallback to snapshot `quote.price`
- **Change %:** From live tick, with green/red trend arrow
- **Prospekt score:** Numeric score + letter grade
- **Quote source:** Where the live price comes from
- **Export buttons:** Enabled/disabled based on current tab

### 4.4 Tab Bar

```
[Overview] [Fundamentals] [Technicals] [Governance] [News & Corporate]
```

Active tab gets `.active` class. Clicking Fundamentals triggers `loadFinancials()` API call.

### 4.5 Freshness Row

Badges for each data section showing staleness:

```
Quote: Live  Fundamentals: Fresh  Technicals: Fresh  Governance: OK  News: Stale  Corporate: Available
```

Status values from backend: `live`, `fresh`, `available`, `ok`, `stale`, `aging`, `unavailable`

Color-coded:
- **Green (live):** live, fresh, available
- **Amber (stale):** stale
- **Red (unavailable):** everything else

### 4.6 Overview Tab

Rendered in a CSS grid layout.

#### Company Profile Section
- Business summary text (from `fundamentals.profile.business_summary` or `overview`)
- **Company facts grid:** Label/value pairs from `fundamentals.profile.facts` array
- Mission/Vision statements (if available in profile)
- Products/Services list (first 6 items)

#### Positives / Negatives Section
Two-column layout:
- **Positives** (up to 6 items, sorted first from `summary.positives`)
- **Negatives** (up to 6 items, from `summary.negatives`)
- Generated by backend `scoring.summarize_positive_negative()`

#### Peer Comparison Table

| Peer | P/E | ROE | ROCE | Debt/Eq |
|------|-----|-----|------|---------|
| ONGC | 8.32 | 14.50% | 18.20% | 0.45 |
| IOC | 5.10 | 12.30% | 15.40% | 0.82 |

- Source attribution at bottom
- "Peer set is unavailable" empty state

#### Public-Source Depth
Grid of status indicators:
- Segments status
- Related Party Transactions status
- Annual Reports status
- Auditor Remarks status
- Delivery % (numeric or status)
- Corporate Actions status
- Insider Trades status

Additional info:
- Segments found list (first 8)
- Link to latest annual report (FY year, clickable URL)
- Delivery data `as_of` date and source
- Note: "No paid APIs used. Restricted values stay labelled instead of inferred."

#### Contradictions / Blind Spots
List of detected contradictions with title + detail for each:
- Example: "Valuation vs Growth Conflict" / "High PE despite declining revenue growth"
- Example: "Profit vs Cashflow Mismatch" / "PAT growing but operating cash flow declining"
- Example: "Promoter Pledge Stress" / "High promoter pledge combined with declining stock price"
- Empty state: "No material contradiction detected in this snapshot."

Backend detects these via `scoring.detect_contradictions()`.

### 4.7 Fundamentals Tab

**Sub-tab bar:**
```
[Ratios] [Income Statement] [Balance Sheet] [Cash Flow]
```

Financial data is lazy-loaded: the `/screener/company/{id}/financials` endpoint is called only when the user switches to the Fundamentals tab.

#### Ratios View

Financial ratios grouped by category (each group has a title like "Profitability", "Valuation", "Liquidity"):
```
┌── Profitability ──────────────────────────┐
│  ROE             18.50%    Screener.in     │
│  ROCE            15.20%    Screener.in     │
│  Net Profit Margin  12.30%    Screener.in  │
└────────────────────────────────────────────┘

┌── Valuation ──────────────────────────────┐
│  P/E Ratio       22.40    Yahoo Finance    │
│  P/B Ratio        4.80    Yahoo Finance    │
└────────────────────────────────────────────┘
```

Each metric card: label, formatted value (auto-detecting unit from %/crore/INR contexts), source.

**Derived Public Analytics section** (from `financialsPayload.analytics`):
- DCF Fair Value (per share, INR)
- DCF Upside (%)
- Piotroski F-Score (0-9)
- DuPont ROE decomposition: ROE %, Asset Turnover, Equity Multiplier
- Source attribution

#### Financial Statements View

Multi-period comparison table for income statement, balance sheet, or cash flow:

```
┌──────────────┬──────────┬──────────┬──────────┬──────────┐
│ Metric       │ FY 2024  │ FY 2023  │ FY 2022  │ YoY      │
├──────────────┼──────────┼──────────┼──────────┼──────────┤
│ Revenue      │ Rs 9,01,064│ Rs 8,76,396│ Rs 7,32,456│ 2.82%   │
│ EBITDA       │ Rs 1,78,611│ Rs 1,62,314│ Rs 1,23,456│ 10.04%  │
│ Net Profit   │ Rs 69,621 │ Rs 66,702 │ Rs 53,456 │ 4.38%   │
└──────────────┴──────────┴──────────┴──────────┴──────────┘
```

Features:
- Period columns extracted from `financialsPayload.periods` array (supports both string and object formats)
- YoY column computed locally: `((latest - previous) / abs(previous)) * 100`
- Auto-formats values based on unit: INR/share uses per-share formatting, INR uses crore formatting
- Source line showing: name | as_of date | basis
- Unit displayed in table header
- Empty state: "Financial statement data is unavailable..."

### 4.8 Technicals Tab

Two-panel layout.

#### Technical Structure Panel

Grid of key indicators:
| Metric | Example Value |
|--------|--------------|
| Trend Bias | Bullish |
| RSI (14) | 58.42 |
| MACD | 12.3456 |
| MACD Signal | 10.2345 |
| SMA 20/50 | Golden Cross |
| SMA 50/200 | Neutral |
| Above 200 DMA | Yes |
| Breakout State | Resistance at 3200 |
| 1M Return | 3.45% |
| 3M Return | 12.30% |
| Volatility (1M ann.) | 18.50% |
| 52W Drawdown | 8.20% |

#### Price Structure Panel

- **Sparkline:** Inline SVG chart of price history (from `technicals.history.prices`)
- **Moving averages:** 20 DMA, 50 DMA, 200 DMA (INR format)
- **Bollinger Bands:** State + Upper Band + Lower Band (INR format)
- **Support/Resistance:** 20D Support, 20D Resistance (INR format)

All technical indicators are computed by `scoring.compute_technicals()` on the backend.

### 4.9 Governance Tab

**Governance metrics grid:**
- Governance Band (e.g., "Low Risk", "Moderate Risk", "High Risk" -- color-coded)
- Governance Score (numeric)
- Promoter Holding %, Promoter Pledge %
- FII Holding %, DII Holding %
- Public Holding %, Institutional Holding %
- Directors Tracked count
- Insider Facts count

**Shareholding source attribution** (from `fundamentals.sources.shareholding` or `sourceHealth.shareholding.status`)

**Governance Flags list:**
- Each flag: code + detail
- Examples: "PROM_PLEDGE" / "Promoter has pledged more than 50% of holdings"
- Up to 8 flags shown
- Empty state: "No governance flags returned..."

### 4.10 Events Tab

Four sections stacked vertically.

#### Latest News (up to 14 items)
Each item is a clickable `<a>` tag:
- Headline
- Meta: source | age | sentiment badge (positive/negative/neutral)
- Empty state: "No news items available."

#### Corporate & Enforcement (up to 12 items)
Each item is a clickable `<a>` tag:
- Title
- Meta: event_type | source | published | sentiment
- **Enforcement Signals sub-section:** Up to 8 enforcement items (violation_type + order_date)

#### Corporate Actions Calendar (up to 10 items)
- Title + event_type + published + source
- Empty state: "No corporate-action rows detected..."

#### Insider Trades (up to 8 items)
- Title + event_type + published + source
- Empty state: "No insider-trade disclosures detected..."

### 4.11 Footer

```
Active symbol: RELIANCE  Freshness: quote 2s, history 3.5h, news 2.1h
```

Shows active symbol and data freshness ages (quote in seconds, history/news in hours).

---

## 5. State Management

All state is component-local `useState` in `ScreenerWorkspace`. There is no Redux, Zustand, or external state library used.

| State Variable | Type | Purpose |
|---------------|------|---------|
| `searchText` | `string` | Current search input value |
| `suggestions` | `ScreenerSearchItem[]` | Autocomplete dropdown items |
| `searchBusy` | `boolean` | Search API in flight |
| `searchOpen` | `boolean` | Dropdown visibility |
| `activeSymbol` | `string` | Currently loaded company symbol (empty = none) |
| `analysisPayload` | `any` | Full response from `/screener/analyze` |
| `financialsPayload` | `any` | Response from `/screener/financials` |
| `financialsSymbol` | `string` | Cached symbol for financials (prevents re-fetch) |
| `analysisBusy` | `boolean` | Analysis API loading |
| `financialsBusy` | `boolean` | Financials API loading |
| `analysisError` | `string` | Error message for analysis |
| `financialsError` | `string` | Error message for financials |
| `queryRows` | `any[]` | Quick-screener result rows |
| `queryBusy` | `boolean` | Screener query in flight |
| `queryError` | `string` | Error message for query |
| `activeTab` | `ScreenerViewTab` | Current view tab |
| `fundamentalSegment` | `FundamentalSegment` | Current statement sub-view |

**Derived data** (computed from `analysisPayload` via destructuring, no `useMemo` unless noted):

```typescript
const snapshot = analysisPayload?.snapshot || null;
const resolved = snapshot?.resolved || {};
const score = snapshot?.score || {};
const quote = snapshot?.quote || {};
const fundamentals = snapshot?.fundamentals || {};
const publicDepth = fundamentals?.public_data_depth || {};
const financialAnalytics = financialsPayload?.analytics || {};
const technicals = snapshot?.technicals || {};
const governance = snapshot?.governance || {};
const events = snapshot?.events || {};
const summary = snapshot?.summary || {};
const freshness = snapshot?.freshness || {};
const peers = snapshot?.peers || {};
const sourceHealth = snapshot?.source_health || {};
```

**Memoized arrays** (computed via `useMemo` to avoid re-computation on re-renders):
- `positives`, `negatives` -- from `summary.positives/negatives`
- `newsRows`, `corpRows`, `corporateActionRows`, `insiderTradeRows` -- from `events.*`
- `enforcementRows` -- from `events.enforcement`
- `annualReportRows` -- from `publicDepth.annual_reports.items`
- `profileFacts` -- from `fundamentals.profile.facts`
- `peerRows` -- from `peers.items`
- `periodColumns` -- from `financialsPayload.periods` (normalized to `{ id, label }` objects)
- `ratioGroups` -- from `financialsPayload.ratios` (grouped by key)
- `contradictions` -- from `snapshot.contradictions`
- `freshnessItems` -- freshness status per section
- `activeStatement`, `statementRows` -- current financial statement data

---

## 6. Data Flow & API Calls

### Search Flow

```
User types in search box
   |
   v  (250ms debounce)
screenerSearch(query, 8)  -->  GET /screener/search?q={query}&limit=8
   |                             8s timeout
   |                             Returns: { query, items[], as_of }
   v
Dropdown shows suggestions
   |
   v  (User clicks suggestion or presses Enter)
selectSuggestion(item) / onSearchSubmit()
   |
   v
loadCompany(symbol)
   |
   v
getScreenerAnalysis(symbol)  -->  GET /screener/company/{symbol}/analyze
   |                                25s timeout
   |                                Returns full snapshot:
   |                                { snapshot: { resolved, quote, score,
   |                                  fundamentals, technicals, governance,
   |                                  events, summary, contradictions,
   |                                  peers, sources, freshness, insiders } }
   v
All tabs except Fundamentals render from this single payload
```

### Fundamentals Lazy Load

```
User clicks "Fundamentals" tab
   |
   v  (triggered by useEffect watching activeTab)
loadFinancials(activeSymbol)
   |
   v
getScreenerFinancials(symbol)  -->  GET /screener/company/{symbol}/financials
   |                                   18s timeout
   |                                   Returns: { periods[], ratios,
   |                                     income_statement, balance_sheet,
   |                                     cash_flow, analytics }
   v
Ratio cards + statement tables render
```

### Quick Screener Query Flow

```
User clicks "Quality Leaders" button
   |
   v
runQuickQuery(query)
   |
   v
runScreenerQuery(query, 20)  -->  POST /screener/query
   |                                  Body: { query, limit: 20, universe: [] }
   |                                  Content-Type: application/json
   |                                  15s timeout
   |                                  Returns: { as_of, query, parsed_filter,
   |                                    universe_size, match_count, matches[] }
   v
Matched stocks displayed as clickable result cards
```

### Initial Load

```typescript
useEffect(() => {
  if (activeSymbol || analysisBusy) return;
  void loadCompany(DEFAULT_SCREENER_SYMBOL);  // 'RELIANCE'
}, [activeSymbol, analysisBusy]);
```

On mount, if no company is loaded and not currently loading, auto-loads RELIANCE.

### Re-fetch Prevention

```typescript
const loadFinancials = async (symbol: string) => {
  if (financialsBusy) return;                          // Already loading
  if (financialsPayload && financialsSymbol === symbol) return;  // Already cached
  // ... fetch
};
```

Financials are cached per symbol and not re-fetched unless the symbol changes.

---

## 7. Real-Time Price Feed

The Screener tab subscribes to live prices for the active company via:

```typescript
const { prices: livePrices } = useMarketFeed(
  activeSymbol ? [activeSymbol] : [],
  { includeIndices: false }
);
```

**Price resolution priority:**
1. `liveTick.price` (from WebSocket) -- most recent
2. `quote.price` (from snapshot) -- fallback

```typescript
const liveTick = activeSymbol ? livePrices[activeSymbol.toUpperCase()] : undefined;
const livePrice = liveTick?.price ?? quote?.price;
const liveChangePct = liveTick?.change_pct ?? quote?.change_pct;
const liveSource = liveTick?.source || quote?.source;
```

The `useMarketFeed` hook (`frontend/src/hooks/useMarketFeed.ts`, 455 lines):
- Connects to `/ws/market` WebSocket (Upstox relay)
- Receives snapshots and ticks
- Falls back to HTTP polling (`getMarketQuotes`) every 5s on connection failure
- Schedules reconnection with exponential backoff: 1s, 2s, 4s, 8s, 15s

**Freshness tracking:** The header shows `liveSource` and the footer shows `freshness.quote_age_seconds`.

---

## 8. Export Functionality

### Export Snapshot (JSON)

- **Available:** Always, when `snapshot` is loaded
- **Output:** `{SYMBOL}-screener-snapshot.json`
- **Content:** The entire `snapshot` object, `JSON.stringify` with 2-space indentation
- **MIME:** `application/json`

```typescript
const exportSnapshotJson = useCallback(() => {
  if (!snapshot) return;
  const symbol = String(resolved?.symbol || activeSymbol || 'company').toUpperCase();
  downloadTextFile(`${symbol}-screener-snapshot.json`, JSON.stringify(snapshot, null, 2), 'application/json');
}, [snapshot, resolved?.symbol, activeSymbol]);
```

### Export Ratios (CSV)

- **Available:** When on Fundamentals > Ratios sub-tab, and ratio data exists
- **Output:** `{SYMBOL}-ratios.csv`
- **Content:** `Group, Metric, Value, Unit, Source` columns
- **MIME:** `text/csv;charset=utf-8`

### Export Statement (CSV)

- **Available:** When on Fundamentals > Income/Balance/Cash Flow sub-tab, and statement data exists
- **Output:** `{SYMBOL}-{segment}.csv` (e.g., `RELIANCE-income_statement.csv`)
- **Content:** `Metric, {period labels}..., Source` columns
- **MIME:** `text/csv;charset=utf-8`

All exports use `URL.createObjectURL` + programmatic anchor click. CSV values are properly escaped (special chars, commas, quotes).

---

## 9. Backend Architecture

### 9.1 Service Layer

**File:** `backend/finagent/screener/service.py` (3612 lines)

`ScreenerService` orchestrates the entire screener pipeline:

#### Identity Resolution
- Uses entity resolver (`get_entity_resolver`) for symbol/ISIN/CIN/name resolution
- Hardcoded fallback maps for known symbols (e.g., `_KNOWN_ISIN_SYMBOLS`, `_KNOWN_SYMBOL_CIN` maps for RELIANCE, TCS, INFY, HDFCBANK, etc.)
- Symbol aliases (e.g., `ZOMATO -> ETERNAL`)
- Default screening universe of 44 major Indian stocks

#### Snapshot Fetching (Parallel)
Fetches data from multiple sources concurrently (`asyncio.gather`):
- NSE/Screener.in financials via `fetch_screener_financials()`
- Yahoo Finance quotes via `fetch_yahoo_quote()` and `fetch_yahoo_chart()`
- Moneycontrol financial data via HTML scraping
- NSE announcements via `fetch_nse_announcements()`
- Shareholding patterns via `fetch_shareholding_pattern()`
- Delivery snapshots via `fetch_nse_delivery_snapshot()`
- News via `fetch_news()`
- India market snapshot via `fetch_india_snapshot()`

**Data precedence:** XBRL official filings > Screener.in cache > Yahoo Finance > Moneycontrol

#### Financial Statement Normalization
- Standardizes income statements, balance sheets, cash flows across sources
- Computes derived ratios
- Handles different accounting standards and period formats

#### Peer Comparison
- Maintains `_PEER_HINTS_BY_SYMBOL` dict with known peer sets
- Falls back to sector-based peer discovery when no explicit hints exist

#### Governance Checks
- Uses IKG (Internal Knowledge Graph) governance scorer
- Integrates director network explorer for insider tracking

#### Orchestration
- Manages concurrency for parallel data fetching
- Merges multi-source data with priority rules
- Handles graceful degradation when sources are unavailable
- Uses staleness checker to track data freshness

### 9.2 Scoring Engine

**File:** `backend/finagent/screener/scoring.py` (588 lines)

#### `parse_nl_filters(query: str) -> ScreenerFilter`

Parses natural language queries into structured filter constraints. Recognizes patterns like:
- "ROCE > 18" → `min_roce: 18.0`
- "PE < 20" → `max_pe: 20.0`
- "above 200 dma" → `require_above_200dma: True`
- "no promoter pledge" → `require_no_pledge: True`
- "low debt" → `max_debt_to_equity: 0.5`
- Quality/growth/value keyword detection

Returns a `ScreenerFilter` dataclass with all constraints and `parse_notes` explaining what was understood.

#### `compute_scores(fundamentals, technicals, governance) -> dict`

Computes the Prospekt composite score with:
- **Numeric score** (0.0 - 10.0)
- **Letter grade:** A+, A, B+, B, C, D, F
- **Pillar breakdowns:**
  - Quality (ROE, ROCE, margins, consistency)
  - Valuation (PE, PB, PEG, DCF)
  - Momentum (RSI, moving averages, returns)
  - Governance (promoter holding, pledge, board quality)

#### `compute_technicals(dates, prices) -> dict`

From a close-price series, computes:
- **Moving averages:** SMA 20, SMA 50, SMA 200
- **EMA:** 12-day, 26-day
- **MACD:** Line, Signal line, Histogram (using 9-day EMA of MACD series when >= 35 data points)
- **RSI (14):** Wilder's smoothing method
- **Bollinger Bands:** Upper/Lower (SMA 20 ± 2σ)
- **Trend signals:** SMA 20/50 crossover, SMA 50/200 crossover, above_200dma
- **Breakout state:** Support/resistance levels
- **Returns:** 1M, 3M % change
- **Volatility:** 1M annualized (standard deviation scaled)
- **Drawdown:** From 52-week high
- **History:** Sparkline prices array

Returns `{ status: "unavailable", reason: "insufficient_history" }` if < 3 price data points.

#### `detect_contradictions(snapshot) -> list`

Detects contradictions by analyzing cross-section data:
- **Valuation vs Growth:** High PE + declining revenue growth
- **Profit vs Cashflow:** Growing PAT + declining operating cash flow
- **Promoter Pledge Stress:** High pledge % + declining stock price
- **Governance Red Flags:** Specific governance flags that conflict with apparent financial health
- **Quality Dissonance:** High ROE paired with extremely high leverage

Each contradiction has a `title` and `detail` string.

#### `check_filter_match(company_data, filter: ScreenerFilter) -> bool`

Applies structured constraints from NL parsing to a candidate company's data. Returns `True` if all constraints pass.

#### `summarize_positive_negative(snapshot) -> dict`

Generates bullet-point lists of strengths ("Positives") and weaknesses ("Negatives") from the overall analysis, used in the Overview tab.

#### Utility Functions

| Function | Purpose |
|----------|---------|
| `safe_float(value)` | Safe float conversion, returns None for NaN/Inf/bad input |
| `_sma(values, window)` | Simple moving average |
| `_ema(values, window)` | Exponential moving average |
| `_stddev(values)` | Standard deviation |
| `_pct_change(current, base)` | Percentage change |
| `_rsi(values, period)` | Relative Strength Index (Wilder's smoothing) |

### 9.3 Schemas

**File:** `backend/finagent/screener/schemas.py` (47 lines)

```python
@dataclass
class ScreenerFilter:
    """Parsed natural-language filters for stock screening."""
    min_roce: float | None = None
    min_roe: float | None = None
    max_pe: float | None = None
    min_pe: float | None = None
    max_debt_to_equity: float | None = None
    min_promoter_holding: float | None = None
    max_promoter_pledge: float | None = None
    require_no_pledge: bool = False
    require_above_200dma: bool = False
    min_rsi: float | None = None
    max_rsi: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    keywords: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)
```

The `to_dict()` method serializes all fields for API responses.

### 9.4 Gateway Routes

All routes defined in `backend/finagent/gateway/run.py`:

| Endpoint | Method | Purpose | Key Params |
|----------|--------|---------|-----------|
| `/screener/search` | GET | Company autocomplete | `q` (query string), `limit` (default 10) |
| `/screener/company/{identifier}/snapshot` | GET | Full snapshot | `period` (1M/3M/6M/YTD/1Y/MAX) |
| `/screener/company/{identifier}/financials` | GET | Normalized financials | (none) |
| `/screener/company/{identifier}/technicals` | GET | Technical indicators | `period` |
| `/screener/company/{identifier}/events` | GET | News & events | `limit` (default 25) |
| `/screener/company/{identifier}/analyze` | GET | Full analysis (all sections combined) | (none) |
| `/screener/query` | POST | NL screener query | `query`, `limit`, `universe[]` |

The `analyze` endpoint is the primary one used by the frontend. It aggregates snapshot + financials + technicals + governance + events into a single response. The individual endpoints exist for direct API access but the frontend only calls `analyze` + `financials` (lazy-loaded).

---

## 10. TypeScript Types

From `frontend/src/api/client.ts`:

```typescript
interface ScreenerSearchItem {
  symbol: string;
  cin?: string | null;
  isin?: string | null;
  name: string;
  sector?: string;
  confidence?: number | null;
  source?: string;
}

interface ScreenerSearchResponse {
  query: string;
  items: ScreenerSearchItem[];
  as_of: string;
}

interface ScreenerQueryResponse {
  as_of: string;
  query: string;
  parsed_filter: Record<string, any>;
  universe_size: number;
  match_count: number;
  matches: Array<Record<string, any>>;
}
```

API functions:
```typescript
screenerSearch(query: string, limit = 8): Promise<ScreenerSearchResponse>
getScreenerSnapshot(identifier: string, period = '1Y'): Promise<any>
getScreenerFinancials(identifier: string): Promise<any>
getScreenerTechnicals(identifier: string, period = '1Y'): Promise<any>
getScreenerEvents(identifier: string, limit = 25): Promise<any>
getScreenerAnalysis(identifier: string): Promise<any>
runScreenerQuery(query: string, limit = 25, universe = []): Promise<ScreenerQueryResponse>
```

Timeouts:
- `screenerSearch`: 8s
- `getScreenerSnapshot`: 15s
- `getScreenerFinancials`: 18s
- `getScreenerTechnicals`: 12s
- `getScreenerEvents`: 12s
- `getScreenerAnalysis`: 25s (longest -- aggregates multiple backend calls)
- `runScreenerQuery`: 15s

---

## 11. Error Handling & Loading States

| State | UI Display |
|-------|-----------|
| **Search in progress** | "Searching..." text next to search bar |
| **No company selected** | "Select a company from search suggestions to open full screener analysis." |
| **Analysis loading** | 3 skeleton placeholder cards + "Loading full analysis..." |
| **Analysis error** | Red `.screener-error` box with error message |
| **Financials loading** | Skeleton card + "Loading financial statements..." |
| **Financials error** | Red `.screener-error` box with error message |
| **Query running** | "Running screener query..." text |
| **Query error** | Red `.screener-error` with message |
| **No query matches** | "No stocks matched this query yet." |
| **No data for section** | Section-specific empty message (e.g., "Financial statement data is unavailable...", "No news items available.", "Peer set is unavailable...") |
| **Render error** | `ScreenerRenderBoundary` catches → "Screener view encountered a rendering error. Please refresh." |
| **Timeout** | API-specific timeout messages (e.g., "Screener analysis is still loading. Please retry.") |
| **Invalid data** | `fmtNum`/`fmtPct`/`fmtInr`/`fmtCrore` return "Unavailable" for NaN/Inf values |
| **Missing text** | `displayText()` returns "Not disclosed" for empty strings |

**Data fetch cancellation:** The search effect uses a `cancelled` flag pattern to prevent stale results:

```typescript
useEffect(() => {
  let cancelled = false;
  const timer = window.setTimeout(async () => {
    // ... fetch ...
    if (!cancelled) {
      setSuggestions(rows);
    }
  }, SEARCH_DEBOUNCE_MS);
  return () => {
    cancelled = true;
    window.clearTimeout(timer);
  };
}, [searchText]);
```

---

## 12. Testing

All tests use `pytest` with `monkeypatch` for mocking external dependencies.

| File | Coverage |
|------|----------|
| `test_screener_service.py` | `ScreenerService`: snapshot merging, query screening, financial normalization, concurrency patterns, Moneycontrol/Screener.in HTML parsing |
| `test_screener_scoring.py` | Scoring module: `parse_nl_filters()` for various NL patterns, `compute_technicals()` edge cases, `compute_scores()` grade boundaries, `detect_contradictions()` detection logic, `check_filter_match()` constraint matching |
| `test_screener_gateway_routes.py` | FastAPI gateway routes: search limit clamping, company route delegation, query universe sanitization. Uses `FakeScreenerService` (test double) |

---

## 13. File Index

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/src/pages/DashboardScreenerPage.tsx` | 8 | Route page wrapper |
| `frontend/src/components/screener/ScreenerWorkspace.tsx` | 1068+ | Main screener UI component |
| `frontend/src/styles/screener.css` | 940 | All screener styling |
| `frontend/src/hooks/useMarketFeed.ts` | 455 | Shared real-time price feed (used by screener) |
| `frontend/src/api/client.ts` | 2574 | API functions + shared types (screener section) |
| `backend/finagent/screener/service.py` | 3612 | Core screener orchestration service |
| `backend/finagent/screener/scoring.py` | 588 | Scoring engine, technicals, NL filter parsing |
| `backend/finagent/screener/schemas.py` | 47 | Pydantic/dataclass schemas |
| `backend/finagent/screener/__init__.py` | - | Package exports (`ScreenerService`, scoring functions) |
| `backend/finagent/gateway/run.py` | 3200+ | FastAPI gateway (screener routes: lines ~3147-3240) |
| `backend/finagent/tests/test_screener_service.py` | - | Service unit tests |
| `backend/finagent/tests/test_screener_scoring.py` | - | Scoring unit tests |
| `backend/finagent/tests/test_screener_gateway_routes.py` | - | Route integration tests |
