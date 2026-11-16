"""Read-only P1 task budget audit against the configured frozen catalog."""
import json
from pathlib import Path
from scripts._env import load
from scripts.run_evaluation import _catalog,ELASTIC
from tasks.schemas import TaskSpec
def main():
    load('.env',ELASTIC)
    cat,_=_catalog(None)
    tasks=[TaskSpec.model_validate_json(line) for name in ['protected','reference'] for line in Path(f'docs/evaluations/taskset-20261110/{name}.jsonl').read_text().splitlines()]
    products={}
    for t in tasks:
     c=t.hard_constraints.category
     if c not in products: products[c]=list(cat.iter_products(c,t.catalog_manifest_hash))
    out=[]
    for t in tasks:
     ps=products[t.hard_constraints.category]; minimum=min(p.price for p in ps)
     out.append(dict(task_id=t.id,split=str(t.split),budget=str(t.hard_constraints.max_total),minimum_price=str(minimum),budget_below_all_prices=t.hard_constraints.max_total<minimum,is_impossible=t.is_impossible,feasible_count=len(t.feasible_set)))
    Path('docs/evaluations/p1-budget-audit.json').write_text(json.dumps(out,indent=2)+'\n')
    print('tasks',len(out),'below minimum',sum(x['budget_below_all_prices'] for x in out),'unmarked impossible',sum(x['budget_below_all_prices'] and not x['is_impossible'] for x in out))


if __name__ == "__main__":
    main()
