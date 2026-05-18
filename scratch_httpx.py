import re

file_path = "finagent/tools/data/india.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace block 1: Screener
content = content.replace(
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            async with session.get(url) as resp:
                if resp.status_code != 200:
                    return None
                html = resp.text''',
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text''')

# Replace block 2: Moneycontrol
content = content.replace(
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            async with session.get(url) as resp:
                if resp.status_code != 200:
                    return None
                data = resp.json(content_type=None)''',
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()''')

# Replace block 3: NSE (quote)
content = content.replace(
'''        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
            # Seed cookies with a homepage visit
            async with session.get("https://www.nseindia.com", headers=_HEADERS_NSE) as _:
                pass
            async with session.get(quote_url, headers=_HEADERS_NSE) as resp:
                if resp.status_code != 200:
                    return None
                data = resp.json(content_type=None)''',
'''        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
            # Seed cookies with a homepage visit
            _ = await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(quote_url, headers=_HEADERS_NSE)
            if resp.status_code != 200:
                return None
            data = resp.json()''')

# Replace block 4: BSE
content = content.replace(
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            async with session.get(url) as resp:
                if resp.status_code != 200:
                    return None
                data = resp.json(content_type=None)''',
'''        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()''')

# Replace block 5: NSE (shareholding)
content = content.replace(
'''        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
            async with session.get("https://www.nseindia.com", headers=_HEADERS_NSE) as _:
                pass
            async with session.get(url, headers=_HEADERS_NSE) as resp:
                if resp.status_code == 200:
                    data = resp.json(content_type=None)
                    holding = _parse_nse_shareholding(data)
                    if holding:
                        cache_set("shareholding", symbol, holding, "shareholding")
                        return holding''',
'''        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
            _ = await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(url, headers=_HEADERS_NSE)
            if resp.status_code == 200:
                data = resp.json()
                holding = _parse_nse_shareholding(data)
                if holding:
                    cache_set("shareholding", symbol, holding, "shareholding")
                    return holding''')

# Replace block 6: Trendlyne
content = content.replace(
'''        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0),
                                          headers=_HEADERS_MC) as session:
            async with session.get(url) as resp:
                if resp.status_code != 200:
                    return None
                html = resp.text''',
'''        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text''')

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("httpx syntax fully fixed")
