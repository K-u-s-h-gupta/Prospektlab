import urllib.request, json
urls = [
    'https://api.prospektlab.com/health',
    'https://api.prospektlab.com/api/health/mcp',
    'https://pp2nutjt0l.execute-api.us-east-1.amazonaws.com/health'
]
for url in urls:
    print(f"Checking URL: {url}")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as res:
            print(f"  Status code: {res.getcode()}")
            print(f"  Response: {res.read().decode('utf-8')[:300]}")
    except Exception as e:
        print(f"  Error: {e}")
