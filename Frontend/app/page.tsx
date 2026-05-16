"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, Briefcase, CheckCircle2, Globe, Loader2, Search, Send, Sparkles, Terminal, TrendingUp } from "lucide-react";
import ReactMarkdown from "react-markdown";

type Message = {
  role: "user" | "oracle";
  content: string;
  agents_used?: string[];
};

type ProcessStatus = "info" | "running" | "completed" | "error";

type ProcessStep = {
  id: string;
  label: string;
  status: ProcessStatus;
  agent?: string;
};

type StreamEvent = {
  type: string;
  label?: string;
  message?: string;
  agent?: string;
  reply?: string;
  agents_used?: string[];
  domain?: string;
};

const API_BASE_URL = "http://localhost:8080";

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "oracle",
      content: "Welcome to **ORACLE Financial Intelligence OS**. How can I assist you with your market research today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [processSteps, setProcessSteps] = useState<ProcessStep[]>([]);
  const [sourceDomains, setSourceDomains] = useState<string[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, processSteps, sourceDomains, isLoading]);

  const upsertProcessStep = (event: StreamEvent) => {
    if (event.type === "status" && event.label) {
      const label = event.label;
      setProcessSteps((prev) => [
        ...prev,
        {
          id: `status-${prev.length + 1}`,
          label,
          status: "info",
        },
      ]);
      return;
    }

    if (event.type === "error") {
      const label = event.message || "Something went wrong during execution.";
      setProcessSteps((prev) => [
        ...prev,
        {
          id: `error-${prev.length + 1}`,
          label,
          status: "error",
        },
      ]);
      return;
    }

    if (event.type === "source" && event.domain) {
      setSourceDomains((prev) => (prev.includes(event.domain as string) ? prev : [...prev, event.domain as string]));
      if (event.label) {
        const label = event.label;
        setProcessSteps((prev) => [
          ...prev,
          {
            id: `source-${event.domain}-${prev.length + 1}`,
            label,
            status: "info",
            agent: event.agent,
          },
        ]);
      }
      return;
    }

    if (!event.agent || !event.label) return;
    const agent = event.agent;
    const label = event.label;

    setProcessSteps((prev) => [
      ...prev,
      {
        id: `${agent}-${prev.length + 1}`,
        agent,
        label,
        status:
          event.type === "agent_completed"
            ? "completed"
            : event.type === "agent_unavailable"
              ? "error"
            : event.type === "agent_planned"
              ? "info"
              : "running",
      },
    ]);
  };

  const fallbackToJsonChat = async (userMsg: string) => {
    const res = await fetch(`${API_BASE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userMsg }),
    });

    if (!res.ok) {
      let detail = "Network response was not ok";
      try {
        const errorData = await res.json();
        detail = errorData.detail || detail;
      } catch {
        detail = await res.text();
      }
      throw new Error(detail);
    }

    const data = await res.json();
    setMessages((prev) => [
      ...prev,
      {
        role: "oracle",
        content: data.reply,
        agents_used: data.agents_used,
      },
    ]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setProcessSteps([]);
    setSourceDomains([]);
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg }),
      });

      if (!res.ok) {
        let detail = "The backend returned an error.";
        try {
          const errorData = await res.json();
          detail = errorData.detail || detail;
        } catch {
          detail = await res.text();
        }
        throw new Error(detail);
      }

      if (!res.body) {
        await fallbackToJsonChat(userMsg);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload: StreamEvent | null = null;
      let streamErrorMessage: string | null = null;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";

        for (const chunk of chunks) {
          const lines = chunk.split("\n");
          let eventType = "message";
          let dataLine = "";

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            }
            if (line.startsWith("data:")) {
              dataLine += line.slice(5).trim();
            }
          }

          if (!dataLine) continue;

          const parsed = JSON.parse(dataLine) as StreamEvent;
          const normalizedEvent = { ...parsed, type: parsed.type || eventType };

          if (normalizedEvent.type === "final") {
            finalPayload = normalizedEvent;
            continue;
          }

          if (normalizedEvent.type === "error") {
            streamErrorMessage = normalizedEvent.message || "The backend reported an error while generating the answer.";
            upsertProcessStep(normalizedEvent);
            break;
          }

          upsertProcessStep(normalizedEvent);
        }

        if (streamErrorMessage) {
          try {
            await reader.cancel();
          } catch {}
          break;
        }
      }

      if (streamErrorMessage) {
        throw new Error(streamErrorMessage);
      }

      if (!finalPayload) {
        throw new Error("The streaming response ended before a final answer was received.");
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "oracle",
          content: finalPayload.reply || "I couldn't generate a response.",
          agents_used: finalPayload.agents_used || [],
        },
      ]);
    } catch (error) {
      console.error(error);
      const message = error instanceof Error ? error.message : "Connection error while contacting the ORACLE backend.";
      setProcessSteps([
        {
          id: "connection-error",
          label: message,
          status: "error",
        },
      ]);
      setMessages((prev) => [
        ...prev,
        { role: "oracle", content: message },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const agentStateMap = new Map<string, ProcessStep>();
  for (const step of processSteps) {
    if (step.agent && !step.id.startsWith("source-")) {
      agentStateMap.set(step.agent, step);
    }
  }
  const agentSteps = Array.from(agentStateMap.values());
  const recentSteps = processSteps.slice(-8);

  return (
    <div className="flex h-screen w-full bg-slate-950 text-slate-50 font-sans selection:bg-blue-500/30">
      <div className="hidden md:flex flex-col w-72 border-r border-slate-800 bg-slate-900/50 p-6">
        <div className="flex items-center gap-3 mb-10">
          <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 shadow-lg shadow-blue-500/20">
            <Sparkles size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white">ORACLE</h1>
            <p className="text-xs font-medium text-slate-400 tracking-wider">FINANCIAL OS</p>
          </div>
        </div>

        <div className="space-y-6 flex-1">
          <div>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Live Intelligence</h3>
            <ul className="space-y-2 text-sm text-slate-300">
              <li className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-800 transition-colors">
                <Activity size={16} className="text-emerald-400" /> Market Data Node
              </li>
              <li className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-800 transition-colors">
                <Briefcase size={16} className="text-blue-400" /> Fundamentals Engine
              </li>
              <li className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-800 transition-colors">
                <Search size={16} className="text-cyan-400" /> Research Pipeline
              </li>
              <li className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-800 transition-colors">
                <TrendingUp size={16} className="text-amber-400" /> Valuation Models
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-auto">
          <div className="glass-panel p-4 rounded-xl">
            <div className="flex items-center gap-2 mb-2">
              <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></div>
              <span className="text-xs font-medium text-slate-300">System Online</span>
            </div>
            <p className="text-xs text-slate-500">Connected to local LangGraph + MCP endpoints.</p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-h-0">
        <header className="h-16 flex items-center px-6 border-b border-slate-800 bg-slate-950/80 backdrop-blur-md z-10 flex-shrink-0">
          <h2 className="font-medium text-slate-200">Terminal</h2>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-8 space-y-8 scroll-smooth">
          {messages.map((m, idx) => (
            <div key={idx} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"} max-w-4xl mx-auto w-full`}>
              <div className={`flex gap-4 max-w-[85%] ${m.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                <div
                  className={`flex-shrink-0 h-10 w-10 rounded-full flex items-center justify-center border ${
                    m.role === "user"
                      ? "bg-slate-800 border-slate-700"
                      : "bg-blue-600/10 border-blue-500/30 text-blue-400"
                  }`}
                >
                  {m.role === "user" ? <Terminal size={18} /> : <Sparkles size={18} />}
                </div>

                <div className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
                  <div
                    className={`px-5 py-4 rounded-2xl text-[15px] leading-relaxed shadow-sm ${
                      m.role === "user"
                        ? "bg-blue-600 text-white rounded-tr-sm"
                        : "glass-panel text-slate-200 rounded-tl-sm"
                    }`}
                  >
                    <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-slate-900 prose-pre:border prose-pre:border-slate-800">
                      <ReactMarkdown>{m.content}</ReactMarkdown>
                    </div>
                  </div>

                  {m.agents_used && m.agents_used.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-3 pl-2">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold pt-1">Agents used:</span>
                      {m.agents_used.map((agent) => (
                        <span key={agent} className="px-2 py-1 bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded-md shadow-sm">
                          {agent.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start max-w-4xl mx-auto w-full">
              <div className="flex gap-4">
                <div className="flex-shrink-0 h-10 w-10 rounded-full bg-blue-600/10 border border-blue-500/30 text-blue-400 flex items-center justify-center">
                  <Loader2 size={18} className="animate-spin" />
                </div>
                <div className="px-5 py-4 rounded-2xl bg-slate-900 border border-slate-800 text-slate-400 text-sm flex items-center gap-3">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500"></span>
                  </span>
                  ORACLE is analyzing...
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="flex-shrink-0 border-t border-slate-800 bg-slate-950/95 backdrop-blur-md px-4 py-4 md:px-8 md:py-5">
          <div className="max-w-3xl mx-auto">
            <div className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-blue-600 to-teal-500 rounded-2xl blur opacity-25 group-focus-within:opacity-50 transition duration-500"></div>
              <form
                onSubmit={handleSubmit}
                className="relative flex items-center bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden"
              >
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask ORACLE to analyze a stock, compare peers, or fetch news..."
                  className="flex-1 bg-transparent px-6 py-4 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-0 text-[15px]"
                  disabled={isLoading}
                  suppressHydrationWarning
                />
                <button
                  type="submit"
                  disabled={!input.trim() || isLoading}
                  className="mr-2 p-2.5 rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:hover:bg-blue-600 transition-colors"
                  suppressHydrationWarning
                >
                  {isLoading ? <Loader2 size={20} className="animate-spin" /> : <Send size={20} />}
                </button>
              </form>
            </div>

            {(isLoading || processSteps.length > 0 || sourceDomains.length > 0) && (
              <div className="mt-3 grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
                <div className="rounded-2xl border border-slate-800 bg-slate-900/90 p-3">
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Sub Agents</p>
                    <span className="text-[10px] text-slate-500">{isLoading ? "Live" : "Last run"}</span>
                  </div>
                  <div className="mt-3 space-y-2">
                    {agentSteps.length === 0 && (
                      <p className="text-xs text-slate-500">Waiting for routing...</p>
                    )}
                    {agentSteps.map((step) => (
                      <div key={step.id} className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/70 px-2.5 py-2">
                        {step.status === "completed" ? (
                          <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0" />
                        ) : step.status === "error" ? (
                          <div className="h-2.5 w-2.5 rounded-full bg-rose-400 flex-shrink-0" />
                        ) : step.status === "info" ? (
                          <div className="h-2.5 w-2.5 rounded-full bg-cyan-400 flex-shrink-0" />
                        ) : (
                          <Loader2 size={14} className="text-blue-400 animate-spin flex-shrink-0" />
                        )}
                        <div className="min-w-0">
                          <p className="text-xs text-slate-200 truncate">{step.agent?.replace(/_/g, " ")}</p>
                          <p className="text-[11px] text-slate-500 truncate">{step.status}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-900/90 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Process</p>
                    {sourceDomains.length > 0 && (
                      <div className="flex items-center gap-2 text-[10px] text-slate-500">
                        <Globe size={12} />
                        <span>Sources</span>
                      </div>
                    )}
                  </div>

                  {sourceDomains.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {sourceDomains.map((domain) => (
                        <span key={domain} className="px-2 py-1 rounded-full border border-cyan-900/60 bg-cyan-950/40 text-cyan-200 text-[11px]">
                          {domain}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="mt-3 max-h-32 overflow-y-auto space-y-2 pr-1">
                    {recentSteps.length === 0 && (
                      <p className="text-xs text-slate-500">No execution steps yet.</p>
                    )}
                    {recentSteps.map((step) => (
                      <div key={`${step.id}-${step.label}`} className="flex items-start gap-2 text-xs">
                        <span
                          className={`mt-1 h-2 w-2 rounded-full flex-shrink-0 ${
                            step.status === "completed"
                              ? "bg-emerald-400"
                              : step.status === "error"
                                ? "bg-rose-400"
                                : step.status === "info"
                                  ? "bg-cyan-400"
                                  : "bg-blue-400 animate-pulse"
                          }`}
                        ></span>
                        <span className="text-slate-300">{step.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="text-center mt-3">
              <p className="text-[11px] text-slate-500 font-medium">Powered by LangGraph, FastMCP, and Deep Analysis Agents.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
