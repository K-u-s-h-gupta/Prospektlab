import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open('finagent/gateway/widget.html', 'r', encoding='utf-8') as f:
    content = f.read()

ids_to_check = ['stopBtn', 'executeBtn', 'targetInput', 'heroTitle', 'processingTarget',
                'processingTitle', 'processingPhaseLabel', 'processingBar', 'processingPercent',
                'stateProcessing', 'stateCommand', 'stateResult', 'memoViaPill',
                'resultBreadcrumb', 'resultTitle', 'chatThread', 'memoBody']

for eid in ids_to_check:
    html_def = f'id="{eid}"' in content
    js_ref = f'$("{eid}")' in content
    print(f'{eid}: HTML_defined={html_def}, JS_referenced={js_ref}')
    if js_ref and not html_def:
        print(f'  *** MISSING HTML ELEMENT: {eid} is referenced in JS but NOT defined in HTML ***')
