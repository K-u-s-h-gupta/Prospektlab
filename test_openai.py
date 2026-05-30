import asyncio
from finagent.runtime_provider import resolve_openai_config
from openai import AsyncOpenAI
import os

async def main():
    os.environ["OPENAI_API_KEY"] = "fake-key"
    cfg = resolve_openai_config()
    client = AsyncOpenAI(api_key=cfg.api_key)
    try:
        resp = await client.chat.completions.create(
            model=cfg.model,
            max_tokens=12000,
            messages=[{"role": "user", "content": "hi"}]
        )
    except Exception as e:
        print("OpenAI Error:", repr(e))

asyncio.run(main())
