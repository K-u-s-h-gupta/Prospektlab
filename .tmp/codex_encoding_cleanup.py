from pathlib import Path

client = Path('Frontend/src/api/client.ts')
text = client.read_text(encoding='utf-8')
client_comment_labels = [
    'Runtime Backend URL Support (for Amplify + separate ECS backend)',
    'Auth state (in-memory only; httpOnly cookie is the source of truth)',
    'Auth Endpoints',
    'Portfolio Endpoints',
    'Governance & Network intelligence',
    'Research and Chat SSE Endpoints',
    'Market Data & Token Usage API Endpoints',
    'Flash Content Engine API',
    'Document export (deep mode only)',
    'IPO Intelligence',
]
lines = []
for line in text.splitlines():
    for label in client_comment_labels:
        if label in line:
            lines.append(f'// -- {label} --')
            break
    else:
        if 'SSE HTTP error status:' in line and 'retrying in 3s' in line:
            indent = line[:len(line) - len(line.lstrip())]
            lines.append(indent + 'console.warn("SSE HTTP error status:", resp.status, "- retrying in 3s");')
        else:
            lines.append(line)
client.write_text('\n'.join(lines) + '\n', encoding='utf-8')

css = Path('Frontend/src/components/earnings/earnings.css')
text = css.read_text(encoding='utf-8')
css_comment_labels = [
    'workspace shell', 'date strip', 'monthly calendar collapse', 'list section',
    'company cards', 'EPS row for past results', 'pagination', 'shared utility', 'responsive'
]
lines = []
for line in text.splitlines():
    stripped = line.strip()
    for label in css_comment_labels:
        if label in stripped and stripped.startswith('/*'):
            lines.append(f'/* -- {label} -- */')
            break
    else:
        if "content: '" in line and ('â' in line or 'Ã' in line or '�' in line):
            indent = line[:len(line) - len(line.lstrip())]
            lines.append(indent + "content: '*';")
        else:
            lines.append(line)
css.write_text('\n'.join(lines) + '\n', encoding='utf-8')

parser = Path('backend/finagent/earnings/parser.py')
text = parser.read_text(encoding='utf-8')
lines = []
for line in text.splitlines():
    if 'Rs Crores' in line:
        lines.append('      Rs Crores    -> scale = 1.0   (most common for large companies)')
    elif 'Rs Millions' in line:
        lines.append('      Rs Millions  -> scale = 0.1   (1 Crore = 10 Millions)')
    elif 'Rs Lakhs' in line:
        lines.append('      Rs Lakhs     -> scale = 0.01  (1 Crore = 100 Lakhs)')
    elif 'Check for millions' in line:
        lines.append('    # Check for millions - must be specific enough to not collide with "crore"')
    elif 'in millions' in line and ('â' in line or 'Ã' in line or '�' in line):
        lines.append('        "rs in millions", "in millions", "rs. mn", "rs mn",')
    elif 'in lakhs' in line and ('â' in line or 'Ã' in line or '�' in line):
        lines.append('        "rs in lakhs", "in lakhs", "rs. lacs", "rs lacs",')
    elif 'Indian financial reporting' in line:
        lines.append('        # Indian financial reporting - year-to-date patterns')
    elif 'not a header row' in line:
        lines.append('        return []  # not a header row - no filtering')
    else:
        lines.append(line)
parser.write_text('\n'.join(lines) + '\n', encoding='utf-8')

service = Path('backend/finagent/earnings/service.py')
text = service.read_text(encoding='utf-8')
lines = []
for line in text.splitlines():
    if 'Yahoo-sourced history row matching' in line:
        lines.append('    """Return the Yahoo-sourced history row matching the given earnings date (+/-3 days).')
    elif 'Cross-validate:' in line:
        lines.append('    Cross-validate: if extracted_revenue / xbrl_revenue is ~10 -> divide by 10.')
    elif 'Detect unit mismatch:' in line:
        lines.append('    # Detect unit mismatch: 8-12x = Rs Millions; 80-120x = Rs Lakhs')
    elif 'Unit correction for %s: extracted revenue %.1f Cr is ~10x' in line:
        lines.append('            "Unit correction for %s: extracted revenue %.1f Cr is ~10x XBRL %.1f Cr -> applying /10 (Rs Millions)",')
    elif 'Unit correction for %s: extracted revenue %.1f Cr is ~100x' in line:
        lines.append('            "Unit correction for %s: extracted revenue %.1f Cr is ~100x XBRL %.1f Cr -> applying /100 (Rs Lakhs)",')
    else:
        lines.append(line)
service.write_text('\n'.join(lines) + '\n', encoding='utf-8')
