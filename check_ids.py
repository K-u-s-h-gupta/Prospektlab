import re

with open('finagent/gateway/widget.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Find all IDs defined in the HTML body
body_match = re.search(r'<body.*?(<script>.*)', text, re.DOTALL)
if body_match:
    body_text = text[:text.find('<script>')]
    js_text = body_match.group(1)
    
    defined_ids = set(re.findall(r'id=["\'](.*?)["\']', body_text))
    
    # Find all calls to $() in JS
    called_ids = set(re.findall(r'\$\(["\'](.*?)["\']\)', js_text))
    
    missing = called_ids - defined_ids
    print("MISSING IDs CALLED BY JS:")
    for m in sorted(missing):
        print(f"- {m}")
