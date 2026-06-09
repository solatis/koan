---
title: 'Frontend submit-keybinding convention: multi-line textareas submit on Ctrl/Cmd+Return,
  single-line/chat inputs on plain Enter'
type: procedure
created: '2026-06-02T00:00:28Z'
modified: '2026-06-02T00:00:28Z'
---

Governs keyboard submit behavior for text-entry fields in the koan frontend (React, under frontend/src/components). Two complementary patterns are in use, distinguished by field shape. Single-line/chat inputs submit on plain Enter and reserve Shift+Enter for a newline: FeedbackInput (frontend/src/components/molecules/FeedbackInput.tsx) sends when `e.key === 'Enter' && !e.shiftKey`. Multi-line answer textareas submit on a Ctrl/Cmd+Return chord and leave plain Enter to insert a newline: the elicitation question card ElicitationPanel (frontend/src/components/organisms/ElicitationPanel.tsx) handles this with a delegated keydown on its `.ep-panel--decision` container, firing when `e.key === 'Enter' && (e.ctrlKey || e.metaKey)` and the event target is a `<textarea>` (the free-text field, or an "Other (type your own)" answer field in RadioOption/CheckboxOption), then calling the same submit path as the primary button (advance to the next question, or finalize on the last). When adding or modifying a text-entry field, pick the pattern by shape: a multi-line textarea keeps plain Enter for newlines and moves submission to the chord; a single-line/chat field submits on plain Enter. Accept BOTH ctrlKey and metaKey for the chord rather than Ctrl alone -- the maintainer (Leon) develops on macOS, where Cmd+Return is the conventional submit chord, and confirmed both modifiers should work when the elicitation answer fields were converted from single-line inputs to textareas. A single-modifier (Ctrl-only) chord makes the shortcut feel broken to macOS users.
