---
title: Live-LLM integration tests target a local OpenAI-compatible server (LM Studio
  / Ollama), run only on the developer machine, not CI -- to keep test cost at zero
type: decision
created: '2026-06-10T11:12:54Z'
modified: '2026-06-10T11:12:54Z'
related:
- 0184-local-ai-lm-studio-support-keyless-openai.md
- 0197-redirecting-koans-agent-spawn-to.md
- 0065-prefer-real-integratione2e-tests-over-mocks-one.md
- 0185-run-koans-standard-test-suite-with-bare-pytest-no.md
---

koan's test suite includes integration tests that exercise a real LLM end-to-end (for example `tests/test_pydantic_ai_agent.py::test_live_gemini_intake_turn_advances_step`, which drives one real intake turn through the agent loop). On 2026-06-10 Leon established the standing rule that such live-LLM integration tests should target a LOCAL OpenAI-compatible LLM server -- LM Studio (koan's keyless `lmstudio` connection type) or Ollama via its OpenAI-compatible endpoint -- rather than a paid cloud provider (Anthropic/OpenAI/Google/Bedrock), because local inference is free and keeps test cost at zero. These tests are expected to run only on Leon's local machine; they do not need to run in CI.

Rationale: gating a live test on a cloud key (e.g. `GOOGLE_API_KEY` / `GEMINI_API_KEY`) makes every local run with a key present cost real money, and running such tests in CI would multiply that cost on every push. Leon characterized the local-LLM approach as "not the best" -- a local model is weaker than a frontier cloud model, so the test exercises the plumbing (spawn path, credential resolution, tool wiring) more than model quality -- but the most pragmatic way to keep costs under control. Alternatives rejected: paid cloud-provider live tests run in CI (recurring per-run cost multiplied across CI); deleting live integration tests entirely (loses end-to-end plumbing coverage that mocked unit tests cannot give).
