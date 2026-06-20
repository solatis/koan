---
title: koan's agent layer is one native PydanticAI abstraction over direct provider
  APIs (Anthropic/OpenAI/Google/Bedrock), not provider SDKs or CLIs
type: decision
created: '2026-06-04T14:11:25Z'
modified: '2026-06-20T00:15:29Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan's agent layer (`koan/agents/`, with `PydanticAIAgent` implementing the `Agent` protocol) reaches large-model providers through a single PydanticAI-based abstraction that speaks each provider's API directly -- Anthropic, OpenAI, Google/Gemini, and AWS Bedrock, all four as first-class targets (on Bedrock, only Claude and OpenAI model families are in scope). Leon chose direct-API-over-one-abstraction because the acceptable-use and subscription terms of the vendor agent tools koan had been built on -- the Claude Agent SDK and the codex/gemini provider CLIs -- were tightening across vendors in ways that put koan's automated, programmatic orchestration on the wrong side of those terms; continued reliance on subscription-gated SDKs and CLIs was therefore both a permission-to-operate risk and a billing-continuity risk. Routing every provider through pay-as-you-go direct APIs under one abstraction removes that exposure and avoids chasing each vendor's SDK quirks. Alternative rejected: per-provider SDK/CLI adapters, which keep the terms-of-service and billing exposure and force koan to track each provider's idiosyncrasies. The cutover is hard -- koan maintains no parallel legacy agent backend, accepting a non-shippable window over dual-maintenance of two agent paths.
