"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleStop,
  Clock3,
  FileText,
  Globe,
  Loader2,
  Search,
  Send,
  Terminal,
  UserRound,
  Zap,
  Sparkles,
  Command,
  ArrowUp,
  Square,
  MoreHorizontal,
  Layers
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { RichResponseComponent } from "./_components/RichResponse";
import type { RichResponse } from "./_components/lib/types";

type McpServerStatus = { ok: boolean; latency_ms?: number; url?: string; error?: string };
type McpHealthStatus = { all_ok: boolean; servers: Record<string, McpServerStatus> };

type QueryMode = "research" | "marathon";

type Message = {
  role: "user" | "oracle";
  content: string;
  agents_used?: string[];
  rich?: RichResponse;
  mode?: QueryMode;
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
  rich?: RichResponse;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

const modes: Array<{
  id: QueryMode;
  label: string;
  caption: string;
  icon: typeof Search;
}> = [
  {
    id: "research",
    label: "Research",
    caption: "Specific",
    icon: Zap,
  },
  {
    id: "marathon",
    label: "Marathon",
    caption: "Deep Dive",
    icon: Layers,
  },
];

const loadingCopy: Record<QueryMode, string[]> = {
  research: ["Synthesizing signals...", "Consulting sources...", "Formulating insight..."],
  marathon: ["Mapping topography...", "Deploying agent swarm...", "Constructing intelligence report..."],
};

function classNames(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function CreativeLoader({ mode, steps }: { mode: QueryMode; steps: ProcessStep[] }) {
  const latest = steps.at(-1)?.label ?? loadingCopy[mode][0];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, filter: "blur(8px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
      className="mx-auto flex w-full max-w-3xl justify-start my-6"
    >
      <div className="flex gap-5 items-center">
        <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-black border border-white/10 shadow-[0_0_30px_rgba(255,255,255,0.05)]">
           <div className="absolute inset-0 rounded-full border border-white/20 animate-[spin_3s_linear_infinite]" />
           <div className="absolute inset-1.5 rounded-full border border-zinc-500/30 animate-[spin_2s_linear_infinite_reverse]" />
           <Sparkles size={14} className="text-zinc-300 animate-pulse" />
        </div>
        <div className="flex flex-col gap-1.5">
          <motion.p 
            key={latest}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-[13px] font-medium tracking-wide text-zinc-300"
          >
            {latest}
          </motion.p>
          <div className="flex gap-2 items-center">
             <div className="flex gap-1">
               <span className="h-1 w-1 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '0ms' }} />
               <span className="h-1 w-1 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '150ms' }} />
               <span className="h-1 w-1 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '300ms' }} />
             </div>
             <span className="text-[10px] text-zinc-600 uppercase tracking-widest font-semibold ml-1">
               {mode} mode active
             </span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "oracle",
      mode: "research",
      content:
        "Welcome to **Prospektlab Intelligence**. How can I assist you today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<QueryMode>("research");
  const [isLoading, setIsLoading] = useState(false);
  const [processSteps, setProcessSteps] = useState<ProcessStep[]>([]);
  const [sourceDomains, setSourceDomains] = useState<string[]>([]);
  const [mcpHealth, setMcpHealth] = useState<McpHealthStatus | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageScrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const activeMode = modes.find((item) => item.id === mode) ?? modes[0];

  const agentStateMap = useMemo(() => {
    const map = new Map<string, ProcessStep>();
    for (const step of processSteps) {
      if (step.agent && !step.id.startsWith("source-")) {
        map.set(step.agent, step);
      }
    }
    return map;
  }, [processSteps]);
  const agentSteps = Array.from(agentStateMap.values());
  const recentSteps = processSteps.slice(-3);

  const scrollToBottom = (force = false) => {
    const container = messageScrollRef.current;
    if (!container) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
    if (force || nearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, processSteps, sourceDomains, isLoading]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/health/mcp`)
      .then((r) => r.json())
      .then((data: McpHealthStatus) => setMcpHealth(data))
      .catch(() => setMcpHealth({ all_ok: false, servers: {} }));
  }, []);

  const upsertProcessStep = (event: StreamEvent) => {
    if (event.type === "status" && event.label) {
      setProcessSteps((prev) => [...prev, { id: `status-${prev.length + 1}`, label: event.label as string, status: "info" }]);
      return;
    }

    if (event.type === "error") {
      setProcessSteps((prev) => [
        ...prev,
        {
          id: `error-${prev.length + 1}`,
          label: event.message || "Something went wrong.",
          status: "error",
        },
      ]);
      return;
    }

    if (event.type === "source" && event.domain) {
      setSourceDomains((prev) => (prev.includes(event.domain as string) ? prev : [...prev, event.domain as string]));
      if (event.label) {
        setProcessSteps((prev) => [
          ...prev,
          {
            id: `source-${event.domain}-${prev.length + 1}`,
            label: event.label as string,
            status: "info",
            agent: event.agent,
          },
        ]);
      }
      return;
    }

    if (!event.agent || !event.label) return;

    setProcessSteps((prev) => [
      ...prev,
      {
        id: `${event.agent}-${prev.length + 1}`,
        agent: event.agent,
        label: event.label as string,
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

  const fallbackToJsonChat = async (userMsg: string, queryMode: QueryMode, signal: AbortSignal) => {
    const res = await fetch(`${API_BASE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: userMsg, mode: queryMode }),
      signal,
    });

    if (!res.ok) {
      let detail = "Network error";
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
        mode: queryMode,
        content: data.reply,
        agents_used: data.agents_used,
        rich: data.rich ?? undefined,
      },
    ]);
  };

  const handleStop = () => {
    if (!abortControllerRef.current) return;
    abortControllerRef.current.abort();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMsg = input.trim();
    const queryMode = mode;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", mode: queryMode, content: userMsg }]);
    setProcessSteps([]);
    setSourceDomains([]);
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, mode: queryMode }),
        signal: controller.signal,
      });

      if (!res.ok) {
        let detail = "Backend error";
        try {
          const errorData = await res.json();
          detail = errorData.detail || detail;
        } catch {
          detail = await res.text();
        }
        throw new Error(detail);
      }

      if (!res.body) {
        await fallbackToJsonChat(userMsg, queryMode, controller.signal);
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
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }

          if (!dataLine) continue;

          const parsed = JSON.parse(dataLine) as StreamEvent;
          const normalizedEvent = { ...parsed, type: parsed.type || eventType };

          if (normalizedEvent.type === "final") {
            finalPayload = normalizedEvent;
            continue;
          }

          if (normalizedEvent.type === "error") {
            streamErrorMessage = normalizedEvent.message || "Error generating answer.";
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
        throw new Error("Stream ended early.");
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "oracle",
          mode: queryMode,
          content: finalPayload.reply || "No response generated.",
          agents_used: finalPayload.agents_used || [],
          rich: finalPayload.rich ?? undefined,
        },
      ]);
    } catch (error) {
      if (controller.signal.aborted) {
        setProcessSteps((prev) => [...prev, { id: `abort-${Date.now()}`, label: "Run stopped", status: "error" }]);
        setMessages((prev) => [...prev, { role: "oracle", mode: queryMode, content: "Query aborted." }]);
      } else {
        console.error(error);
        const message = error instanceof Error ? error.message : "Connection error.";
        setProcessSteps([{ id: "connection-error", label: message, status: "error" }]);
        setMessages((prev) => [...prev, { role: "oracle", mode: queryMode, content: message }]);
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (input.trim() && !isLoading) {
        const synthEvent = { preventDefault: () => {} } as FormEvent;
        handleSubmit(synthEvent);
      }
    }
  };

  return (
    <main className="relative flex h-dvh w-full flex-col overflow-hidden bg-[#0a0a0a] text-zinc-100 font-sans selection:bg-zinc-800">
      {/* Abstract dark creative background */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(255,255,255,0.03)_0%,rgba(0,0,0,1)_80%)]" />
        <div className="absolute inset-0 opacity-[0.015] bg-[url('https://grainy-gradients.vercel.app/noise.svg')]" />
      </div>

      {/* Minimal Header */}
      <header className="relative z-10 flex h-14 shrink-0 items-center justify-between px-6 md:px-10">
        <div className="flex items-center gap-3 opacity-80 hover:opacity-100 transition-opacity">
          <Sparkles size={16} className="text-zinc-400" />
          <h1 className="text-sm font-semibold tracking-wide text-zinc-200">Prospektlab</h1>
        </div>
        <div className="flex items-center gap-3">
          {mcpHealth && (
            <div className="flex items-center gap-2 text-[10px] tracking-widest uppercase font-medium text-zinc-500">
               <span className={classNames("h-1.5 w-1.5 rounded-full", mcpHealth.all_ok ? "bg-emerald-500" : "bg-amber-500")} />
               {mcpHealth.all_ok ? "Systems Nominal" : "Degraded"}
            </div>
          )}
        </div>
      </header>

      {/* Chat Area */}
      <div ref={messageScrollRef} className="relative z-10 flex-1 overflow-y-auto px-4 md:px-10 pt-4 pb-32">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
          <AnimatePresence initial={false}>
            {messages.map((m, idx) => (
              <motion.div
                key={`${idx}-${m.role}`}
                initial={{ opacity: 0, y: 15, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
                className={classNames("flex w-full", m.role === "user" ? "justify-end" : "justify-start")}
              >
                <div className={classNames("flex flex-col gap-2 max-w-[85%] md:max-w-[75%]", m.role === "user" ? "items-end" : "items-start")}>
                  
                  {m.role === "user" ? (
                    <div className="px-5 py-3.5 rounded-2xl rounded-tr-sm bg-zinc-800/80 backdrop-blur-md border border-zinc-700/50 text-[15px] leading-relaxed text-zinc-100 shadow-sm">
                      {m.content}
                    </div>
                  ) : (
                    <div className="w-full text-left">
                       {/* Contextual UI / Rich Response */}
                       {m.rich && (
                         <div className="mb-4 w-full overflow-hidden rounded-2xl border border-white/5 bg-white/[0.02] shadow-2xl backdrop-blur-xl">
                            <RichResponseComponent data={m.rich} />
                         </div>
                       )}
                       {/* Text Content */}
                       <div className="prose prose-invert max-w-none text-[15px] leading-8 text-zinc-300 prose-p:my-4 prose-headings:font-semibold prose-headings:text-zinc-100 prose-a:text-zinc-100 prose-a:underline-offset-4 hover:prose-a:text-white prose-strong:text-zinc-100 prose-code:text-zinc-300 prose-code:bg-white/5 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-pre:bg-black/50 prose-pre:border prose-pre:border-white/5">
                          <ReactMarkdown>{m.content}</ReactMarkdown>
                       </div>
                       
                       {/* Agents Used Tags */}
                       {m.agents_used && m.agents_used.length > 0 && (
                          <div className="mt-4 flex flex-wrap gap-2">
                             {m.agents_used.map((agent) => (
                               <span key={agent} className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-[10px] uppercase tracking-wider font-medium text-zinc-500 border border-white/5">
                                  <Terminal size={10} />
                                  {agent.replace(/_/g, " ")}
                               </span>
                             ))}
                          </div>
                       )}
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
            
            {isLoading && <CreativeLoader key="creative-loader" mode={mode} steps={processSteps} />}
          </AnimatePresence>
          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* Floating Input Area */}
      <div className="absolute bottom-0 left-0 right-0 z-20 bg-gradient-to-t from-[#0a0a0a] via-[#0a0a0a]/90 to-transparent pb-6 pt-12 px-4 md:px-10">
        <div className="mx-auto w-full max-w-3xl">
          
          {/* Progress Indicators (Only when active) */}
          <AnimatePresence>
            {(isLoading || processSteps.length > 0) && (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 10 }}
                className="mb-4 flex flex-wrap gap-2"
              >
                 {agentSteps.map((step) => (
                    <div key={step.id} className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-[11px] border border-white/5 backdrop-blur-md text-zinc-400">
                      {step.status === "completed" ? <CheckCircle2 size={12} className="text-zinc-300" /> : <Loader2 size={12} className="animate-spin text-zinc-500" />}
                      <span>{step.agent?.replace(/_/g, " ")}</span>
                    </div>
                 ))}
                 {sourceDomains.length > 0 && (
                   <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-[11px] border border-white/5 backdrop-blur-md text-zinc-400">
                     <Globe size={12} />
                     <span>{sourceDomains.length} Sources</span>
                   </div>
                 )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="relative group">
            {/* Glow Effect behind input */}
            <div className="absolute -inset-1 rounded-3xl bg-white/5 opacity-50 blur-xl transition-opacity group-focus-within:opacity-100 group-focus-within:bg-white/10" />
            
            <form onSubmit={handleSubmit} className="relative flex flex-col rounded-3xl bg-[#0f0f0f] border border-zinc-800/60 shadow-2xl overflow-hidden transition-all focus-within:border-zinc-700">
              
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={mode === "marathon" ? "Deploy marathon research... (Shift+Enter for new line)" : "Ask a specific question..."}
                className="w-full resize-none bg-transparent px-6 pt-5 pb-3 text-[15px] leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:outline-none min-h-[64px] max-h-[200px]"
                disabled={isLoading}
                rows={1}
                suppressHydrationWarning
              />
              
              <div className="flex items-center justify-between px-4 pb-4">
                {/* Mode Switcher */}
                <div className="flex items-center bg-black/40 rounded-full p-1 border border-white/5">
                  {modes.map((item) => {
                    const Icon = item.icon;
                    const isActive = mode === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setMode(item.id)}
                        disabled={isLoading}
                        className={classNames(
                          "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-medium transition-all duration-300",
                          isActive 
                            ? "bg-zinc-800 text-zinc-100 shadow-sm" 
                            : "text-zinc-500 hover:text-zinc-300 hover:bg-white/5"
                        )}
                      >
                        <Icon size={12} className={isActive ? "opacity-100" : "opacity-60"} />
                        {item.label}
                      </button>
                    )
                  })}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                   {isLoading ? (
                      <button
                        type="button"
                        onClick={handleStop}
                        className="group flex h-9 w-9 items-center justify-center rounded-full bg-red-500/10 text-red-400 transition-colors hover:bg-red-500/20 border border-red-500/20"
                        title="Stop Generation"
                      >
                         <Square size={14} className="fill-current" />
                      </button>
                   ) : (
                      <button
                        type="submit"
                        disabled={!input.trim()}
                        className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-100 text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
                        title="Send Message"
                      >
                         <ArrowUp size={18} strokeWidth={2.5} />
                      </button>
                   )}
                </div>
              </div>
            </form>
          </div>
          
          <div className="mt-4 text-center">
             <p className="text-[10px] text-zinc-600 font-medium tracking-wide">Prospektlab can make mistakes. Verify critical information.</p>
          </div>
        </div>
      </div>
    </main>
  );
}

