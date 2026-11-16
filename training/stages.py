"""Loop stage names, in order. Kept import-light so the read-only API can use them without pulling in the GPU gates."""
STAGES = ("generate", "curate", "audit", "plan", "train", "evaluate", "reenter")
