import asyncio
import logging
import os
import sys

# Reconfigure stdout/stderr for Windows UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

logging.basicConfig(level=logging.INFO)

from finagent.router.intent_router import LLMQueryContextualizer

async def test_contextualizer():
    contextualizer = LLMQueryContextualizer()
    
    test_cases = [
        # (query, prior_target, expected_is_followup)
        ("provide me its latest news", "BEL", True),
        ("what is their market share?", "Reliance", True),
        ("analyze this company for me", "TCS", True),
        ("analyze REL vs Wipro", "Reliance", False),
        ("what is the latest news for HDFC?", "BEL", False),
        ("how does it compare to peers?", "Wipro", True),
    ]
    
    print("--- Testing Contextualizer ---")
    for query, prior, expected in test_cases:
        rewritten, is_followup = await contextualizer.contextualize(query, prior)
        print(f"Prior Target: {prior}")
        print(f"Query:        '{query}'")
        print(f"Rewritten:    '{rewritten}'")
        print(f"Is Followup:  {is_followup} (Expected: {expected})")
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(test_contextualizer())
