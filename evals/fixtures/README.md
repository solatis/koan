# Eval Fixtures

Each subdirectory is one benchmark fixture. Structure:

    <fixture-name>/
        task.md          -- task description (UTF-8 plain text)
        snapshot.tar.gz  -- git archive of the target project at a specific commit

`task.md` is a small text file and is committed normally.
`snapshot.tar.gz` is stored via git-lfs (see `.gitattributes`). Contributors
need `git lfs install` + `git lfs pull` to hydrate the tarballs; otherwise
the solver will fail with a "not a gzip file" error because the checkout
contains LFS pointer files instead of the real blobs.

The snapshot is a `git archive` of the project, so `.koan/memory/*.md` rides
along inside it. No separate memory copy is needed.

To capture a new fixture from the koan project itself:

    git archive HEAD --format=tar.gz -o evals/fixtures/<name>/snapshot.tar.gz
    printf 'Your task description\n' > evals/fixtures/<name>/task.md
