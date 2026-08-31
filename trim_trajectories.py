"""
One-time trajectory cleanup: removes development-testing debris (random-hex
trajectory files from live-app testing) and trims each repo_N.jsonl down to
its last complete run, removing the dozen-plus stacked re-runs accumulated
across tonight's debugging.

Run once from the project root: python trim_trajectories.py
"""

import glob
import json
import os

TRAJ_DIR = "trajectories"


def main():
    all_files = glob.glob(os.path.join(TRAJ_DIR, "*.jsonl"))
    repo_files = [f for f in all_files if os.path.basename(f).startswith("repo_")]
    debris_files = [f for f in all_files if f not in repo_files]

    print(f"Found {len(repo_files)} eval-set trajectory file(s), "
          f"{len(debris_files)} development-testing debris file(s).\n")

    for f in debris_files:
        size = os.path.getsize(f)
        os.remove(f)
        print(f"Deleted debris: {f} ({size} bytes)")

    print()
    for f in sorted(repo_files):
        with open(f, "r", encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]

        last_start = None
        for i, entry in enumerate(lines):
            if entry.get("step") == 1:
                last_start = i

        if last_start is None:
            print(f"SKIPPED {f}: no 'step: 1' marker found, leaving as-is")
            continue

        trimmed = lines[last_start:]
        original_size = os.path.getsize(f)

        with open(f, "w", encoding="utf-8") as fh:
            for entry in trimmed:
                fh.write(json.dumps(entry) + "\n")

        new_size = os.path.getsize(f)
        print(f"{f}: {len(lines)} lines ({original_size} bytes) -> "
              f"{len(trimmed)} lines ({new_size} bytes)")

    print("\nDone.")


if __name__ == "__main__":
    main()
