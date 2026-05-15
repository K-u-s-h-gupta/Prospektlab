import re

with open('finagent/gateway/widget.html', 'r', encoding='utf-8') as f:
    text = f.read()

body_text = text[:text.find('<script>')]
js_text = text[text.find('<script>'):]
defined = set(re.findall(r'id=["\'](.*?)["\']', body_text))
called = set(re.findall(r'\$\(["\'](.*?)["\']\)', js_text))

missing = called - defined
print('Missing IDs:')
for m in sorted(missing):
    print(f'- {m}')
