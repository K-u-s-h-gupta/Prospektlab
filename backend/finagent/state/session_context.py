from contextvars import ContextVar
from typing import Set
from urllib.parse import urlparse

# ContextVars to track session-scoped metrics
active_agents: ContextVar[Set[str] | None] = ContextVar("active_agents", default=None)
active_mcps: ContextVar[Set[str] | None] = ContextVar("active_mcps", default=None)
active_websites: ContextVar[Set[str] | None] = ContextVar("active_websites", default=None)

def init_session_context():
    """Initialize fresh sets of context variables for the current async task chain."""
    active_agents.set(set())
    active_mcps.set(set())
    active_websites.set(set())

def record_agent(name: str):
    agents = active_agents.get()
    if agents is not None:
        agents.add(name)

def record_mcp(name: str):
    mcps = active_mcps.get()
    if mcps is not None:
        mcps.add(name)

def record_website(url_or_domain: str):
    websites = active_websites.get()
    if websites is not None:
        try:
            if url_or_domain.startswith("http://") or url_or_domain.startswith("https://"):
                domain = urlparse(url_or_domain).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
            else:
                domain = url_or_domain
            if domain:
                websites.add(domain)
        except Exception:
            websites.add(url_or_domain)
