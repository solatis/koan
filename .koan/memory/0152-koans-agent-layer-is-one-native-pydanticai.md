---
title: koan's agent layer is one native PydanticAI abstraction over direct provider
  APIs (Anthropic/OpenAI/Google/Bedrock), not provider SDKs or CLIs
type: decision
created: '2026-06-04T14:11:25Z'
modified: '2026-06-04T14:11:25Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

koan's agent layer (`koan/agents/`, with `PydanticAIAgent` implementing the `Agent` protocol) reaches large-model providers through a single PydanticAI-based abstraction that speaks each provider's API directly -- Anthropic, OpenAI, Google/Gemini, and AWS Bedrock, all four as first-class targets (on Bedrock, only Claude and OpenAI model families are in scope). Leon chose direct-API-over-one-abstraction because provider subscription terms tightened across vendors, making an agent layer built on subscription-gated provider SDKs and CLIs a billing-continuity risk; routing every provider through direct API under one abstraction removes that exposure and avoids chasing each vendor's SDK quirks. Alternative rejected: per-provider SDK/CLI adapters, which keep the subscription billing risk and force koan to track each provider's idiosyncrasies. The cutover is hard -- koan maintains no parallel legacy agent backend, accepting a non-shippable window over dual-maintenance of two agent paths.
