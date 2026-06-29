---
title: A dog-fooded koan orchestrator can run an older phase graph than the working
  tree the executor edits
type: context
created: '2026-06-29T08:49:12Z'
modified: '2026-06-29T08:49:12Z'
---

koan is developed by running koan on itself, which can put the running orchestrator process on a different, older version of the source than the working tree the spawned executor edits. In one such run the running server exposed an older phase vocabulary -- separate review phases (`tech-plan-spec`, `tech-plan-review`, `milestone-spec`, `milestone-review`, `plan-spec`, `plan-review`, `execute`, `exec-review`) -- while the on-disk working tree had the later collapsed phase set (`intake`, `core-flows`, `tech-plan`, `milestone`, `plan`, `execute`, `curation`, with review folded into a mechanical reviewer). The mismatch surfaced when `koan_set_phase("tech-plan")` was rejected because the running workflow only knew `tech-plan-spec`. This matters because the orchestrator must navigate phase transitions using the RUNNING harness's phase names (read them off the rejection error's available-phases list), while every plan and artifact it writes must target the WORKING TREE the executor actually modifies -- the two views of koan can disagree on phase names, guidance text, and structure.
