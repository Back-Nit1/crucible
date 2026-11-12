import json
from types import SimpleNamespace

from modal_app import qwen_service


def test_window_keeps_buyer_and_latest_pair_without_orphan_tools(monkeypatch):
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return json.dumps(messages)

        def __call__(self, text):
            return {'input_ids': list(text)}

    monkeypatch.setattr(qwen_service, 'MAX_INPUT_TOKENS', 220)
    request = SimpleNamespace(system='system', tools=[], messages=[
        {'role': 'user', 'content': 'buyer budget'},
        {'role': 'assistant', 'content': 'old' * 100},
        {'role': 'tool', 'content': 'old result'},
        {'role': 'assistant', 'content': 'latest'},
        {'role': 'tool', 'content': 'latest result'},
    ])
    original = list(request.messages)
    rendered = json.loads(qwen_service.render_prompt(Tokenizer(), request))
    assert [m['role'] for m in rendered] == ['system', 'user', 'assistant', 'tool']
    assert rendered[-1]['content'] == 'latest result'
    assert rendered[1]['content'] == 'buyer budget'
    assert request.messages == original
