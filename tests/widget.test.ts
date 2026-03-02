import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ExtensionUIContext, Theme } from "@mariozechner/pi-coding-agent";
import { visibleWidth } from "@mariozechner/pi-tui";

import { WidgetController, formatPlanningHeaderLabel } from "../src/planner/ui/widget.js";

type WidgetInstance = {
  render: (width: number) => string[];
  invalidate: () => void;
};

type WidgetFactory = ((tui: unknown, theme: Theme) => WidgetInstance) | undefined;

function createPlainTheme(): Theme {
  return {
    fg: (_color: string, text: string) => text,
    bg: (_color: string, text: string) => text,
    bold: (text: string) => text,
  } as unknown as Theme;
}

function createWidgetHarness(): {
  controller: WidgetController;
  render: (width: number) => string[];
  destroy: () => void;
} {
  const theme = createPlainTheme();
  let factory: WidgetFactory;

  const ui = {
    theme,
    setWidget: (_key: string, next: WidgetFactory) => {
      factory = next;
    },
  } as unknown as ExtensionUIContext;

  const controller = new WidgetController(ui, "plan-test-id");

  return {
    controller,
    render: (width: number) => {
      assert.ok(factory, "widget factory should be registered");
      return factory({} as unknown, theme).render(width);
    },
    destroy: () => controller.destroy(),
  };
}

describe("formatPlanningHeaderLabel", () => {
  it("applies compaction in deterministic order", () => {
    const phase = "Plan design";
    const status = "CURRENT";

    const full = `Planning · ${phase} · ${status}`;
    const shortStatus = `Planning · ${phase} · CUR`;
    const noStatus = `Planning · ${phase}`;
    const shortPhase = "Planning · Design";

    assert.equal(formatPlanningHeaderLabel(phase, status, visibleWidth(full)), full);
    assert.equal(formatPlanningHeaderLabel(phase, status, visibleWidth(full) - 1), shortStatus);
    assert.equal(formatPlanningHeaderLabel(phase, status, visibleWidth(shortStatus) - 1), noStatus);
    assert.equal(formatPlanningHeaderLabel(phase, status, visibleWidth(noStatus) - 1), shortPhase);

    const tiny = formatPlanningHeaderLabel(phase, status, 14);
    assert.ok(visibleWidth(tiny) <= 14);
    assert.ok(tiny.startsWith("Planning"));
  });
});

describe("WidgetController rendering", () => {
  it("renders metadata header with 3-phase layout (no context gathering)", () => {
    const harness = createWidgetHarness();
    try {
      const lines = harness.render(140);
      const text = lines.join("\n");

      assert.match(text, /Planning · Plan design · CURRENT/);
      assert.doesNotMatch(text, /Context gathering/);
      assert.doesNotMatch(text, /┃ Context gathering ┃/);
    } finally {
      harness.destroy();
    }
  });

  it("aligns identity table separator using dynamic key width", () => {
    const harness = createWidgetHarness();
    try {
      harness.controller.update({
        subagentRole: "reviewer",
        subagentParallelCount: 12,
        subagentModel: "openai-codex/gpt-5.3-codex",
      });

      const lines = harness.render(140);
      const planLine = lines.find((line) => line.includes("Plan ID") && line.includes(" : "));
      const agentLine = lines.find((line) => line.includes("Agent pool") && line.includes(" : "));
      const modelLine = lines.find((line) => line.includes("Model") && line.includes(" : "));

      assert.ok(planLine, "expected Plan ID row");
      assert.ok(agentLine, "expected Agent pool row");
      assert.ok(modelLine, "expected Model row");

      const planSep = planLine.indexOf(" : ");
      const agentSep = agentLine.indexOf(" : ");
      const modelSep = modelLine.indexOf(" : ");

      assert.equal(planSep, agentSep);
      assert.equal(agentSep, modelSep);
    } finally {
      harness.destroy();
    }
  });
});
