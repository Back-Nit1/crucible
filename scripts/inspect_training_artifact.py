"""Verify and summarize a trained adapter artifact (no network, no GPU).

  uv run python -m scripts.inspect_training_artifact <artifact_manifest.json> [--adapter-dir <final/>]

Exit 0 = the manifest is internally consistent (sealed hash, adapter hash, step/segment arithmetic) and, if --adapter-dir
is given, every adapter file on disk matches. Exit 1 = anything else; the reason code is printed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modal_app.adapter_artifact import ArtifactError, load_manifest, verify_adapter_dir
from training.checkpoints import artifact_ref


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--adapter-dir", type=Path)
    a = ap.parse_args(argv)
    try:
        m = load_manifest(a.manifest)
        if a.adapter_dir:
            verify_adapter_dir(m, a.adapter_dir)
    except ArtifactError as exc:
        print(json.dumps({"verified": False, "code": exc.code}))
        return 1
    print(json.dumps({"verified": True, "adapter_files_checked": bool(a.adapter_dir), "checkpoint_id": m.checkpoint_id,
                      "artifact_ref": artifact_ref(m), "run_id": m.run_id, "base_model": m.base_model,
                      "base_revision": m.base_revision, "adapter_hash": m.adapter_hash,
                      "training_manifest_hash": m.training_manifest_hash, "dataset_hash": m.dataset_hash,
                      "data_source_model_version": m.data_source_model_version,
                      "steps": f"{m.steps_completed}/{m.total_steps}", "epochs_completed": m.epochs_completed,
                      "launches": len(m.segments), "measured_duration_seconds": m.duration_seconds, "gpu": m.gpu,
                      "cost_usd": m.cost_usd, "cost_basis": m.cost_basis, "created_at": m.created_at.isoformat()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
