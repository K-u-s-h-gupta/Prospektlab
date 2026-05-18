"""Extract JS from widget.html and check for syntax errors using node."""
import re, subprocess, tempfile, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('finagent/gateway/widget.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Find the main <script> block (the big one after line 789)
scripts = list(re.finditer(r'<script>(.*?)</script>', html, re.DOTALL))
print(f"Found {len(scripts)} script blocks")

# The main script is the largest one
main_script = max(scripts, key=lambda m: len(m.group(1)))
js = main_script.group(1)
start_line = html[:main_script.start()].count('\n') + 1
print(f"Main script starts at HTML line {start_line}, length {len(js)} chars")

# Write to temp file and check syntax with node
js_file = os.path.join(os.path.dirname(__file__), '_check_syntax.js')
with open(js_file, 'w', encoding='utf-8') as f:
    f.write(js)

result = subprocess.run(['node', '--check', js_file], capture_output=True, text=True)
if result.returncode == 0:
    print("JS syntax: OK (no errors)")
else:
    print(f"JS syntax ERROR:\n{result.stderr}")

# Clean up
os.unlink(js_file)
