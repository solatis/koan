# evals/dataset.py
# Loads benchmark fixtures as an Inspect AI MemoryDataset.
#
# Fixtures are enumerated by scanning fixtures/*/tasks/*/task.md.
# Each (fixture, task) pair becomes one Sample whose id is "<fixture>/<task>".
# snapshot.tar.gz is optional at load time; the solver checks at run time.
# Directories without a task.md are skipped silently.

from pathlib import Path

from inspect_ai.dataset import MemoryDataset, Sample


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_dataset(fixtures_dir: Path = FIXTURES_DIR) -> MemoryDataset:
    """Return an Inspect AI MemoryDataset from all fixture/task pairs."""
    samples = []
    for fixture_dir in sorted(fixtures_dir.iterdir()):
        if not fixture_dir.is_dir():
            continue
        tasks_dir = fixture_dir / "tasks"
        if not tasks_dir.is_dir():
            continue
        for task_dir in sorted(tasks_dir.iterdir()):
            task_file = task_dir / "task.md"
            if not task_dir.is_dir() or not task_file.exists():
                continue
            samples.append(Sample(
                input=task_file.read_text(encoding="utf-8").strip(),
                id=f"{fixture_dir.name}/{task_dir.name}",
                metadata={
                    "fixture_dir": str(fixture_dir),
                    "task_dir": str(task_dir),
                    "snapshot_path": str(fixture_dir / "snapshot.tar.gz"),
                    "fixture_name": fixture_dir.name,
                    "task_name": task_dir.name,
                },
            ))
    return MemoryDataset(samples, name="koan-bench")
