import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, LayoutDashboard, ShieldAlert, TrendingUp, Rocket, ArrowRight, CornerDownLeft } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

/**
 * Global command palette (Ctrl/Cmd+K) — the Bloomberg-style spine.
 * Theme-native (custom CSS vars, no UI library). Self-contained: mounts once,
 * listens globally, fuzzy-filters a static command set + recent companies.
 */

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  keywords: string;
  run: (nav: ReturnType<typeof useNavigate>) => void;
}

const BASE_COMMANDS: Command[] = [
  { id: 'go-dashboard', label: 'Go to Dashboard', icon: LayoutDashboard, keywords: 'dashboard home portfolio overview',
    run: (nav) => nav('/dashboard/overview') },
  { id: 'go-ipo', label: 'IPO Pipeline', hint: 'primary market', icon: Rocket,
    keywords: 'ipo primary market drhp rhp gmp listing issue pipeline',
    run: (nav) => nav('/dashboard/ipo') },
  { id: 'go-governance', label: 'Portfolio Governance X-Ray', hint: 'forensic risk', icon: ShieldAlert,
    keywords: 'governance risk forensic pledge enforcement xray',
    run: (nav) => nav('/dashboard/governance') },
  { id: 'go-analytics', label: 'Portfolio Analytics', icon: TrendingUp, keywords: 'analytics beta volatility risk performance',
    run: (nav) => nav('/dashboard/portfolio') },
];

function fuzzyScore(query: string, text: string): number {
  if (!query) return 1;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return 100 - (t.indexOf(q));
  // subsequence match
  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length ? 10 : 0;
}

export const CommandPalette: React.FC = () => {
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [active, setActive] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);

  // Global hotkey
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  React.useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const results = React.useMemo(() => {
    return BASE_COMMANDS
      .map((c) => ({ c, s: fuzzyScore(query, c.label + ' ' + c.keywords) }))
      .filter((r) => r.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((r) => r.c);
  }, [query]);

  React.useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, results.length - 1)));
  }, [results.length]);

  if (!open) return null;

  const runActive = () => {
    const cmd = results[active];
    if (cmd) {
      cmd.run(navigate);
      setOpen(false);
    }
  };

  return (
    <div className="cmdk-backdrop" onMouseDown={() => setOpen(false)}>
      <div className="cmdk-panel" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cmdk-input-row">
          <Search size={16} color="var(--accent-cyan)" />
          <input
            ref={inputRef}
            className="cmdk-input"
            placeholder="Search companies, jump to a view, run an action…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              else if (e.key === 'Enter') { e.preventDefault(); runActive(); }
            }}
          />
          <kbd className="cmdk-kbd">ESC</kbd>
        </div>
        <div className="cmdk-results">
          {results.length === 0 && <div className="cmdk-empty">No matches</div>}
          {results.map((cmd, i) => {
            const Icon = cmd.icon;
            return (
              <button
                key={cmd.id}
                className={`cmdk-item ${i === active ? 'cmdk-item-active' : ''}`}
                onMouseEnter={() => setActive(i)}
                onClick={runActive}
              >
                <Icon size={15} color={i === active ? 'var(--accent-cyan)' : 'var(--text-muted)'} />
                <span className="cmdk-item-label">{cmd.label}</span>
                {cmd.hint && <span className="cmdk-item-hint">{cmd.hint}</span>}
                {i === active
                  ? <CornerDownLeft size={13} color="var(--text-muted)" />
                  : <ArrowRight size={13} color="transparent" />}
              </button>
            );
          })}
        </div>
        <div className="cmdk-footer">
          <span><kbd className="cmdk-kbd">↑↓</kbd> navigate</span>
          <span><kbd className="cmdk-kbd">↵</kbd> select</span>
          <span><kbd className="cmdk-kbd">⌘K</kbd> toggle</span>
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;
