# 🗄️ ProspektLab Database & State Management Schema

**Version:** 2.0.0  
**Last Updated:** May 21, 2026

---

## 📋 Table of Contents

1. [State Management Architecture](#state-management)
2. [Checkpoint Structure](#checkpoint-structure)
3. [Session Schema](#session-schema)
4. [Memory Store Schema](#memory-store-schema)
5. [Citation Log Schema](#citation-log-schema)
6. [Persistent Storage](#persistent-storage)
7. [Data Retention Policies](#data-retention)
8. [Queries & Indices](#queries-and-indices)
9. [Migration Strategy](#migration-strategy)

---

## State Management Architecture

### Overview

ProspektLab uses **three layers** of state management:

```
┌─────────────────────────────────────────────┐
│  In-Memory State (Fast)                     │
│  - Session objects                          │
│  - Event queues                             │
│  - Temporary caches                         │
└─────────────────────────────────────────────┘
					▼
┌─────────────────────────────────────────────┐
│  File-Based Checkpoints (Medium)            │
│  - ~/.finagent/state/*.json                 │
│  - Checkpoints of research phases           │
│  - Recovery from failures                   │
└─────────────────────────────────────────────┘
					▼
┌─────────────────────────────────────────────┐
│  Persistent Storage (Durable)               │
│  - ~/.finagent/memory/*.json                │
│  - Long-term fact store                     │
│  - Optional: Supabase PostgreSQL            │
└─────────────────────────────────────────────┘
```

### Current State: Filesystem-Based

```
~/.finagent/
├── state/
│   ├── session_abc-123.json              # Checkpoint for session
│   ├── session_def-456.json
│   └── ...
├── memory/
│   ├── entity_TCS.json                   # Facts about TCS
│   ├── entity_INFY.json
│   └── ...
├── memos/
│   ├── session_abc-123.md                # Generated memo
│   ├── session_def-456.md
│   └── ...
└── cache/
	├── search_results.json               # Web search cache
	└── ...
```

### Future State: Database-Backed

```
PostgreSQL / Supabase
├── sessions (session_id, user_id, query, depth, status, created_at)
├── checkpoints (id, session_id, phase, data, timestamp)
├── memory_facts (id, target, claim, source, confidence, created_at)
├── citations (id, checkpoint_id, claim_text, source, url, confidence)
└── users (id, email, api_key, created_at)
```

---

## Checkpoint Structure

### Schema

```python
@dataclass
class Checkpoint:
	"""Snapshot of research progress at each phase."""

	session_id: str
	phase: str                             # identify | enrichment | breadth_survey | ...
	timestamp: datetime

	# Phase-specific results
	phase_result: StepResult | None

	# Accumulated state
	memo_draft: str | None                 # Memo being built
	memory_facts: list[MemoryFact]        # Facts discovered so far
	citations: list[Citation]              # Sources & citations

	# Metadata
	elapsed_time_seconds: float
	progress_percent: float
	errors: list[str]                      # Errors in this phase
	recovery_info: dict | None             # For resuming after failure
```

### Storage Location

```json
~/.finagent/state/session_550e8400-e29b-41d4-a716-446655440000.json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "target": "ASIANPAINT",
  "query": "Deep analysis of Asian Paints",
  "depth": "deep",
  "created_at": "2026-05-21T10:30:00Z",
  "phases": {
	"identify": {
	  "phase": "identify",
	  "timestamp": "2026-05-21T10:30:05Z",
	  "result": {
		"ticker": "ASIANPAINT",
		"isin": "INE021A01012",
		"exchange": "NSE",
		"company_name": "Asian Paints (India) Limited"
	  },
	  "progress_percent": 10,
	  "elapsed_time_seconds": 5
	},
	"enrichment": {
	  "phase": "enrichment",
	  "timestamp": "2026-05-21T10:30:35Z",
	  "result": {
		"india_snapshot": {
		  "price": 3250,
		  "market_cap": 2100000000000,
		  "pe_ratio": 42.5,
		  "roe": 18.2,
		  "dividend_yield": 1.85
		},
		"news_items": [
		  {
			"headline": "Asian Paints Q4 Results...",
			"source": "Economic Times",
			"url": "...",
			"sentiment": "positive"
		  }
		],
		"wikipedia_summary": "Asian Paints is India's leading paint company..."
	  },
	  "progress_percent": 35,
	  "elapsed_time_seconds": 30
	},
	"breadth_survey": {
	  "phase": "breadth_survey",
	  "timestamp": "2026-05-21T10:31:35Z",
	  "result": {
		"scraped_docs": [
		  {
			"url": "...",
			"title": "...",
			"text": "...",
			"facts_extracted": [...]
		  }
		]
	  },
	  "progress_percent": 50,
	  "elapsed_time_seconds": 60
	},
	"deep_dive": {...},
	"analysis": {...},
	"specialist_analysis": {...},
	"verification": {...},
	"synthesis": {...}
  },
  "memory_facts": [
	{
	  "target": "ASIANPAINT",
	  "claim": "Asian Paints market cap is ₹2.1 trillion",
	  "source": "NSE API",
	  "confidence": 0.95,
	  "created_at": "2026-05-21T10:30:30Z"
	}
  ],
  "citations": [
	{
	  "claim_text": "Market cap ₹2.1T",
	  "source": "NSE India",
	  "url": "https://www.nseindia.com/...",
	  "confidence": 0.95,
	  "timestamp": "2026-05-21T10:30:30Z"
	}
  ],
  "status": "complete",
  "total_time_seconds": 245,
  "quality_score": 84
}
```

### Phase Results (StepResult)

```python
@dataclass
class StepResult:
	"""Result of a single research phase."""

	phase: str
	success: bool
	data: dict                             # Phase-specific data
	errors: list[str]
	warnings: list[str]
	metadata: dict

# Examples by phase:

# Phase: identify
StepResult(
	phase="identify",
	data={
		"ticker": "TCS",
		"exchange": "NSE",
		"isin": "INE467B01029"
	}
)

# Phase: enrichment
StepResult(
	phase="enrichment",
	data={
		"india_snapshot": {...},
		"news": [...],
		"wikipedia": {...}
	}
)

# Phase: specialist_analysis
StepResult(
	phase="specialist_analysis",
	data={
		"accounting": {...},
		"competitive": {...},
		"governance": {...},
		"valuation": {...}
	}
)
```

---

## Session Schema

### Session Object (In-Memory)

```python
@dataclass
class Session:
	"""Active research session."""

	id: str                                # UUID
	query: str
	depth: str                             # chat | standard | deep | marathon
	status: str                            # running | complete | failed
	created_at: datetime
	started_at: datetime
	completed_at: datetime | None

	# Progress tracking
	current_phase: str
	progress_percent: float                # 0-100
	phases_complete: list[str]

	# Output
	events: list[dict]                     # Event queue
	memo: str | None                       # Final memo (when complete)
	result: ResearchResult | None

	# Metadata
	user_id: str | None                    # For auth (future)
	metadata: dict
```

### Session Status Transitions

```
┌─────────┐
│ created │
└────┬────┘
	 │
	 ▼
┌─────────────┐
│   running   │ ← Can be interrupted
└────┬────────┘
	 │
	 ├─ On success ─┐
	 │               ▼
	 │          ┌──────────┐
	 │          │ complete │
	 │          └──────────┘
	 │
	 ├─ On error ───┐
	 │               ▼
	 │          ┌────────┐
	 │          │ failed │
	 │          └────────┘
```

### Session Storage

#### In-Memory (Active)
```python
sessions: dict[str, Session] = {}

# Access
session = sessions.get(session_id)
if session:
	session.current_phase = "enrichment"
	session.progress_percent = 35
```

#### Persistent (Completed)
```
~/.finagent/state/session_{id}.json
```

### Session Lifecycle

```
1. CREATE
   - Generate session_id
   - Create Session object
   - Store in sessions dict
   - Emit: research_started

2. RUN PHASES (loop)
   - Phase 1-8 execute
   - Each updates: current_phase, progress_percent, phases_complete
   - Emit: phase_start, phase_complete events

3. COMPLETE
   - Write checkpoint to disk
   - Generate memo
   - Store memory facts
   - Status = "complete"
   - Emit: research_complete
   - Delete from sessions dict (archive to disk)

4. EXPIRY
   - After 24 hours: delete from disk
   - Or: prune via cleanup task
```

---

## Memory Store Schema

### MemoryFact Structure

```python
@dataclass
class MemoryFact:
	"""Persistent fact about a target."""

	id: str                                # UUID
	target: str                            # "TCS", "INFY", etc
	claim: str                             # "TCS revenue ₹200k Cr"
	source: str                            # Where it came from
	source_url: str | None

	# Quality
	confidence: float                      # 0.0-1.0
	verified: bool
	verification_method: str               # cross_source | calculation | api

	# Temporal
	created_at: datetime
	updated_at: datetime
	expires_at: datetime | None            # TTL for seasonal data

	# Attribution
	extracted_from_session: str | None     # session_id
	extracted_by_agent: str                # Which agent found this

	# Metadata
	tags: list[str]                        # ["financials", "growth", ...]
	related_facts: list[str]               # IDs of related facts
```

### Storage

```json
~/.finagent/memory/entity_TCS.json
{
  "target": "TCS",
  "facts": [
	{
	  "id": "fact-001",
	  "claim": "TCS revenue in FY25 is ₹200,000 Cr",
	  "source": "NSE API",
	  "confidence": 0.95,
	  "created_at": "2026-05-20T15:30:00Z",
	  "verified": true,
	  "tags": ["financials", "revenue", "fy25"]
	},
	{
	  "id": "fact-002",
	  "claim": "TCS PE ratio is 42.5x",
	  "source": "MCP Fundamentals",
	  "confidence": 0.98,
	  "created_at": "2026-05-21T10:00:00Z",
	  "verified": true,
	  "tags": ["valuation", "pe", "current"]
	}
  ],
  "last_updated": "2026-05-21T10:00:00Z",
  "total_facts": 2
}
```

### Recall Query

```python
async def recall_facts(target: str, query: str) -> list[MemoryFact]:
	"""Find relevant facts from memory."""

	# Load entity file
	path = f"~/.finagent/memory/entity_{target}.json"
	data = json.load(open(path))

	# Keyword matching (simple; upgrade to embeddings)
	query_keywords = query.lower().split()
	matching_facts = []

	for fact in data['facts']:
		fact_keywords = fact['claim'].lower().split()
		overlap = len(set(query_keywords) & set(fact_keywords))

		if overlap > 0 and fact['confidence'] > 0.7:
			matching_facts.append(fact)

	# Sort by confidence
	matching_facts.sort(key=lambda f: f['confidence'], reverse=True)
	return matching_facts[:5]  # Top 5
```

---

## Citation Log Schema

### Citation Structure

```python
@dataclass
class Citation:
	"""Attribution of a claim to its source."""

	id: str                                # UUID
	session_id: str

	# What was cited
	claim_text: str                        # "Asian Paints PE is 42.5x"

	# Source
	source_name: str                       # "NSE API", "Wikipedia", "Reddit"
	source_url: str | None
	source_type: str                       # api | website | social | document

	# Quality
	confidence: float                      # 0.0-1.0
	verified: bool

	# Temporal
	extracted_at: datetime
	found_at_url: str | None               # URL where found
	fetch_timestamp: datetime

	# Metadata
	agent_extracted_by: str                # Which agent
	memo_section: str                      # Where used in memo
```

### Storage

```json
~/.finagent/state/session_550e8400-e29b-41d4-a716-446655440000.json
{
  "citations": [
	{
	  "id": "cite-001",
	  "claim_text": "Asian Paints market cap is ₹2.1 trillion",
	  "source_name": "NSE API",
	  "source_url": "https://www.nseindia.com/market-data/...",
	  "confidence": 0.95,
	  "verified": true,
	  "extracted_at": "2026-05-21T10:30:30Z",
	  "memo_section": "## Financial Overview"
	},
	{
	  "id": "cite-002",
	  "claim_text": "Asian Paints is market leader in decorative paints",
	  "source_name": "Wikipedia",
	  "source_url": "https://en.wikipedia.org/wiki/Asian_Paints",
	  "confidence": 0.85,
	  "verified": true,
	  "extracted_at": "2026-05-21T10:30:45Z",
	  "memo_section": "## Company Overview"
	}
  ]
}
```

---

## Persistent Storage

### Directory Structure

```
~/.finagent/
├── state/                              # Checkpoint storage (24h TTL)
│   ├── session_uuid-1.json
│   ├── session_uuid-2.json
│   └── ...
│
├── memory/                             # Long-term fact store
│   ├── entity_TCS.json                # Facts about TCS
│   ├── entity_INFY.json               # Facts about Infosys
│   ├── entity_RELIANCE.json
│   └── ...
│
├── memos/                              # Generated research memos
│   ├── session_uuid-1.md
│   ├── session_uuid-2.md
│   └── ...
│
├── cache/                              # Response caching
│   ├── web_search_results.json
│   ├── api_responses.json
│   └── ...
│
└── logs/                               # Application logs
	├── research.log
	├── agent.log
	└── ...
```

### File Formats

#### JSON Checkpoint
```json
{
  "session_id": "...",
  "phases": {...},
  "status": "complete"
}
```

#### Markdown Memo
```markdown
# Company Analysis Memo

## Executive Summary
...

## Financials
...

## References
[1] Source 1
[2] Source 2
```

#### Memory Facts
```json
{
  "target": "TICKER",
  "facts": [...]
}
```

---

## Data Retention Policies

### Session Checkpoints

| Status | Retention | Rationale |
|--------|-----------|-----------|
| **Running** | In-memory | Active session |
| **Complete** | 24 hours | Archive to memo |
| **Failed** | 7 days | Debug & analysis |
| **Archived** | 30 days | Compliance, historical |

### Memory Facts

| Data Type | TTL | Notes |
|-----------|-----|-------|
| **Financials** | 30 days | Changes quarterly |
| **Prices** | 1 day | Real-time data |
| **News** | 7 days | Becomes stale |
| **Analyst Reports** | 90 days | Longer relevance |
| **Management Quality** | 1 year | Stable attribute |

### Implementation

```python
async def cleanup_expired_sessions():
	"""Prune old session files."""
	now = datetime.now()
	session_dir = Path("~/.finagent/state")

	for session_file in session_dir.glob("session_*.json"):
		checkpoint = json.load(open(session_file))
		created_at = datetime.fromisoformat(checkpoint['created_at'])

		# Delete if older than retention period
		if (now - created_at).days > 7:  # 7-day retention
			session_file.unlink()

# Run daily via cron or scheduler
schedule.every().day.at("02:00").do(cleanup_expired_sessions)
```

---

## Queries & Indices

### Common Queries

#### Find Latest Facts About Target

```python
def get_latest_facts(target: str, limit: int = 10) -> list[MemoryFact]:
	"""Get most recent facts about a company."""
	path = f"~/.finagent/memory/entity_{target}.json"
	data = json.load(open(path))

	facts = data['facts']
	facts.sort(key=lambda f: f['created_at'], reverse=True)
	return facts[:limit]
```

#### Find High-Confidence Facts

```python
def get_verified_facts(target: str, min_confidence: float = 0.8) -> list[MemoryFact]:
	"""Get only verified facts above confidence threshold."""
	path = f"~/.finagent/memory/entity_{target}.json"
	data = json.load(open(path))

	verified = [f for f in data['facts'] 
				if f['verified'] and f['confidence'] >= min_confidence]
	return verified
```

#### Search by Tag

```python
def find_facts_by_tag(target: str, tag: str) -> list[MemoryFact]:
	"""Find facts tagged with specific keyword."""
	path = f"~/.finagent/memory/entity_{target}.json"
	data = json.load(open(path))

	tagged = [f for f in data['facts'] if tag in f.get('tags', [])]
	return tagged
```

### Proposed Indices (PostgreSQL)

```sql
-- When migrating to database:

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_created_at ON sessions(created_at DESC);

CREATE INDEX idx_memory_facts_target ON memory_facts(target);
CREATE INDEX idx_memory_facts_confidence ON memory_facts(confidence DESC);
CREATE INDEX idx_memory_facts_verified ON memory_facts(verified);

CREATE INDEX idx_citations_session_id ON citations(session_id);
CREATE INDEX idx_citations_source_name ON citations(source_name);
```

---

## Migration Strategy

### Phase 1: Current (Filesystem)

**Pros:**
- Simple, no DB setup required
- Easy to inspect files
- Works offline

**Cons:**
- Not scalable beyond local machine
- No concurrent access control
- Hard to query across entities
- No backup strategy

### Phase 2: Local SQLite (Optional)

```python
import sqlite3

# Create schema
conn = sqlite3.connect('~/.finagent/finagent.db')
cursor = conn.cursor()

cursor.execute('''
	CREATE TABLE IF NOT EXISTS memory_facts (
		id TEXT PRIMARY KEY,
		target TEXT NOT NULL,
		claim TEXT NOT NULL,
		source TEXT,
		confidence REAL,
		verified BOOLEAN,
		created_at TEXT,
		FOREIGN KEY(target) REFERENCES entities(name)
	)
''')

cursor.execute('CREATE INDEX IF NOT EXISTS idx_target ON memory_facts(target)')
conn.commit()
```

### Phase 3: Production (PostgreSQL + Supabase)

```python
import asyncpg

# Connect
pool = await asyncpg.create_pool(
	'postgresql://user:pass@supabase.../db',
	min_size=10,
	max_size=20
)

# Query
async with pool.acquire() as conn:
	facts = await conn.fetch(
		'SELECT * FROM memory_facts WHERE target = $1 AND confidence > $2',
		target, 0.8
	)
```

### Migration Steps

```
1. Export filesystem data to JSON schema
   └─ For each entity, extract facts

2. Create PostgreSQL schema
   └─ CREATE TABLE memory_facts, sessions, checkpoints, citations

3. Bulk import from JSON
   └─ COPY statement or programmatic insert

4. Validate data integrity
   └─ Row counts match, no orphans

5. Switch to database backend in production
   └─ Update code: use pool instead of filesystem

6. Keep filesystem as backup during transition
   └─ Dual-write for safety
```

---

## Example: Complete Data Flow

### User Starts Deep Research

```
1. POST /api/research
   ↓
2. Create Session object (in-memory)
   ├─ session_id = UUID
   ├─ status = "running"
   └─ Store in: sessions[session_id]
   ↓
3. Start Phase 1: Identify
   ├─ Create Checkpoint
   ├─ Create StepResult
   └─ Update Session.progress_percent = 10
   ↓
4. Emit: phase_complete event
   ├─ Call: session.events.append(event)
   ├─ Clients receive via SSE
   └─ Checkpoint saved to ~/.finagent/state/session_uuid.json
   ↓
5. Run Phases 2-8 similarly
   ↓
6. Final: Synthesis phase
   ├─ Generate markdown memo
   ├─ Extract MemoryFacts
   ├─ Extract Citations
   ├─ Save memo to ~/.finagent/memos/session_uuid.md
   └─ Save facts to ~/.finagent/memory/entity_TICKER.json
   ↓
7. Mark session as complete
   ├─ session.status = "complete"
   ├─ session.completed_at = now()
   ├─ Final checkpoint saved
   └─ Delete from sessions dict (archive to disk)
   ↓
8. Emit: research_complete event
   ├─ Include: memo_url, quality_score, time, sources_used
   └─ Client redirects to memo view
```

---

## Performance Characteristics

### File System Performance

| Operation | Typical Time | Bottleneck |
|-----------|--------------|-----------|
| Write checkpoint | 50-200ms | Disk I/O |
| Read checkpoint | 20-50ms | Disk I/O |
| Recall facts | 100-500ms | Keyword matching |
| Write memo | 100-300ms | File size |

### Database Performance (Future)

| Operation | Typical Time | Bottleneck |
|-----------|--------------|-----------|
| Insert fact | 5-20ms | Network latency |
| Query facts | 10-50ms | Index lookup |
| Bulk insert | 1-5s | Batch overhead |

---

## Security Considerations

### Data Sensitivity

- **Session data:** Not sensitive (research queries, not personal)
- **Memory facts:** Public company data (not sensitive)
- **Citations:** URLs to public sources (not sensitive)
- **Future:** User data will need encryption at rest

### Access Control (Future)

```python
# When user auth is added:

async def get_user_sessions(user_id: str):
	"""Only retrieve user's own sessions."""
	path = "~/.finagent/state"
	user_sessions = []

	for session_file in Path(path).glob("session_*.json"):
		data = json.load(open(session_file))
		if data.get('user_id') == user_id:
			user_sessions.append(data)

	return user_sessions
```

---

**Last Updated:** May 21, 2026  
**Next Migration Target:** PostgreSQL + Supabase  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence

