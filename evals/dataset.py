# evals/dataset.py
# Loads benchmark fixtures as an Inspect AI MemoryDataset.
#
# Each fixture directory must contain task.md (the task description).
# snapshot.tar.gz is optional at load time (the solver checks at run time).
# The snapshot is a `git archive` of the project, so .koan/memory/*.md rides
# along inside it -- no separate memory/ directory. Directories without
# task.md are skipped silently.

from pathlib import Path

# Dataset is an abstract protocol in inspect_ai 0.3+; MemoryDataset is the
# concrete in-memory implementation.
from inspect_ai.dataset import MemoryDataset, Sample


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_dataset(fixtures_dir: Path = FIXTURES_DIR) -> MemoryDataset:
    """Return an Inspect AI MemoryDataset from all fixture directories."""
    samples = []
    for fixture_dir in sorted(fixtures_dir.iterdir()):
        task_file = fixture_dir / "task.md"
        if not fixture_dir.is_dir() or not task_file.exists():
            continue
        task_description = task_file.read_text(encoding="utf-8").strip()
        samples.append(Sample(
            input=task_description,
            metadata={
                "fixture_dir": str(fixture_dir),
                "fixture_name": fixture_dir.name,
                "snapshot_path": str(fixture_dir / "snapshot.tar.gz"),
            },
        ))
    return MemoryDataset(samples, name="koan-bench")
