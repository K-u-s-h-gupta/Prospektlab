# 🏗️ ProspektLab Complete Architecture - Step-by-Step Guide

**Version:** 3.0.0 - Ultimate Reference  
**Last Updated:** May 21, 2026  
**Target Audience:** Developers, Architects, DevOps Engineers  
**Total Coverage:** 15,000+ words with 50+ examples

---

## 📑 Table of Contents

1. [System Overview](#system-overview)
2. [Frontend Architecture](#frontend-architecture)
3. [Backend Architecture](#backend-architecture)
4. [Web Search Pipeline](#web-search-pipeline)
5. [Research Engine (FinAgent)](#research-engine-finagent)
6. [Multi-Agent Orchestration](#multi-agent-orchestration)
7. [Data Flow & Integration](#data-flow--integration)
8. [Database & State Management](#database--state-management)
9. [Deployment Architecture](#deployment-architecture)
10. [API Reference with Examples](#api-reference-with-examples)
11. [Performance & Scalability](#performance--scalability)
12. [Security Model](#security-model)
13. [Troubleshooting Guide](#troubleshooting-guide)

---

## 🎯 System Overview

### What is ProspektLab?

ProspektLab is a **next-generation financial intelligence platform** that combines:
- **Quick Chat** for instant financial questions (ORACLE FIOS)
- **Deep Research** for comprehensive investment analysis (FinAgent)
- **Multi-Agent AI** for domain-specific expertise
- **Real-time Web Search** with source ranking
- **Fact Verification** to reduce hallucinations

### System Goals

| Goal | How Achieved | Example |
|------|--------------|---------|
| **Speed** | LangGraph + MCP microservices | "What's TCS PE ratio?" → 5 seconds |
| **Accuracy** | Verification phase + source ranking | Conflicts detected, confidence scored |
| **Coverage** | 4 search engines + 15 data sources | NSE, SEC, Yahoo, Wikipedia, Reddit |
| **Authority** | Domain tier system (1-8) | Regulatory sources prioritized over tweets |
| **Transparency** | Citation tracking + memory facts | Each claim linked to source |

### Architecture Layers

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 0: Users (Web, Mobile)                                │
└──────────────────┬───────────────────────────────────────────┘
				   │ HTTPS
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 1: Frontend (Next.js + React)                         │
│  - Chat interface, real-time streaming, chart rendering      │
└──────────────────┬───────────────────────────────────────────┘
				   │ HTTP/REST + SSE
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 2: API Gateway (AWS ALB)                              │
│  - HTTPS termination, routing, load balancing                │
└──────────────────┬───────────────────────────────────────────┘
				   │ Internal network
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 3A: ORACLE Chat API (FastAPI)                         │
│  - Quick responses, intent routing, LangGraph orchestration   │
└──────────────────┬───────────────────────────────────────────┘
				   │
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 3B: FinAgent Research API (FastAPI)                   │
│  - Deep research, 8-phase pipeline, SSE streaming            │
└──────────────────┬───────────────────────────────────────────┘
				   │
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 4: Core Services                                      │
│  ├─ Multi-agent orchestration                                │
│  ├─ Web search (4 engines)                                   │
│  ├─ Data retrieval (15+ sources)                             │
│  ├─ Analysis & verification                                  │
│  └─ Memory & state management                                │
└──────────────────┬───────────────────────────────────────────┘
				   │
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 5: MCP Microservices (5 services)                     │
│  ├─ NSE India (8001)                                         │
│  ├─ Fundamentals (8002)                                      │
│  ├─ Research (8003)                                          │
│  ├─ Docs/Filings (8004)                                      │
│  └─ Valuation (8005)                                         │
└──────────────────┬───────────────────────────────────────────┘
				   │
┌──────────────────▼───────────────────────────────────────────┐
│  Layer 6: External Data Sources                              │
│  ├─ NSE API, SEC EDGAR, Yahoo Finance                        │
│  ├─ Wikipedia, News APIs, Social Media                       │
│  └─ Web search engines (DDG, Bing, Firecrawl)                │
└──────────────────────────────────────────────────────────────┘
```

---

## 🎨 Frontend Architecture

### Directory Structure

```
Frontend/
├── app/                          # Next.js app directory
│   ├── page.tsx                  # Main chat interface
│   ├── layout.tsx                # Root layout
│   ├── globals.css               # Global styles
│   └── api/                      # API routes (optional)
│
├── _components/                  # Reusable components
│   ├── ChatInterface.tsx         # Message input + display
│   ├── MessageBubble.tsx         # Single message component
│   ├── RichOutput/
│   │   ├── Charts.tsx            # Candlestick, line, bar charts
│   │   ├── Tables.tsx            # Data table with sorting
│   │   ├── Gauge.tsx             # Circular gauge charts
│   │   └── Memo.tsx              # Markdown memo renderer
│   ├── AgentVisualization.tsx    # Show which agents ran
│   ├── Loading.tsx               # Progress spinner
│   └── StreamingIndicator.tsx    # Real-time update badge
│
├── hooks/                        # Custom React hooks
│   ├── useChat.ts                # Chat state + API calls
│   ├── useSSE.ts                 # Server-Sent Events wrapper
│   └── useLocalStorage.ts        # Persist conversations
│
├── styles/                       # Tailwind/CSS
│   └── tailwind.config.js
│
├── public/                       # Static assets
│   └── icons/
│
├── package.json
├── tsconfig.json
├── next.config.js
└── README.md
```

### Key Components Explained

#### 1. ChatInterface Component

**File:** `Frontend/app/page.tsx`

```typescript
'use client'
import React, { useState, useRef, useEffect } from 'react'
import { useChat } from '@/hooks/useChat'
import { useSSE } from '@/hooks/useSSE'
import MessageBubble from '@/_components/MessageBubble'
import RichOutput from '@/_components/RichOutput'
import AgentVisualization from '@/_components/AgentVisualization'

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to latest message
  useEffect(() => {
	messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSendMessage = async () => {
	if (!input.trim()) return

	// Add user message to UI immediately
	const userMessage: Message = {
	  id: Date.now().toString(),
	  role: 'user',
	  content: input,
	  timestamp: new Date(),
	}
	setMessages(prev => [...prev, userMessage])
	setInput('')
	setIsLoading(true)

	try {
	  // POST to /api/chat
	  const response = await fetch('/api/chat', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({
		  message: input,
		  mode: 'research',  // or 'marathon'
		  conversation_id: 'session-123',
		}),
	  })

	  const data = await response.json()

	  // Add assistant message with rich output
	  const assistantMessage: Message = {
		id: Date.now().toString(),
		role: 'assistant',
		content: data.reply,
		richOutput: data.rich,
		agentsUsed: data.agents_used,
		citations: data.citations,
		timestamp: new Date(),
	  }
	  setMessages(prev => [...prev, assistantMessage])
	} catch (error) {
	  console.error('Chat error:', error)
	  // Show error message
	  setMessages(prev => [...prev, {
		id: Date.now().toString(),
		role: 'system',
		content: 'Error: Could not get response',
		timestamp: new Date(),
	  }])
	} finally {
	  setIsLoading(false)
	}
  }

  return (
	<div className="flex flex-col h-screen bg-gradient-to-b from-slate-900 to-slate-800">
	  {/* Header */}
	  <header className="border-b border-slate-700 bg-slate-800/50 backdrop-blur px-6 py-4">
		<h1 className="text-2xl font-bold text-white">ProspektLab</h1>
		<p className="text-sm text-slate-400">Financial Intelligence Platform</p>
	  </header>

	  {/* Messages Container */}
	  <div className="flex-1 overflow-y-auto px-6 py-8 space-y-4">
		{messages.map((msg) => (
		  <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
			<div className={`max-w-2xl ${
			  msg.role === 'user'
				? 'bg-blue-600 text-white rounded-lg px-4 py-3'
				: 'bg-slate-700 text-slate-100 rounded-lg px-4 py-3'
			}`}>
			  <MessageBubble message={msg} />

			  {/* Rich Output (Charts, Tables) */}
			  {msg.richOutput && (
				<div className="mt-4 border-t border-slate-600 pt-4">
				  <RichOutput data={msg.richOutput} />
				</div>
			  )}

			  {/* Agents Used */}
			  {msg.agentsUsed && msg.agentsUsed.length > 0 && (
				<div className="mt-2 pt-2 border-t border-slate-600">
				  <AgentVisualization agents={msg.agentsUsed} />
				</div>
			  )}

			  {/* Citations */}
			  {msg.citations && msg.citations.length > 0 && (
				<div className="mt-2 text-xs text-slate-400">
				  <p className="font-semibold">Sources:</p>
				  <ul className="list-disc list-inside">
					{msg.citations.map((cit, idx) => (
					  <li key={idx}>
						<a href={cit.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
						  {cit.source}
						</a>
					  </li>
					))}
				  </ul>
				</div>
			  )}
			</div>
		  </div>
		))}
		<div ref={messagesEndRef} />
	  </div>

	  {/* Input Area */}
	  <footer className="border-t border-slate-700 bg-slate-800/50 backdrop-blur px-6 py-4">
		<div className="flex gap-3">
		  <input
			type="text"
			value={input}
			onChange={(e) => setInput(e.target.value)}
			onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
			placeholder="Ask about stocks, companies, market trends..."
			className="flex-1 bg-slate-700 text-white px-4 py-2 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
			disabled={isLoading}
		  />
		  <button
			onClick={handleSendMessage}
			disabled={isLoading || !input.trim()}
			className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-6 py-2 rounded-lg font-semibold transition"
		  >
			{isLoading ? 'Thinking...' : 'Send'}
		  </button>
		</div>
	  </footer>
	</div>
  )
}
```

**Flow Explanation:**
1. User types message in input field
2. Click "Send" → `handleSendMessage()` triggered
3. Message added to UI immediately (optimistic update)
4. POST to `/api/chat` with message content
5. Backend returns `ChatResponse` with reply + rich output
6. Display response with charts, tables, agents used, citations

#### 2. Rich Output Components

**Charts Component Example:**

```typescript
// _components/RichOutput/Charts.tsx
import React from 'react'
import { LineChart, Line, CandlestickChart, XAxis, YAxis } from 'recharts'

export function LineChartComponent({ data, title }: { data: any[]; title: string }) {
  return (
	<div className="bg-slate-800 p-4 rounded-lg">
	  <h3 className="text-white font-semibold mb-4">{title}</h3>
	  <LineChart width={600} height={300} data={data}>
		<XAxis dataKey="date" />
		<YAxis />
		<Line type="monotone" dataKey="price" stroke="#3b82f6" />
	  </LineChart>
	</div>
  )
}

// Candlestick chart for OHLC data
export function CandlestickChartComponent({ data, title }: { data: any[]; title: string }) {
  return (
	<div className="bg-slate-800 p-4 rounded-lg">
	  <h3 className="text-white font-semibold mb-4">{title}</h3>
	  {/* TradingView-like candlestick implementation */}
	  <div className="overflow-x-auto">
		{data.map((candle, idx) => (
		  <div key={idx} className="inline-block mr-1">
			{/* Render candle */}
			<svg width="30" height="200">
			  {/* High-Low line */}
			  <line x1="15" y1={computeY(candle.high)} x2="15" y2={computeY(candle.low)} stroke="white" />
			  {/* Open-Close rectangle */}
			  <rect
				x="8"
				y={computeY(Math.max(candle.open, candle.close))}
				width="14"
				height={Math.abs(computeY(candle.close) - computeY(candle.open))}
				fill={candle.close >= candle.open ? '#10b981' : '#ef4444'}
			  />
			</svg>
		  </div>
		))}
	  </div>
	</div>
  )
}
```

**Table Component Example:**

```typescript
// _components/RichOutput/Tables.tsx
export function DataTable({ columns, rows, title }: DataTableProps) {
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSort = (col: string) => {
	if (sortBy === col) {
	  setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
	} else {
	  setSortBy(col)
	  setSortDir('asc')
	}
  }

  // Sort rows
  const sortedRows = sortBy
	? [...rows].sort((a, b) => {
		const aVal = a[sortBy]
		const bVal = b[sortBy]
		const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
		return sortDir === 'asc' ? cmp : -cmp
	  })
	: rows

  return (
	<div className="bg-slate-800 p-4 rounded-lg overflow-x-auto">
	  <h3 className="text-white font-semibold mb-4">{title}</h3>
	  <table className="w-full text-sm text-slate-300">
		<thead className="border-b border-slate-600">
		  <tr>
			{columns.map((col) => (
			  <th
				key={col}
				onClick={() => handleSort(col)}
				className="text-left px-4 py-2 cursor-pointer hover:bg-slate-700 font-semibold"
			  >
				{col} {sortBy === col && (sortDir === 'asc' ? '↑' : '↓')}
			  </th>
			))}
		  </tr>
		</thead>
		<tbody>
		  {sortedRows.map((row, idx) => (
			<tr key={idx} className="border-b border-slate-700 hover:bg-slate-750">
			  {columns.map((col) => (
				<td key={col} className="px-4 py-2">
				  {typeof row[col] === 'number' ? row[col].toFixed(2) : row[col]}
				</td>
			  ))}
			</tr>
		  ))}
		</tbody>
	  </table>
	</div>
  )
}
```

#### 3. Server-Sent Events Hook

```typescript
// hooks/useSSE.ts
export function useSSE(eventSourceURL: string, onMessage: (data: any) => void) {
  useEffect(() => {
	const eventSource = new EventSource(eventSourceURL)

	eventSource.onopen = () => console.log('SSE connection opened')

	eventSource.addEventListener('phase_start', (event) => {
	  const data = JSON.parse(event.data)
	  onMessage({ type: 'phase_start', data })
	})

	eventSource.addEventListener('phase_complete', (event) => {
	  const data = JSON.parse(event.data)
	  onMessage({ type: 'phase_complete', data })
	})

	eventSource.addEventListener('research_complete', (event) => {
	  const data = JSON.parse(event.data)
	  onMessage({ type: 'research_complete', data })
	  eventSource.close()
	})

	eventSource.onerror = (error) => {
	  console.error('SSE error:', error)
	  eventSource.close()
	}

	return () => eventSource.close()
  }, [eventSourceURL, onMessage])
}

// Usage in component
const ResearchPage = () => {
  const [progress, setProgress] = useState(0)
  const [currentPhase, setCurrentPhase] = useState('')

  useSSE(`/api/session/${sessionId}/events`, (event) => {
	if (event.type === 'phase_start') {
	  setCurrentPhase(event.data.phase)
	} else if (event.type === 'phase_complete') {
	  setProgress(event.data.progress)
	} else if (event.type === 'research_complete') {
	  // Show memo
	}
  })

  return (
	<div>
	  <h2>Research Progress: {currentPhase}</h2>
	  <progress value={progress} max="100" />
	  <span>{progress}%</span>
	</div>
  )
}
```

### Frontend Deployment

**Configuration:** `Frontend/next.config.js`

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // Optimize for production
  compress: true,
  swcMinify: true,

  // Environment variables
  env: {
	NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000',
  },

  // Image optimization
  images: {
	domains: ['api.example.com'],
  },
}

module.exports = nextConfig
```

**Deployment to AWS Amplify:**

```yaml
# amplify.yml
version: 1
env:
  variables:
	NEXT_PUBLIC_API_BASE: https://api.prospektlab.com
	NODE_OPTIONS: --max-old-space-size=4096

frontend:
  phases:
	# Install dependencies
	preBuild:
	  commands:
		- npm ci
	# Build Next.js
	build:
	  commands:
		- npm run build
  # Output directory
  artifacts:
	baseDirectory: .next
	files:
	  - '**/*'
  # Cache node_modules
  cache:
	paths:
	  - node_modules/**/*

# Custom domain (optional)
customRules:
  - source: /<*>
	target: /index.html
	status: 200
```

---

## 🚀 Backend Architecture

### Directory Structure

```
Backend/
├── api.py                        # FastAPI main entrypoint (703 lines)
├── graph.py                      # LangGraph orchestration
├── intent.py                     # Query intent classification
├── rich_builder.py               # Output formatting
├── mcp_config.py                 # MCP service clients
├── requirements.txt              # Python dependencies
└── README.md

finagent/
├── api.py                        # FinAgent API (152 lines)
├── run_agent.py                  # Research pipeline (2000 lines)
├── __init__.py
├── agents/                       # Multi-agent system
│   ├── orchestrator.py           # Coordinates agents
│   ├── verifier.py               # Fact verification
│   └── specialists/
│       ├── accounting.py         # Accounting analysis
│       ├── competitive.py        # Competitive analysis
│       ├── governance.py         # Board analysis
│       └── valuation.py          # Valuation analysis
├── tools/
│   ├── web/                      # Web search & scraping
│   │   ├── search.py             # Search wrappers
│   │   ├── scraper.py            # Main scraping logic
│   │   └── http_fetcher.py       # HTTP + robots.txt
│   ├── data/                     # Data models & APIs
│   │   ├── models.py             # 50+ Pydantic models
│   │   ├── data_sources/         # Data source clients
│   │   └── indicators.py         # Technical indicators
│   └── mcp/                      # MCP service clients
│       ├── nse_india.py
│       ├── fundamentals.py
│       ├── research.py
│       ├── docs.py
│       └── valuation.py
├── memory/                       # Long-term memory
│   ├── store.py                  # Fact storage
│   └── chat_memory.py            # Conversation history
├── state/                        # State management
│   ├── checkpoint.py             # Phase checkpoints
│   └── citation_log.py           # Citation tracking
├── synthesis/                    # Memo generation
│   └── synthesize_memo.py        # Markdown synthesis
├── geo/                          # Entity resolution
│   ├── entity_resolver.py        # Ticker lookup
│   └── query_localizer.py        # Geography context
├── analysis/                     # Post-research analysis
│   ├── conflicts.py              # Conflict detection
│   └── quality.py                # Research scoring
├── gateway/                      # Standalone gateway
│   ├── run.py                    # FastAPI gateway (1657 lines)
│   └── widget.html               # Embedded widget
└── events.py                     # Event bus for streaming
```

### 1. Backend API (FastAPI)

**File:** `Backend/api.py` (703 lines)

```python
"""
ORACLE FIOS FastAPI Backend
- Quick chat endpoint
- Intent-based routing
- LangGraph orchestration
- Streaming responses
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import json
import logging

from Backend.graph import build_graph
from Backend.intent import classify_intent
from Backend.rich_builder import build_rich_output

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────

GRAPH_RUN_TIMEOUT_SECONDS = 240  # 4 minutes max
GRAPH_IDLE_TIMEOUT_SECONDS = 90
GRAPH_REBUILD_COOLDOWN_SECONDS = 5

CORS_ORIGINS = [
	"http://localhost:3000",
	"http://localhost:3001",
	"https://prospektlab.com",
	"https://www.prospektlab.com",
]

# ────────────────────────────────────────────────────────────
# Data Models
# ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
	"""Request model for /api/chat endpoint"""
	message: str = Field(..., min_length=1, max_length=1000, description="User query")
	mode: str = Field(default="research", regex="^(research|marathon)$", description="Response mode")
	conversation_id: Optional[str] = Field(None, description="Session ID for context")

	class Config:
		example = {
			"message": "What is the PE ratio of TCS?",
			"mode": "research",
			"conversation_id": "session-123"
		}

class ChatResponse(BaseModel):
	"""Response model for /api/chat endpoint"""
	reply: str = Field(..., description="Main response text")
	agents_used: list[str] = Field(default_factory=list, description="Agents that processed query")
	rich: Optional[dict] = Field(None, description="Rich output (charts, tables, etc)")
	output_mode: Optional[str] = Field(None, description="narrative|chart|table")
	response_depth: Optional[str] = Field(None, description="shallow|medium|deep")
	citations: list[dict] = Field(default_factory=list, description="Sources used")

	class Config:
		example = {
			"reply": "TCS has a PE ratio of 24.5, which is...",
			"agents_used": ["fundamentals_agent", "valuation_agent"],
			"rich": {
				"type": "metric_card",
				"data": {"label": "PE Ratio", "value": 24.5, "change": "+2.1%"}
			},
			"citations": [
				{"source": "NSE", "url": "https://nseindia.com", "confidence": 0.95}
			]
		}

# ────────────────────────────────────────────────────────────
# FastAPI Application
# ────────────────────────────────────────────────────────────

app = FastAPI(
	title="ORACLE FIOS API",
	description="Financial Intelligence Operating System",
	version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
	CORSMiddleware,
	allow_origins=CORS_ORIGINS,
	allow_credentials=True,
	allow_methods=["GET", "POST", "OPTIONS"],
	allow_headers=["*"],
)

# Global graph instance (cached)
_graph = None
_graph_lock = asyncio.Lock()

async def get_graph():
	"""Get or build LangGraph with caching"""
	global _graph
	if _graph is None:
		async with _graph_lock:
			if _graph is None:
				logger.info("Building LangGraph for first time...")
				_graph = await build_graph()
	return _graph

# ────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["System"])
async def health_check():
	"""Health check endpoint"""
	return {
		"status": "healthy",
		"service": "ORACLE FIOS",
		"version": "1.0.0",
		"timestamp": datetime.now().isoformat(),
	}

@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
	"""
	Main chat endpoint

	Flow:
	1. Validate input
	2. Classify intent
	3. Route to appropriate agents
	4. Execute LangGraph
	5. Format output
	6. Return response

	Example:
	```
	POST /api/chat
	{
	  "message": "What are TCS's latest financials?",
	  "mode": "research"
	}

	Response:
	{
	  "reply": "TCS Q3 FY25 results...",
	  "agents_used": ["fundamentals_agent"],
	  "rich": {...},
	  "citations": [...]
	}
	```
	"""
	try:
		# Step 1: Validate input
		message = request.message.strip()
		if not message:
			raise HTTPException(status_code=400, detail="Message cannot be empty")

		logger.info(f"Chat request: {message[:100]}...")

		# Step 2: Classify intent
		intent = await classify_intent(message)
		logger.info(f"Classified intent: {intent}")

		# Step 3: Get LangGraph
		graph = await get_graph()

		# Step 4: Run graph with timeout
		logger.info(f"Running graph for {request.mode} mode...")
		try:
			state = await asyncio.wait_for(
				graph.ainvoke(
					{
						"messages": [{"role": "user", "content": message}],
						"intent": intent,
						"mode": request.mode,
					},
					timeout=GRAPH_RUN_TIMEOUT_SECONDS
				),
				timeout=GRAPH_RUN_TIMEOUT_SECONDS
			)
		except asyncio.TimeoutError:
			logger.error("Graph execution timed out")
			return ChatResponse(
				reply="Request timed out. Please try a simpler query.",
				agents_used=["timeout_handler"],
			)

		# Step 5: Extract response
		final_message = state["messages"][-1]["content"] if state["messages"] else ""
		agents_used = state.get("agents_used", [])

		# Step 6: Build rich output
		rich_output = await build_rich_output(
			intent=intent,
			state=state,
			mode=request.mode
		)

		# Step 7: Build response
		response = ChatResponse(
			reply=final_message,
			agents_used=agents_used,
			rich=rich_output,
			citations=state.get("citations", []),
		)

		logger.info(f"Chat response successful")
		return response

	except Exception as e:
		logger.exception("Chat endpoint error")
		raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents", tags=["System"])
async def list_agents():
	"""List available agents"""
	return {
		"agents": [
			{"name": "fundamentals_agent", "description": "Financial ratios and metrics"},
			{"name": "valuation_agent", "description": "Valuation models and fair value"},
			{"name": "news_agent", "description": "Recent news and sentiment"},
			{"name": "competitor_agent", "description": "Competitive analysis"},
		]
	}

@app.options("/api/chat")
async def chat_options():
	"""CORS preflight for chat endpoint"""
	return {}

# ────────────────────────────────────────────────────────────
# Error Handlers
# ────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
	return {
		"error": exc.detail,
		"status_code": exc.status_code,
	}

# ────────────────────────────────────────────────────────────
# Startup/Shutdown
# ────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
	logger.info("ORACLE FIOS starting up...")
	# Pre-build graph on startup
	await get_graph()
	logger.info("Graph built successfully")

@app.on_event("shutdown")
async def shutdown_event():
	logger.info("ORACLE FIOS shutting down...")

if __name__ == "__main__":
	import uvicorn
	uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Key Features:**
- ✅ Pydantic validation (request/response)
- ✅ CORS middleware
- ✅ Timeout protection (240s)
- ✅ Error handling
- ✅ Logging
- ✅ Health check endpoint
- ✅ Agent listing endpoint

**Running the backend:**

```bash
# Development
uvicorn Backend.api:app --reload --host 0.0.0.0 --port 8000

# Production
gunicorn -w 4 -k uvicorn.workers.UvicornWorker Backend.api:app --bind 0.0.0.0:8000
```

### 2. Intent Classification

**File:** `Backend/intent.py`

```python
"""
Intent classification to route queries to appropriate agents
"""

from enum import Enum
from typing import Optional
import re
import logging

logger = logging.getLogger(__name__)

class Intent(Enum):
	"""Query intent types"""
	VALUATION_METRICS = "valuation_metrics"         # PE, PB, ROE, etc
	FUNDAMENTAL_ANALYSIS = "fundamental_analysis"   # Revenue, profit, growth
	TECHNICAL_ANALYSIS = "technical_analysis"       # Price, volume, charts
	NEWS_SENTIMENT = "news_sentiment"               # Recent news, sentiment
	COMPETITOR_COMPARISON = "competitor_comparison" # vs other companies
	INVESTMENT_THESIS = "investment_thesis"         # Bull/bear case
	DIVIDEND_ANALYSIS = "dividend_analysis"         # Dividend, payout
	RISK_ASSESSMENT = "risk_assessment"             # Volatility, downsides
	MARKET_CONTEXT = "market_context"               # Sector, index, macro
	OTHER = "other"                                 # Unknown

async def classify_intent(query: str) -> Intent:
	"""
	Classify user query into intent category

	Examples:
	- "What is TCS's PE ratio?" → VALUATION_METRICS
	- "How is TCS performing vs Infosys?" → COMPETITOR_COMPARISON
	- "Should I buy TCS?" → INVESTMENT_THESIS
	- "What's the dividend yield?" → DIVIDEND_ANALYSIS
	"""

	query_lower = query.lower()

	# Define keyword patterns for each intent
	patterns = {
		Intent.VALUATION_METRICS: [
			r'\b(pe|p/e|price.to.earnings|pb|p/b|roe|roa|debt.?to.?equity)\b',
			r'\b(valuation|valued at|worth)\b',
			r'\b(multiple|ratio)\b',
		],
		Intent.FUNDAMENTAL_ANALYSIS: [
			r'\b(revenue|sales|profit|earnings|ebitda|fcf|margin)\b',
			r'\b(financial|quarter|quarterly|annual|fy\d+)\b',
			r'\b(performance|results|growth)\b',
		],
		Intent.TECHNICAL_ANALYSIS: [
			r'\b(price|chart|candlestick|moving.average|rsi|macd)\b',
			r'\b(volume|high|low|open|close|trend)\b',
			r'\b(support|resistance|breakout)\b',
		],
		Intent.NEWS_SENTIMENT: [
			r'\b(news|headlines|sentiment|buzz|talk)\b',
			r'\b(latest|recent|today|yesterday)\b',
			r'\b(said|announced|reported)\b',
		],
		Intent.COMPETITOR_COMPARISON: [
			r'\b(vs|versus|compared to|compare with)\b',
			r'\b(competitor|peer|rival|alternative)\b',
			r'\b(better|worse|outperform)\b',
		],
		Intent.DIVIDEND_ANALYSIS: [
			r'\b(dividend|payout|yield|dps)\b',
			r'\b(distribution|pay-out)\b',
		],
		Intent.RISK_ASSESSMENT: [
			r'\b(risk|volatility|downside|exposure|concern)\b',
			r'\b(should i|should we|worth it)\b',
		],
	}

	# Count pattern matches
	scores = {}
	for intent, pattern_list in patterns.items():
		match_count = 0
		for pattern in pattern_list:
			match_count += len(re.findall(pattern, query_lower))
		scores[intent] = match_count

	# Return highest scoring intent
	max_score = max(scores.values())
	if max_score > 0:
		for intent, score in scores.items():
			if score == max_score:
				logger.info(f"Intent classified as: {intent.value} (score: {score})")
				return intent

	# Default to other if no matches
	logger.info(f"Intent not recognized, defaulting to OTHER")
	return Intent.OTHER
```

**Example Usage:**

```python
# Test intent classification
query1 = "What is TCS's PE ratio?"
intent1 = await classify_intent(query1)
# Output: Intent.VALUATION_METRICS

query2 = "How is TCS performing vs Infosys?"
intent2 = await classify_intent(query2)
# Output: Intent.COMPETITOR_COMPARISON

query3 = "Latest news on TCS"
intent3 = await classify_intent(query3)
# Output: Intent.NEWS_SENTIMENT
```

### 3. LangGraph Orchestration

**File:** `Backend/graph.py` (simplified)

```python
"""
LangGraph orchestration for multi-agent chat

Architecture:
- Supervisor node: routes to appropriate agents
- Agent nodes: execute domain-specific tasks
- Tool nodes: call external APIs (MCP)
"""

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic
from typing import TypedDict, Annotated, Optional
import json

# ────────────────────────────────────────────────────────────
# State Definition
# ────────────────────────────────────────────────────────────

class GraphState(TypedDict):
	"""State shared across all nodes"""
	messages: Annotated[list, "Conversation messages"]
	intent: "Intent"  # Classified intent
	current_agent: Optional[str]
	agents_used: list[str]
	citations: list[dict]
	is_complete: bool

# ────────────────────────────────────────────────────────────
# Agent Tools
# ────────────────────────────────────────────────────────────

async def get_company_data(ticker: str) -> dict:
	"""Fetch company data from MCP service"""
	# Call MCP Fundamentals service
	result = await mcp_client.call_tool(
		"get_company_data",
		{"ticker": ticker}
	)
	return result

async def search_web(query: str, limit: int = 5) -> list[dict]:
	"""Search web for query"""
	from finagent.tools.web.scraper import search_web
	results = await search_web(query, max_results=limit)
	return [{"title": r.title, "url": r.final_url, "excerpt": r.excerpt} for r in results]

# ────────────────────────────────────────────────────────────
# Node: Supervisor
# ────────────────────────────────────────────────────────────

async def supervisor_node(state: GraphState) -> GraphState:
	"""
	Supervisor node that routes to appropriate agents

	Decision logic:
	- VALUATION_METRICS → Fundamentals Agent
	- NEWS_SENTIMENT → News Agent
	- COMPETITOR_COMPARISON → Multiple agents
	- etc.
	"""

	intent = state.get("intent")
	messages = state.get("messages", [])

	# Create system prompt for supervisor
	supervisor_prompt = f"""
	You are a financial analyst supervisor. Route the user query to the best agent.

	Available agents:
	- fundamentals_agent: Financial metrics, ratios, company data
	- news_agent: Latest news and sentiment
	- valuation_agent: Valuation models, fair value
	- competitor_agent: Competitive analysis

	Query intent: {intent}
	User message: {messages[-1]['content'] if messages else ''}

	Respond in JSON format:
	{{"agent": "agent_name", "reason": "why this agent"}}
	"""

	# Call LLM to decide
	llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
	response = await llm.ainvoke([{"role": "user", "content": supervisor_prompt}])

	# Parse response
	try:
		decision = json.loads(response.content)
		agent_name = decision["agent"]
		state["current_agent"] = agent_name
	except:
		agent_name = "fundamentals_agent"  # Default

	return state

# ────────────────────────────────────────────────────────────
# Node: Fundamentals Agent
# ────────────────────────────────────────────────────────────

async def fundamentals_agent_node(state: GraphState) -> GraphState:
	"""Execute fundamentals analysis"""

	messages = state.get("messages", [])
	user_message = messages[-1]["content"]

	# Extract ticker from message
	ticker = extract_ticker(user_message)

	if not ticker:
		return state

	# Get company data
	data = await get_company_data(ticker)

	# Add to messages
	tool_result = {
		"role": "tool",
		"content": f"Company data for {ticker}: {json.dumps(data, indent=2)}"
	}
	state["messages"].append(tool_result)
	state["agents_used"].append("fundamentals_agent")
	state["citations"].append({
		"source": "NSE",
		"confidence": 0.95
	})

	return state

# ────────────────────────────────────────────────────────────
# Node: LLM Responder (Final)
# ────────────────────────────────────────────────────────────

async def llm_responder_node(state: GraphState) -> GraphState:
	"""Generate final response using LLM"""

	llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")

	# Create context
	context = f"""
	You are a financial expert assistant. Based on the company data provided,
	give a concise, accurate response to the user's query.

	Agents used: {', '.join(state['agents_used'])}
	"""

	# Call LLM
	messages = state["messages"]
	system_message = {"role": "system", "content": context}
	response = await llm.ainvoke([system_message] + messages)

	# Add response
	state["messages"].append({
		"role": "assistant",
		"content": response.content
	})
	state["is_complete"] = True

	return state

# ────────────────────────────────────────────────────────────
# Build Graph
# ────────────────────────────────────────────────────────────

async def build_graph():
	"""Build and return LangGraph"""

	workflow = StateGraph(GraphState)

	# Add nodes
	workflow.add_node("supervisor", supervisor_node)
	workflow.add_node("fundamentals_agent", fundamentals_agent_node)
	workflow.add_node("llm_responder", llm_responder_node)

	# Add edges
	workflow.set_entry_point("supervisor")
	workflow.add_edge("supervisor", "fundamentals_agent")
	workflow.add_edge("fundamentals_agent", "llm_responder")
	workflow.add_edge("llm_responder", END)

	# Compile
	graph = workflow.compile()
	return graph
```

**Flow Diagram:**

```
User Query
	↓
Supervisor Node (route decision)
	├─ VALUATION_METRICS → Fundamentals Agent
	├─ NEWS_SENTIMENT → News Agent
	├─ COMPETITOR → Competitor Agent
	└─ OTHER → Default Agent
	↓
Selected Agent (execute)
	├─ Fetch data
	├─ Analyze
	└─ Update state
	↓
LLM Responder (generate response)
	├─ Read messages + tool results
	├─ Generate natural language
	└─ Return response
	↓
Response to User
```

---

## 🔍 Web Search Pipeline

### Complete Search Example

**Scenario:** User asks "What's the latest news about TCS acquisition?"

```
1. QUERY PARSING
   Input: "What's the latest news about TCS acquisition?"
   ↓
   Entity extracted: TCS (Tata Consultancy Services)
   Intent: NEWS_SENTIMENT
   Ticker: TCS / TATA CONSULTANCY SERVICES / 532540

2. SEARCH EXPANSION
   Layered queries generated:
   ├─ Query 1: "TCS SEC filing 10-K acquisition"
   ├─ Query 2: "TCS investor relations M&A"
   ├─ Query 3: "TCS acquisition news latest"
   └─ Query 4: "TCS acquisition competitors market"

3. PARALLEL MULTI-ENGINE SEARCH

   For Query 1: "TCS SEC filing 10-K acquisition"
   ├─ Firecrawl.search() [Primary]
   │  ├─ Result 1: SEC filing on acquisition strategy
   │  ├─ Result 2: Management discussion
   │  └─ Result 3: Risk factors (acquisition related)
   │
   ├─ Tavily.search() [Secondary]
   │  ├─ Result 1: Financial Times article
   │  ├─ Result 2: Reuters report
   │  └─ Result 3: Analyst note
   │
   ├─ DuckDuckGo.search() [Fallback 1]
   │  ├─ Result 1: TCS annual report
   │  ├─ Result 2: Business Insider article
   │  └─ Result 3: Stock discussion forum
   │
   └─ Bing.search() [Fallback 2]
	  ├─ Result 1: Economic Times article
	  ├─ Result 2: Money Control news
	  └─ Result 3: Bloomberg report

   (All 4 engines run in PARALLEL, not sequential)

   MERGE RESULTS:
   ├─ Firecrawl results: 3 docs (with full content)
   ├─ Tavily results: 2 new docs (not in Firecrawl)
   ├─ DDG results: 2 new docs
   ├─ Bing results: 1 new doc
   └─ Total unique: 8 results

4. ROBOT.TXT COMPLIANCE CHECK
   For each URL:
   ├─ Check robots.txt cache
   ├─ If miss: fetch robots.txt (non-blocking)
   ├─ Verify can_fetch("*", url)
   └─ If blocked: skip (or note in blocked_reason)

   Example:
   ├─ nseindia.com/... → ✓ Allowed
   ├─ ir.tcs.com/... → ✓ Allowed (identified host)
   ├─ sec.gov/... → ✓ Allowed (identified bypass)
   ├─ somesite.com/robots.txt → Disallow * → ✗ Skip
   └─ anonymized-site.com → No robots.txt → ✓ Allowed

5. CONCURRENT HTTP FETCHING
   For each allowed URL (8 URLs, parallel fetch):

   URL 1: nseindia.com/data/tcs-news
   ├─ User-Agent: Rotate from pool
   ├─ httpx.get(url) → 200 OK
   ├─ Extract title & text
   ├─ Domain tier: 1 (Regulatory)
   └─ ScrapedDoc created

   URL 2: ir.tcs.com/announcements/acquisition
   ├─ User-Agent: Identified UA (SEC policy)
   ├─ httpx.get(url) → 200 OK
   ├─ Extract title & text
   ├─ Domain tier: 2 (Company IR)
   └─ ScrapedDoc created

   URL 3: javascript-heavy-site.com/news
   ├─ httpx.get(url) → Timeout/fail
   ├─ Retry with Playwright browser
   ├─ Page renders with JavaScript
   ├─ Extract content after render
   ├─ Domain tier: 5 (General web)
   └─ ScrapedDoc created

   (All 8 fetches concurrent using asyncio.as_completed())

6. HTML PARSING
   For each fetched page:

   Page 1: SEC Filing (prefer narrative)
   Input HTML:
   ```html
   <html>
	 <head><title>TCS Acquisition Strategy 2024</title></head>
	 <body>
	   <script>...</script>
	   <div class="header">XBRL Metadata: ...</div>
	   <div class="content">
		 "TCS announced today the acquisition of..."
	   </div>
	 </body>
   </html>
   ```

   Process:
   ├─ Remove <script>, <style>, <noscript>
   ├─ Extract title: "TCS Acquisition Strategy 2024"
   ├─ Extract text (prefer_narrative=True for SEC)
   │  ├─ Walk through sentences
   │  ├─ Skip low-alpha sentences (metadata)
   │  ├─ Keep narrative-rich sentences
   │  └─ Return first 1200 chars
   ├─ Result: "TCS announced today the acquisition of..."
   └─ ScrapedDoc.excerpt = "TCS announced today..."

7. DEDUPLICATION BY FINAL URL
   Across all 4 queries (32 raw results):
   ├─ seen_urls = {}
   ├─ For each result:
   │  ├─ Normalize: remove fragments (#...)
   │  ├─ Check if in seen_urls
   │  ├─ If new: add to unique_docs
   │  └─ If duplicate: skip
   └─ Final unique: 15 docs (removed 17 duplicates)

8. DOMAIN TIER RANKING
   Sort 15 docs by domain tier:

   Tier 1 (Regulatory):
   ├─ nseindia.com: "TCS acquisition announced"
   └─ sec.gov: "Form 8-K filing"

   Tier 2 (Company IR):
   ├─ ir.tcs.com: "Management announcement"
   └─ investor.tcs.com: "Investor briefing"

   Tier 3 (Financial Research):
   ├─ screener.in: "TCS acquisition analysis"
   ├─ trendlyne.com: "TCS deal impact"
   └─ tickertape.in: "Investment perspective"

   Tier 4 (Financial News):
   ├─ moneycontrol.com: "TCS to acquire..."
   ├─ economictimes.com: "TCS acquisition news"
   ├─ livemint.com: "What TCS acquisition means"
   └─ thehindubusinessline.com: "Strategic move analyzed"

   Tier 5 (General Web):
   ├─ medium.com: "TCS acquisition insights"
   └─ linkedin.com: "TCS acquisition commentary"

   (Tier 8 social media filtered out for this query)

9. RERANKING BY PREFERRED DOMAINS
   If preferred_domains = ["ir.tcs.com", "sec.gov"]:
   ├─ Move preferred domains to top
   ├─ Keep tier-based order for others
   └─ Result:
	  1. ir.tcs.com (preferred)
	  2. sec.gov (preferred)
	  3. nseindia.com (tier 1)
	  4. screener.in (tier 3)
	  5. moneycontrol.com (tier 4)
	  ...

10. CACHING
	Query cache store:
	├─ Key: "What's the latest news about TCS acquisition?"
	└─ Value: [ScrapedDoc, ScrapedDoc, ..., ScrapedDoc]

	Future identical query → Instant return from cache

11. RETURN TO FINAGENT
	Return 15 ScrapedDoc objects:
	```python
	[
		ScrapedDoc(
			url="https://ir.tcs.com/...",
			final_url="https://ir.tcs.com/...",
			domain="ir.tcs.com",
			tier=2,
			title="TCS Announces Acquisition of...",
			excerpt="TCS announced today the acquisition of...",
			text_len=4532,
			status=200,
			via="httpx",
			is_social=False
		),
		# ... 14 more docs
	]
	```

12. DOWNSTREAM USAGE IN FINAGENT
	These 15 docs are used for:
	├─ Extracting facts (phase 5: Analysis)
	├─ Fact-checking (phase 7: Verification)
	├─ Citation tracking (phase 8: Synthesis)
	├─ Memory storage (long-term recall)
	└─ Memo generation (final report)
```

**Total time for this search:** ~15-25 seconds
- Search engines (parallel): 2-3 seconds
- robots.txt checks: 1-2 seconds
- HTTP fetches (8 parallel): 5-10 seconds
- HTML parsing (8 serial): 2-3 seconds
- Reranking & dedup: <1 second

---

## 🤖 Research Engine (FinAgent)

### 8-Phase Research Pipeline

**File:** `finagent/run_agent.py` (2000 lines)

#### Phase 1: IDENTIFY

**Objective:** Resolve entity from user query to canonical form

```python
# Phase 1: IDENTIFY
# Input: "What's TCS doing?"
# Output: ResolvedEntity(ticker="TCS", isin="INE467B01029", exchange="NSE", ...)

async def phase_identify(query: str, session_id: str) -> ResolvedEntity:
	"""
	Entity resolution step

	Example:
	Input query: "Is Infosys a good investment?"
	├─ Extract: "Infosys"
	├─ Lookup in ticker database
	├─ Resolve to: ticker="INFY", ISIN="INE009A01021", exchange="NSE"
	├─ Canonical name: "Infosys Limited"
	└─ Return: ResolvedEntity(...)

	Another example:
	Input query: "What about Apple iPhone sales?"
	├─ Extract: "Apple"
	├─ Ambiguous: could be Apple Inc (US), Apple Hospitality (India), etc
	├─ Disambiguate: check context, user history, default to largest cap
	├─ Resolve to: ticker="AAPL", ISIN="US0378331005", exchange="NASDAQ"
	└─ Return: ResolvedEntity(...)
	"""

	from finagent.geo.entity_resolver import resolve_entity

	# Extract entity
	entity_name = extract_entity_from_query(query)

	# Resolve
	entity = await resolve_entity(entity_name)

	if not entity:
		# Try web search as fallback
		search_results = await search_web(entity_name, max_results=1)
		if search_results:
			entity = parse_entity_from_search(search_results[0])

	# Log
	BUS.emit(session_id, "phase", phase="identify", 
			 result=entity.dict() if entity else None)

	return entity

# Example entity resolver
async def resolve_entity(name: str) -> ResolvedEntity | None:
	"""
	Resolve entity name to structured data

	Database lookup:
	"TCS" → ResolvedEntity(
		ticker="TCS",
		isin="INE467B01029",
		exchange="NSE",
		legal_name="Tata Consultancy Services Limited",
		sector="IT",
		market_cap=3500000000000,  # ₹35 lakhs crore
		...
	)
	"""

	# Try exact match
	entity = entity_db.get(name.upper())
	if entity:
		return entity

	# Try fuzzy match
	candidates = entity_db.fuzzy_search(name, limit=1)
	if candidates:
		return candidates[0]

	return None
```

**Time:** 5-10 seconds

#### Phase 2: ENRICHMENT

**Objective:** Fetch baseline data from multiple sources in parallel

```python
# Phase 2: ENRICHMENT
# Input: ResolvedEntity(ticker="TCS")
# Output: EnrichmentBundle with data from 4 sources

@dataclass
class EnrichmentBundle:
	"""Enrichment data from multiple sources"""
	nse: NSESnapshot | None              # Latest price, volume, market cap
	yahoo: YahooSnapshot | None          # Historical data, splits, dividends
	wiki: WikiSnapshot | None            # Company overview
	news: list[NewsItem]                 # Recent news (5-10 items)

async def phase_enrichment(entity: ResolvedEntity, session_id: str) -> EnrichmentBundle:
	"""
	Parallel enrichment from multiple sources

	Example for TCS:
	├─ NSE API call
	│  └─ Returns: price=₹3250, volume=2.3M, market_cap=₹35L Cr
	├─ Yahoo Finance call
	│  └─ Returns: historical OHLC data, PE ratio, dividend yield
	├─ Wikipedia call
	│  └─ Returns: company overview, history, operations
	└─ News aggregator call
	   └─ Returns: ["TCS Q3 results beat expectations", "TCS wins new contract"]

	All run concurrently (not sequential)
	"""

	# Create tasks
	nse_task = fetch_nse_data(entity.ticker)
	yahoo_task = fetch_yahoo_data(entity.ticker)
	wiki_task = fetch_wiki_data(entity.legal_name)
	news_task = fetch_news_headlines(entity.legal_name)

	# Wait for all (parallel)
	nse_data, yahoo_data, wiki_data, news_data = await asyncio.gather(
		nse_task, yahoo_task, wiki_task, news_task,
		return_exceptions=True
	)

	# Build bundle
	bundle = EnrichmentBundle(
		nse=nse_data if not isinstance(nse_data, Exception) else None,
		yahoo=yahoo_data if not isinstance(yahoo_data, Exception) else None,
		wiki=wiki_data if not isinstance(wiki_data, Exception) else None,
		news=news_data if not isinstance(news_data, Exception) else [],
	)

	BUS.emit(session_id, "phase", phase="enrichment",
			 nse_price=bundle.nse.price if bundle.nse else None,
			 news_count=len(bundle.news))

	return bundle

# Example NSE fetch
async def fetch_nse_data(ticker: str) -> NSESnapshot:
	"""
	Fetch latest data from NSE API

	Example response:
	{
		"symbol": "TCS",
		"price": 3250.50,
		"high": 3260.00,
		"low": 3240.00,
		"volume": 2300000,
		"market_cap": 3500000000000,
		"pe_ratio": 24.5,
		"roe": 12.3,
		"dividend_yield": 1.85,
		...
	}
	"""

	# Call MCP NSE service
	response = await mcp_client.call_tool(
		url="http://localhost:8001/mcp",
		method="tools/call",
		params={
			"name": "get_snapshot",
			"arguments": {"ticker": ticker}
		}
	)

	return NSESnapshot(**response)
```

**Time:** 20-30 seconds (parallel, so max of any single API)

#### Phase 3: BREADTH SURVEY

**Objective:** Multi-angle web search (4 angles × 5 results = 20 documents)

```python
# Phase 3: BREADTH SURVEY
# Input: Entity = "TCS"
# Output: 20 ScrapedDoc from web search

async def phase_breadth_survey(
	entity: ResolvedEntity,
	session_id: str
) -> list[ScrapedDoc]:
	"""
	Layered web search from 4 angles

	Angles:
	1. Regulatory/Filing angle: "TCS SEC filing 10-K"
	   → Finds: Annual reports, regulatory filings, official disclosures

	2. Company IR angle: "TCS investor relations"
	   → Finds: Company announcements, presentations, investor briefings

	3. Performance angle: "TCS earnings transcript"
	   → Finds: Quarterly results, management commentary, guidance

	4. Competitive angle: "TCS competitors market share"
	   → Finds: Industry analysis, competitive positioning, benchmarks
	"""

	from finagent.tools.web.scraper import search_layered

	# Define 4 angles
	queries = [
		f"{entity.legal_name} SEC filing 10-K",
		f"{entity.legal_name} investor relations",
		f"{entity.legal_name} earnings transcript",
		f"{entity.legal_name} competitors market share",
	]

	# Run layered search
	docs = await search_layered(
		target=entity.legal_name,
		queries=queries,
		per_query=5,
		preferred_domains=["ir.tcs.com", "sec.gov", "nseindia.com"],
		on_query=lambda q, status, count: BUS.emit(
			session_id, "query", query=q, status=status, count=count
		),
		entity=entity,
	)

	BUS.emit(session_id, "phase", phase="breadth-survey",
			 docs_found=len(docs))

	return docs
```

**Time:** 30-60 seconds (4 parallel queries × 2-5s each search engine)

#### Phase 4: DEEP DIVE

**Objective:** Identify gaps and do targeted follow-up searches

```python
# Phase 4: DEEP DIVE
# Input: Results from breadth survey
# Output: Gap-filling research documents

async def phase_deep_dive(
	breadth_docs: list[ScrapedDoc],
	entity: ResolvedEntity,
	session_id: str
) -> list[ScrapedDoc]:
	"""
	Analyze breadth results for gaps and search again

	Example gap detection:
	Breadth survey found:
	├─ Financial data (2024 full year)
	├─ Competitive analysis (2024)
	├─ Management commentary (Q3 2024)
	└─ But MISSING: Growth projects, pipeline, R&D spending

	→ Generate targeted queries:
	   1. "TCS growth projects 2024 2025"
	   2. "TCS R&D spending innovation"
	   3. "TCS upcoming client wins pipeline"

	→ Search again to fill gaps
	"""

	# Analyze breadth results for coverage
	coverage = analyze_coverage(breadth_docs)

	# Identify gaps
	gaps = identify_gaps(coverage, entity)

	# Generate targeted queries
	targeted_queries = generate_gap_queries(gaps, entity)

	# Search for each gap
	gap_docs = []
	for query in targeted_queries:
		docs = await search_web(
			query,
			max_results=3,
			entity=entity,
		)
		gap_docs.extend(docs)
		BUS.emit(session_id, "query", query=query, 
				 status="done", count=len(docs))

	BUS.emit(session_id, "phase", phase="deep-dive",
			 gap_queries=len(targeted_queries),
			 gap_docs=len(gap_docs))

	return gap_docs

# Example gap detection
def analyze_coverage(docs: list[ScrapedDoc]) -> dict:
	"""Analyze what topics are covered"""
	topics_covered = set()
	for doc in docs:
		if re.search(r'revenue|sales|earnings', doc.text_len, re.I):
			topics_covered.add('financials')
		if re.search(r'competitor|peer|rival', doc.excerpt, re.I):
			topics_covered.add('competition')
		if re.search(r'growth|expand|future', doc.excerpt, re.I):
			topics_covered.add('growth')
		# ...
	return {
		'covered_topics': topics_covered,
		'coverage_score': len(topics_covered) / 10,  # 0-1
	}

def identify_gaps(coverage: dict, entity: ResolvedEntity) -> list[str]:
	"""Identify missing topics"""
	essential_topics = {'financials', 'competition', 'growth', 'risks', 'management'}
	covered = coverage['covered_topics']
	gaps = essential_topics - covered
	return list(gaps)
```

**Time:** 30-45 seconds

#### Phase 5: ANALYSIS

**Objective:** Conflict detection and data quality scoring

```python
# Phase 5: ANALYSIS
# Input: All collected data (breadth + deep dive)
# Output: Conflict report, quality score

async def phase_analysis(
	all_docs: list[ScrapedDoc],
	entity: ResolvedEntity,
	session_id: str
) -> AnalysisResult:
	"""
	Multi-source conflict detection

	Example conflicts:
	Source 1 (NSE): "TCS revenue FY25: ₹200,000 Cr"
	Source 2 (Reuters): "TCS revenue FY25: $24.1B"  ← Different currency
	Source 3 (Wikipedia): "TCS revenue FY24: ₹190,000 Cr"

	Conflicts detected:
	├─ Source 1 vs Source 2: Same data (currency adjusted)
	├─ Source 1 vs Source 3: Different fiscal years (FY25 vs FY24)
	└─ Conflict score: 0 (no real conflict, just different years)

	Another example:
	Source 1: "TCS acquired ABC Company for $500M"
	Source 2: "TCS acquired ABC Company for $450M"
	Conflict score: 0.6 (conflicting valuations)
	"""

	from finagent.analysis.conflicts import detect_conflicts
	from finagent.analysis.quality import score_research

	# Extract facts
	facts = extract_facts_from_docs(all_docs)

	# Detect conflicts
	conflicts = await detect_conflicts(facts)

	# Score research quality
	quality_score = await score_research(
		facts=facts,
		conflicts=conflicts,
		sources_count=len(all_docs),
		coverage=analyze_coverage(all_docs),
	)

	BUS.emit(session_id, "phase", phase="analysis",
			 conflicts_found=len(conflicts),
			 quality_score=quality_score)

	return AnalysisResult(
		facts=facts,
		conflicts=conflicts,
		quality_score=quality_score,
	)

# Example conflict detection
async def detect_conflicts(facts: list[Fact]) -> list[Conflict]:
	"""
	Detect conflicting facts

	Conflict types:
	1. Direct conflict: Same claim, different values
	2. Temporal conflict: Different time periods
	3. Ambiguity: Unclear which is correct
	"""

	conflicts = []

	# Group facts by topic
	facts_by_topic = {}
	for fact in facts:
		topic = fact.topic  # "revenue", "profit", "acquisition", etc
		if topic not in facts_by_topic:
			facts_by_topic[topic] = []
		facts_by_topic[topic].append(fact)

	# Check each topic for conflicts
	for topic, topic_facts in facts_by_topic.items():
		if len(topic_facts) <= 1:
			continue

		# Compare pairwise
		for i, fact1 in enumerate(topic_facts):
			for fact2 in topic_facts[i+1:]:
				if conflicting(fact1, fact2):
					conflicts.append(Conflict(
						fact1=fact1,
						fact2=fact2,
						severity=compute_severity(fact1, fact2),
						resolution=try_resolve(fact1, fact2),
					))

	return conflicts
```

**Time:** 15-20 seconds

#### Phase 6: SPECIALIST ANALYSIS (Parallel)

**Objective:** Run 4 specialist agents in parallel

```python
# Phase 6: SPECIALIST ANALYSIS
# Input: All collected data
# Output: 4 specialist reports

@dataclass
class SpecialistReport:
	specialist: str  # "accounting", "competitive", "governance", "valuation"
	analysis: str
	key_findings: list[str]
	confidence_score: float
	timestamps: datetime

async def phase_specialist_analysis(
	data: dict,
	entity: ResolvedEntity,
	session_id: str
) -> dict[str, SpecialistReport]:
	"""
	Run 4 specialist agents in parallel

	Specialists:
	1. Accounting Specialist
	   - Forensic accounting analysis
	   - Red flag detection (earnings manipulation, accounting tricks)
	   - Ratio analysis

	2. Competitive Specialist
	   - Market position analysis
	   - SWOT analysis
	   - Competitive advantages/disadvantages

	3. Governance Specialist
	   - Board composition
	   - Promoter changes
	   - Management quality assessment

	4. Valuation Specialist
	   - DCF model
	   - Comparable company valuation
	   - Fair value estimate
	"""

	from finagent.agents.specialists import (
		AccountingSpecialist,
		CompetitiveSpecialist,
		GovernanceSpecialist,
		ValuationSpecialist
	)

	# Create specialist tasks
	accounting_task = AccountingSpecialist().analyze(data, entity)
	competitive_task = CompetitiveSpecialist().analyze(data, entity)
	governance_task = GovernanceSpecialist().analyze(data, entity)
	valuation_task = ValuationSpecialist().analyze(data, entity)

	# Run all in parallel
	results = await asyncio.gather(
		accounting_task,
		competitive_task,
		governance_task,
		valuation_task,
		return_exceptions=True
	)

	# Combine results
	reports = {
		'accounting': results[0] if not isinstance(results[0], Exception) else None,
		'competitive': results[1] if not isinstance(results[1], Exception) else None,
		'governance': results[2] if not isinstance(results[2], Exception) else None,
		'valuation': results[3] if not isinstance(results[3], Exception) else None,
	}

	BUS.emit(session_id, "phase", phase="specialist-analysis",
			 accounting_confidence=reports['accounting'].confidence_score if reports['accounting'] else 0,
			 valuation_score=reports['valuation'].key_findings if reports['valuation'] else [])

	return reports

# Example: Accounting Specialist
class AccountingSpecialist:
	async def analyze(self, data: dict, entity: ResolvedEntity) -> SpecialistReport:
		"""
		Example analysis for TCS:

		Input financial data:
		├─ Revenue: ₹200,000 Cr
		├─ Profit after tax: ₹40,000 Cr
		├─ Operating cash flow: ₹45,000 Cr
		├─ Capex: ₹8,000 Cr
		└─ Free cash flow: ₹37,000 Cr

		Analysis:
		1. Earnings quality
		   - Cash profit vs Accounting profit
		   - OCF/Net Income = 45k/40k = 1.125 (very good)
		   - Indicates high quality earnings

		2. Red flags
		   - Check for: Channel stuffing, aggressive revenue recognition
		   - Check: Increase in receivables vs sales growth
		   - No major red flags found

		3. Ratios
		   - ROE = Net Income / Equity = 40k / 100k = 40%
		   - ROA = Net Income / Assets = 40k / 150k = 26.7%
		   - Both exceptional (industry avg: 15-20%)

		Verdict: Strong, clean financials
		"""

		# Extract financial metrics
		financials = extract_financials(data)

		# Perform forensic checks
		red_flags = await self.check_red_flags(financials)

		# Calculate ratios
		ratios = self.calculate_ratios(financials)

		# Generate analysis
		analysis = f"""
		## Accounting Analysis for {entity.legal_name}

		### Earnings Quality
		Operating Cash Flow / Net Income: {ratios['ocf_to_ni']:.2f}
		Interpretation: {'Excellent' if ratios['ocf_to_ni'] > 1 else 'Good' if ratios['ocf_to_ni'] > 0.8 else 'Caution'}

		### Key Metrics
		ROE: {ratios['roe']:.1f}%
		ROA: {ratios['roa']:.1f}%

		### Red Flags
		{', '.join(red_flags) if red_flags else 'None detected'}

		### Verdict
		Financials quality: {'Strong' if not red_flags else 'Caution'}
		"""

		return SpecialistReport(
			specialist="accounting",
			analysis=analysis,
			key_findings=red_flags or ["Strong earnings quality"],
			confidence_score=0.92,
			timestamps=datetime.now(),
		)
```

**Time:** 60-120 seconds (parallel, so max of any single specialist)

#### Phase 7: VERIFICATION

**Objective:** Fact-check all claims

```python
# Phase 7: VERIFICATION
# Input: All claims from phases 1-6
# Output: Verification report

async def phase_verification(
	facts: list[Fact],
	specialist_reports: dict,
	session_id: str
) -> VerificationResult:
	"""
	Verifier agent fact-checks all claims

	Process:
	1. Extract all claims
	2. For each claim, verify against sources
	3. Score confidence
	4. Flag unverifiable claims

	Example verification:
	Claim: "TCS revenue in FY25 is ₹200,000 Cr"
	├─ Verification: Found in official filing (NSE)
	├─ Cross-check: Investor relations confirms same
	├─ Confidence score: 0.99
	└─ Status: VERIFIED

	Claim: "TCS will grow 15% next year"
	├─ Verification: Not explicitly stated anywhere
	├─ Source: Only in analyst speculation forums
	├─ Confidence score: 0.35
	└─ Status: UNVERIFIABLE (speculation)
	"""

	from finagent.agents.verifier import Verifier

	verifier = Verifier()

	# Extract all claims
	all_claims = extract_all_claims(facts, specialist_reports)

	# Verify each claim
	verifications = []
	for claim in all_claims:
		verification = await verifier.verify_claim(claim)
		verifications.append(verification)
		BUS.emit(session_id, "verification", claim=claim.text[:100],
				 confidence=verification.confidence)

	# Aggregate results
	result = VerificationResult(
		total_claims=len(all_claims),
		verified=len([v for v in verifications if v.is_verified]),
		unverifiable=len([v for v in verifications if not v.is_verified]),
		average_confidence=sum(v.confidence for v in verifications) / len(verifications),
	)

	BUS.emit(session_id, "phase", phase="verification",
			 verified_count=result.verified,
			 confidence=result.average_confidence)

	return result
```

**Time:** 30-45 seconds

#### Phase 8: SYNTHESIS

**Objective:** Generate final markdown memo

```python
# Phase 8: SYNTHESIS
# Input: All phase results
# Output: Markdown memo

async def phase_synthesis(
	all_data: dict,
	entity: ResolvedEntity,
	quality_score: float,
	session_id: str
) -> Memo:
	"""
	Generate comprehensive research memo

	Output format:

	# {Company Name} - Investment Analysis

	**Research Date:** 2024-05-21
	**Quality Score:** 92/100
	**Recommendation:** BUY (5/5 confidence)

	## Executive Summary
	- Company overview
	- Key investment thesis
	- Valuation summary

	## Financial Overview
	- Key metrics table
	- Charts (revenue trend, profitability)

	## Business Analysis
	- Markets and segments
	- Competitive position
	- Growth drivers

	## Valuation Analysis
	- Fair value estimate
	- DCF analysis
	- Comparable company valuation

	## Risk Assessment
	- Key risks
	- Mitigation factors

	## Conclusion
	- Investment recommendation
	- Key catalysts
	- Time horizon

	## References [1-50]
	- [1] NSE filing - link
	- [2] Reuters report - link
	- ...
	"""

	from finagent.synthesis.synthesize_memo import Synthesizer

	synthesizer = Synthesizer()

	# Generate memo
	memo_markdown = await synthesizer.synthesize(
		company=entity.legal_name,
		data=all_data,
		quality_score=quality_score,
	)

	# Save to disk
	memo_path = await save_memo(memo_markdown, session_id)

	# Extract memory facts
	memory_facts = extract_memory_facts_from_memo(memo_markdown)

	# Store in long-term memory
	await store_facts(memory_facts, entity, session_id)

	BUS.emit(session_id, "phase", phase="synthesis",
			 memo_path=memo_path,
			 memory_facts_count=len(memory_facts))

	return Memo(
		path=memo_path,
		markdown=memo_markdown,
		entities=[entity],
		quality_score=quality_score,
		created_at=datetime.now(),
	)
```

**Time:** 15-30 seconds

### Complete 8-Phase Timeline

```
Phase 1: Identify        [████░░░░░░░░░░░░░░░] 5-10s
Phase 2: Enrichment      [████████░░░░░░░░░░░] 20-30s
Phase 3: Breadth Survey  [████████████░░░░░░░] 30-60s
Phase 4: Deep Dive       [████████████░░░░░░░] 30-45s
Phase 5: Analysis        [██████░░░░░░░░░░░░░] 15-20s
Phase 6: Specialists     [████████████░░░░░░░] 60-120s
Phase 7: Verification    [████████░░░░░░░░░░░] 30-45s
Phase 8: Synthesis       [██████░░░░░░░░░░░░░] 15-30s
────────────────────────────────────────────────────
Total Research Time:     ~3-5 minutes

Critical path (bottleneck): Specialist Analysis (Phase 6)
```

---

## 🔄 Multi-Agent Orchestration

### LangGraph Architecture

```python
from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic

# ────────────────────────────────────────────────────────
# Agents Definition
# ────────────────────────────────────────────────────────

class ResearchAgent:
	"""Base agent class"""

	def __init__(self, name: str, tools: list):
		self.name = name
		self.tools = tools
		self.llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")

	async def invoke(self, state: dict) -> dict:
		"""Execute agent"""
		pass

class FundamentalsAgent(ResearchAgent):
	"""Analyzes financial metrics"""

	async def invoke(self, state: dict) -> dict:
		"""Get fundamentals data"""
		# Tool calls: get_pe_ratio, get_revenue, get_margins, etc
		pass

class CompetitorAgent(ResearchAgent):
	"""Competitive analysis"""

	async def invoke(self, state: dict) -> dict:
		"""Compare with competitors"""
		pass

class NewsAgent(ResearchAgent):
	"""Latest news and sentiment"""

	async def invoke(self, state: dict) -> dict:
		"""Search and summarize news"""
		pass

# ────────────────────────────────────────────────────────
# Graph Construction
# ────────────────────────────────────────────────────────

async def build_research_graph():
	"""Build multi-agent orchestration graph"""

	workflow = StateGraph(ResearchState)

	# Add agents as nodes
	fundamentals_agent = FundamentalsAgent(name="fundamentals", tools=[...])
	competitor_agent = CompetitorAgent(name="competitor", tools=[...])
	news_agent = NewsAgent(name="news", tools=[...])

	workflow.add_node("fundamentals", fundamentals_agent.invoke)
	workflow.add_node("competitor", competitor_agent.invoke)
	workflow.add_node("news", news_agent.invoke)

	# Add supervisor for routing
	workflow.add_node("supervisor", supervisor_node)

	# Add LLM responder
	workflow.add_node("responder", responder_node)

	# Define edges
	workflow.set_entry_point("supervisor")

	# Supervisor routes to agents
	workflow.add_conditional_edges(
		"supervisor",
		lambda x: x["next_agent"],
		{
			"fundamentals": "fundamentals",
			"competitor": "competitor",
			"news": "news",
		}
	)

	# Agents go to responder
	workflow.add_edge("fundamentals", "responder")
	workflow.add_edge("competitor", "responder")
	workflow.add_edge("news", "responder")

	# Responder to end
	workflow.add_edge("responder", END)

	return workflow.compile()
```

---

## 💾 Database & State Management

### State Persistence

```python
# ~/.finagent/state/
session-uuid-12345/
├── checkpoint.json          # Phase snapshots
├── memory_facts.json        # Extracted facts
├── citations.json           # Source citations
├── memo.md                  # Generated memo
└── metadata.json            # Session metadata

# checkpoint.json example
{
  "session_id": "session-uuid-12345",
  "phases": {
	"identify": {
	  "result": {"ticker": "TCS", "isin": "INE467B01029", ...},
	  "progress": 10,
	  "elapsed_seconds": 5
	},
	"enrichment": {
	  "result": {"nse": {...}, "yahoo": {...}, "wiki": {...}, "news": [...]},
	  "progress": 25,
	  "elapsed_seconds": 25
	},
	...
	"synthesis": {
	  "result": {"memo_path": "/path/to/memo.md", ...},
	  "progress": 100,
	  "elapsed_seconds": 300
	}
  },
  "status": "complete",
  "quality_score": 92,
  "created_at": "2024-05-21T15:30:00Z",
  "updated_at": "2024-05-21T15:35:00Z"
}
```

---

## 🚀 Deployment Architecture

### AWS Infrastructure

```yaml
# Architecture Overview
ProspektLab on AWS:

VPC (Virtual Private Cloud)
├─ Public Subnet
│  ├─ NAT Gateway (for outbound internet)
│  └─ Route Table
└─ Private Subnet
   ├─ ECS Cluster
   │  ├─ Task: Backend API (FastAPI)
   │  ├─ Task: MCP NSE Service
   │  ├─ Task: MCP Fundamentals Service
   │  ├─ Task: MCP Research Service
   │  ├─ Task: MCP Docs Service
   │  └─ Task: MCP Valuation Service
   └─ Route Table

Route53 (DNS)
├─ api.prospektlab.com → ALB
└─ www.prospektlab.com → CloudFront

CloudFront (CDN)
├─ Origins:
│  ├─ S3 (frontend static files)
│  └─ ALB (API requests)
└─ Cache behaviors

ALB (Application Load Balancer)
├─ HTTPS listener (443)
│  ├─ SSL certificate (ACM)
│  └─ Target group → ECS tasks
└─ HTTP listener (80) → HTTPS redirect

RDS (Relational Database Service) [Future]
├─ PostgreSQL instance
├─ Multi-AZ failover
└─ Automated backups

S3 (Simple Storage Service)
├─ Frontend assets (Next.js build)
├─ Research memos
└─ Backups

ECR (Elastic Container Registry)
├─ backend:latest
├─ mcp-nse:latest
├─ mcp-fundamentals:latest
└─ mcp-services:latest

CloudWatch (Monitoring)
├─ Logs (application logs)
├─ Metrics (CPU, memory, latency)
└─ Alarms (anomalies)
```

### Deployment Steps

```bash
# 1. Build Docker image
docker build -t prospektlab-backend:latest -f Dockerfile .

# 2. Push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789.dkr.ecr.us-east-1.amazonaws.com
docker tag prospektlab-backend:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/prospektlab-backend:latest
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/prospektlab-backend:latest

# 3. Update ECS service
aws ecs update-service \
  --cluster prospektlab-cluster \
  --service backend-service \
  --force-new-deployment

# 4. Monitor deployment
aws ecs describe-services \
  --cluster prospektlab-cluster \
  --services backend-service
```

---

## 📡 API Reference with Examples

### POST /api/chat

**Request:**
```bash
curl -X POST https://api.prospektlab.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{
	"message": "What is the PE ratio of TCS?",
	"mode": "research",
	"conversation_id": "session-123"
  }'
```

**Response:**
```json
{
  "reply": "TCS has a PE ratio of 24.5, which is moderate compared to the IT sector average of 22. This suggests TCS is trading at a fair valuation given its strong fundamentals and consistent growth.",
  "agents_used": ["fundamentals_agent", "valuation_agent"],
  "rich": {
	"type": "metric_card",
	"data": {
	  "label": "PE Ratio",
	  "value": 24.5,
	  "change": "+2.1%",
	  "chart": {
		"type": "line",
		"history": [
		  {"date": "2024-01-01", "value": 23.8},
		  {"date": "2024-02-01", "value": 24.0},
		  {"date": "2024-03-01", "value": 24.5}
		]
	  }
	}
  },
  "citations": [
	{
	  "source": "NSE",
	  "url": "https://nseindia.com/market-data/live-equity-market",
	  "confidence": 0.95,
	  "date": "2024-05-21"
	},
	{
	  "source": "TCS Investor Relations",
	  "url": "https://ir.tcs.com",
	  "confidence": 0.92,
	  "date": "2024-05-15"
	}
  ]
}
```

### POST /api/research

**Request:**
```bash
curl -X POST https://api.prospektlab.com/api/research \
  -H "Content-Type: application/json" \
  -d '{
	"query": "Deep analysis of TCS as an investment",
	"depth": "deep"
  }'
```

**Response (202 Accepted):**
```json
{
  "session_id": "research-session-abc123",
  "status": "running",
  "events_url": "https://api.prospektlab.com/api/session/research-session-abc123/events",
  "progress": 0,
  "created_at": "2024-05-21T15:30:00Z"
}
```

### GET /api/session/{session_id}/events (SSE)

**Stream Events:**
```
event: phase_start
data: {"phase": "identify", "timestamp": "2024-05-21T15:30:05Z"}

event: phase_complete
data: {"phase": "identify", "progress": 10, "result": {...}}

event: phase_start
data: {"phase": "enrichment", "timestamp": "2024-05-21T15:30:10Z"}

event: query
data: {"query": "TCS SEC filing", "status": "running", "count": 0}

event: query
data: {"query": "TCS SEC filing", "status": "done", "count": 5}

event: phase_complete
data: {"phase": "enrichment", "progress": 25}

... (more events) ...

event: research_complete
data: {"session_id": "research-session-abc123", "memo_url": "/session/research-session-abc123/memo", "quality_score": 92}
```

### GET /api/session/{session_id}/memo

**Response:**
```markdown
# TCS (Tata Consultancy Services) - Investment Analysis

**Research Date:** May 21, 2024  
**Quality Score:** 92/100  
**Recommendation:** BUY | Target Price: ₹3,500

## Executive Summary

TCS is India's largest IT services company with strong fundamentals and consistent growth. The company benefits from a diverse client base, operational excellence, and recurring revenue streams.

**Investment Thesis:**
- Strong fundamentals with 15-20% CAGR over 5 years
- Attractive valuation at 24.5x PE vs sector average 22x
- High dividend yield of 1.85%
- Competitive advantages in digital transformation

**Key Metrics:**
| Metric | Value | YoY Change |
|--------|-------|-----------|
| Revenue | ₹200,000 Cr | +12% |
| Profit | ₹40,000 Cr | +15% |
| ROE | 40% | Stable |
| Dividend Yield | 1.85% | +0.2% |

## Financial Analysis

### Revenue Trend
[Chart showing revenue growth trend]

### Profitability
- Operating margin: 20.5% (strong)
- Net margin: 20% (industry-leading)
- ROE: 40% (exceptional)

... [Full analysis continues] ...

## Risks

- **Geopolitical Risk:** US hiring slowdown could impact 60% of revenue
- **Competition:** Increasing competition from Indian and global peers
- **Currency Volatility:** 70% revenue in USD-exposed to INR depreciation

## Conclusion

TCS presents an attractive investment opportunity at current valuations with strong growth prospects and market-leading position.

## References

[1] NSE Market Data - https://nseindia.com
[2] TCS Q3 FY25 Results - https://ir.tcs.com
... [50+ references] ...
```

---

## 📊 Performance & Scalability

### Benchmarks

```
Operation                  | Time | Bottleneck
---------------------------|------|------------------
Chat Query (simple)         | 5-10s | Intent classification
Deep Research               | 2-5m  | Specialist analysis (Phase 6)
Web Search (4 engines)      | 10-30s| HTTP fetching
Single MCP call             | 1-3s  | Network latency
Memory Fact Recall          | <1s   | Database lookup
HTML Parsing (N=20)         | 2-3s  | BeautifulSoup processing
```

### Scalability Strategies

**1. Horizontal Scaling**
```
Load: 100 users/minute
Current capacity: 2 ECS tasks × 50 req/task = 100 req/minute ✓

Load: 500 users/minute
Needed: 2 → 10 ECS tasks
ALB auto-scaling: min=2, target=5, max=10
```

**2. Caching**
```
Query Cache (in-memory):
├─ Hit rate: ~40% (repeated queries)
├─ Speedup: 10-20x faster
└─ Memory: ~100MB for 1000 queries

Results Cache (Redis):
├─ TTL: 24 hours
├─ Hit rate: ~30%
└─ Cost: Minimal (key-value store)
```

**3. Database Optimization**
```
Indexes on:
├─ ticker (for quick lookup)
├─ created_at (for time-based queries)
└─ quality_score (for sorting)

Partitioning:
├─ By date (old data → archive)
├─ By entity type
└─ By quality score
```

---

## 🔐 Security Model

### Current Protections

✅ CORS validation  
✅ Rate limiting (100 req/min per IP)  
✅ Input validation (Pydantic)  
✅ API key in environment  
✅ HTTPS (ALB termination)  
✅ Timeout protection  

### Future Enhancements

⏳ JWT authentication  
⏳ Per-user API keys  
⏳ Per-user quotas  
⏳ Encryption at rest  
⏳ Audit logging  
⏳ WAF rules  

---

## 🛠️ Troubleshooting Guide

### Issue: Chat endpoint returns 500

**Diagnosis:**
```bash
# Check backend logs
docker logs backend-container | grep ERROR

# Check LangGraph
Check if graph.py imported correctly
Check if MCP services are running
```

**Common causes:**
- MCP service down → restart MCP container
- API key missing → set OPENAI_API_KEY
- Timeout → increase GRAPH_RUN_TIMEOUT_SECONDS

### Issue: Research takes >5 minutes

**Diagnosis:**
```bash
# Check which phase is slow
tail -f ~/.finagent/logs/research.log | grep "Phase"

# Check web search
Monitor search engine responses
```

**Common causes:**
- Phase 6 (Specialists) slow → reduce specialist count or timeout
- Web search slow → increase timeout or reduce per_query limit
- HTTP fetches slow → enable browser fallback for JS-heavy sites

---

## 🎓 Summary

This complete architecture guide covers:

✅ **Frontend:** Next.js with React, real-time streaming, charts & tables  
✅ **Backend:** FastAPI with LangGraph orchestration  
✅ **Web Search:** 4-engine parallel search with tier-based ranking  
✅ **Research Engine:** 8-phase pipeline for deep analysis  
✅ **Multi-Agent:** Specialists for accounting, competitive, governance, valuation  
✅ **Data Flow:** End-to-end request processing with examples  
✅ **Deployment:** AWS ECS/Fargate with auto-scaling  
✅ **Performance:** Benchmarks and scalability strategies  
✅ **Security:** Current protections and roadmap  

**Total System Complexity:** Enterprise-grade with 5000+ lines of code  
**Time to Deploy:** ~2 hours on AWS  
**Monthly Cost:** ~$1,000 (compute + storage + APIs)

