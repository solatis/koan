---
title: Live-LLM integration tests target a local OpenAI-compatible server (Ollama
  via an openai-type connection), run only on the developer machine and not CI, to
  keep test cost at zero
type: decision
created: '2026-06-10T11:12:54Z'
modified: '2026-06-14T10:06:41Z'
related:
- 0197-redirecting-koans-agent-spawn-to.md
- 0065-prefer-real-integratione2e-tests-over-mocks-one.md
- 0185-run-koans-standard-test-suite-with-bare-pytest-no.md
- 0218-koan-removed-lmstudio-support-but-retained-the.md
---

koan's test suite includes integration tests that exercise a real LLM end-to-end (for example `tests/test_pydantic_ai_agent.py::test_live_gemini_intake_turn_advances_step`, which drives one real intake turn through the agent loop). Leon established the standing rule that such live-LLM integration tests should target a LOCAL OpenAI-compatible LLM server rather than a paid cloud provider (Anthropic/OpenAI/Google/Bedrock), because local inference is free and keeps test cost at zero; these tests are expected to run only on his machine, not in CI. koan's dedicated `lmstudio` connection type was later removed, so the local target is now Ollama (or any OpenAI-compatible local server) reached through an `openai`-type connection with a `base_url` override; the former LM-Studio-only live e2e test was deleted rather than repointed. Rationale: gating a live test on a cloud key (e.g. `GOOGLE_API_KEY` / `GEMINI_API_KEY`) makes every local run with a key present cost real money, and CI would multiply that cost; a local model is weaker than a frontier cloud model, so the test exercises the plumbing (spawn path, credential resolution, tool wiring) more than model quality. Alternatives rejected: paid cloud-provider live tests run in CI (recurring per-run cost); deleting live integration tests entirely (loses end-to-end plumbing coverage that mocked unit tests cannot give).
