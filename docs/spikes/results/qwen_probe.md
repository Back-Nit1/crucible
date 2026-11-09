# Qwen bounded probe: passed

Model `Qwen/Qwen2.5-7B-Instruct@a09a354` checkpoint `qwen-base`, 20 prompts, first turn.

| Metric | Result |
|---|---|
| valid_structured_call | 20/20 |
| schema_valid_arguments | 19/20 |
| parse_intent_first | 19/20 |
| first_attempt_valid | 19/20 |
| malformed | 1/20 |
| inference_errors | 0/20 |
| retries | 1 |
| tokens | {'prompt': 32016, 'completion': 1605, 'measured_over': 19} |
| latency ms | {'mean': 5141.7, 'p50': 5108.0, 'p95': 7409.0, 'max': 7409.0, 'measured_over': 19} |
| cost usd | {'total': '0.033903', 'per_prompt': '0.00169515', 'known': True, 'ceiling': '0.861948', 'ceiling_exceeded': False, 'basis': 'measured generation seconds x Modal list rates (estimate; Modal billing is the truth)'} |

Pass bar (proposed): {'valid_structured_call': 0.9, 'schema_valid_arguments': 0.9, 'parse_intent_first': 0.9}
