import json
from pathlib import Path
from vera.composer import compose

cases = json.loads(Path('examples/compose-anchor-pairs.json').read_text(encoding='utf-8'))
for i, case in enumerate(cases, 1):
    result = compose(category=case['input']['category'], merchant=case['input']['merchant'], trigger=case['input']['trigger'], customer=case['input'].get('customer'))
    print('CASE', i, case['description'])
    print('EXPECTED:', case['output']['body'])
    print('ACTUAL  :', result.body)
    print('---')
