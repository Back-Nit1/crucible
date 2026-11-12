"""Summarize saved model failures without making model or catalog calls."""
import json
from collections import Counter
from pathlib import Path


def summarize(root: Path) -> dict:
    files = sorted((root / 'episodes').glob('*/*.json'))
    terminations, kills = Counter(), Counter()
    for path in files:
        episode = json.loads(path.read_text())['episode']
        terminations[episode['termination']] += 1
        kills.update(item['rule_id'] for item in episode['kill_information'])
    return {'records': len(files), 'terminations': dict(terminations), 'kill_rules': dict(kills)}


if __name__ == '__main__':
    print(json.dumps({name: summarize(Path('checkpoints/evaluations') / name)
                      for name in ('eval-20261110-base', 'pilot-v6-state-tools')}, indent=2))
