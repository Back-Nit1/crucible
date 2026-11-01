"""Register the pinned base checkpoint in the Elastic `checkpoints` index (idempotent). Evaluations are published by
scripts.run_generation for measured model runs; trained checkpoints can only be added with a real artifact reference.
  uv run python -m scripts.publish_models --env-file <.env>"""
import argparse
import datetime as dt
import os
import sys

from scripts._env import load


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file")
    a = ap.parse_args(argv)
    if a.env_file:
        load(a.env_file, {"ELASTIC_API_KEY", "ELASTIC_ENDPOINT", "ELASTIC_CLOUD_ID"})
    from catalog.providers.elastic import Elastic, endpoint_from_cloud_id
    from eval.publish import checkpoint_doc, publish
    from modal_app.qwen_toolcalls import MODEL_ID, MODEL_REVISION
    es = Elastic(os.environ.get("ELASTIC_ENDPOINT") or endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]))
    n = publish(es, "checkpoints", [checkpoint_doc(checkpoint_id="qwen-base", base_model=MODEL_ID, base_revision=MODEL_REVISION,
                                                   created_at=dt.datetime(2026, 10, 31, tzinfo=dt.UTC))])
    print(f"published {n} checkpoint record(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
