## §1. Foundations

The framework is grounded in four papers in this project corpus that address the same class of problem — machine generation of architectural diagrams from textual sources.

- **CIAO** (2604.08293) — generates system-level architecture documentation from GitHub repos using C4 + ISO/IEC/IEEE 42010 + SEI Views & Beyond.
- **MASC4** (2510.22787) — generates C4 (L1–L3) views from a _system brief_ via LLM agents. No source code; pure intent-to-diagram.
- **VisDocSketcher** (2509.11942) — generates Mermaid sketches from Jupyter notebooks via static analysis + LLM agents.
- **ArchView** (2603.21178) — evaluates LLM-generated architecture views across 340 repositories, by view type, granularity, and concern.

Of these, MASC4 is the closest analogue to Koan's setting because its source is a brief (intent), not source code. CIAO covers the doc-template / section-prompt structure most rigorously. VisDocSketcher is the only paper that uses Mermaid specifically. ArchView provides empirical guidance on which view types are amenable to automated generation.

Three foundational choices fall directly out of the literature:

> "The C4 model … provided a four-level hierarchy, Context (L1), Container (L2), Component (L3), and Code (L4), that is widely used for structuring developer-oriented documentation." — CIAO

> "Mermaid enables the creation of structured diagrams … This format is particularly well-suited for automated generation and reproducible documentation, as it allows diagrams to be rendered programmatically without manual graphical editing." — VisDocSketcher

> "To keep the study's scope firmly on architectural reasoning, we focus on the first three levels of the C4 model. Generating code-level (L4) diagrams would require a larger experimental platform and additional evaluation metrics beyond our current framework." — MASC4

Hence: **C4 levels 1–3 as the abstraction model, Mermaid as the notation, defer L4.**

---

## §2. The decision Koan removes from the LLM

The naive framing — "the LLM decides when to add a diagram" — is the wrong primitive. Every paper that succeeded at this task removed that decision from the LLM and pushed it into the document template:

> "Each prompt consists of (i) a global prompt, shared across all sections, which defines the LLM's role, target audience, writing style, and grounding requirements; and (ii) a section-specific prompt, instantiated from the documentation template and tailored to the goal and expected artifacts of that section." — CIAO

> "We employ a schema-guided zero-shot prompting strategy. Rather than providing solved input-output examples (a few-shot approach), the prompt gives the model a detailed set of instructions and a structural template or syntax guide, constraining the output to the desired format." — MASC4

The framework therefore pins two decisions in templates and removes them from the orchestrator:

1. **Whether** a diagram appears at all in a given location.
2. **What kind** of diagram appears.

What remains for the LLM:

- **Selection of instances** — which specific components, containers, actors, or steps populate the slot.
- **Suppression** — render the slot as prose when complexity is below a defined threshold (see §5).

This is the most important single move in the framework. It reflects the project's stated constraint that diagrams support process and are not the deliverable, and it removes the largest source of variance in the output.

---

## §3. Diagram type catalog

The framework supports five Mermaid diagram types. Selection is constrained by ArchView's quantitative finding:

> "Control flow and data flow achieved balanced performance across both SSIM and LLM quality, making them most reliable for automated view generation. … General documentation failed both visually and semantically." — ArchView

| ID  | Mermaid type                  | Concern                                                 | C4 level        |
| --- | ----------------------------- | ------------------------------------------------------- | --------------- |
| CTX | `flowchart`                   | System boundaries, external actors, external systems    | L1 (Context)    |
| CON | `flowchart`                   | Runtime building blocks and their connections           | L2 (Container)  |
| CMP | `classDiagram` or `flowchart` | Internal modules of one container, structural relations | L3 (Component)  |
| SEQ | `sequenceDiagram`             | Interaction over time across components or actors       | crosses L2 / L3 |
| STT | `stateDiagram-v2`             | Lifecycle of an entity with non-trivial transitions     | orthogonal      |

### What is deliberately not in the catalog

- **No deployment diagrams.** ArchView reports that "concerns requiring deeper reasoning about variability such as Deployment and Performance necessitated the Custom-built (AV) for best results" — the regime where automated quality drops sharply. Defer.
- **No package / dependency diagrams.** Already classified by the project as obvious-but-low-value. The corpus offers no counter-evidence; none of the surveyed approaches treats them as a primary view.
- **No ER diagrams.** Data models in Koan documents are expressed as code-fenced schema definitions. Rendering them as ER on top adds notation cost without comprehension gain. (MAAD does generate them, but inside the 4+1 view model, not C4.)
- **No code-level (L4) diagrams.** MASC4 explicitly defers them; below Component, the artifact is the code itself.

### CMP type choice: classDiagram vs. flowchart

ArchView's notation finding generalizes to a notation-richness question:

> "Notation complexity analysis revealed performance improved with richer notation: simple 'boxes' achieved SSIM 0.54 while complex 'boxes and arrows, icons and arrows' reached SSIM 0.74." — ArchView

For component views with explicit interface contracts (classes, services with named ports), use `classDiagram`. For component views where the interesting structure is flow rather than membership, use `flowchart` with stereotyped node shapes (`A[(database)]`, `B[/queue/]`, `C{{service}}`). Pick one per document; do not mix within a single diagram.

---

## §4. Document-to-slot mapping

The framework's deterministic core: for each Koan document type, an explicit set of diagram slots. Each slot is tied to a diagram ID from §3.

The mapping below uses Traycer-aligned document names, since Koan's structure is Traycer-inspired. Substitute names where they differ.

| Document      | Section / slot                         | Diagram ID                 | Required?                           |
| ------------- | -------------------------------------- | -------------------------- | ----------------------------------- |
| Epic Brief    | (none)                                 | —                          | —                                   |
| Core Flows    | per-flow: Interaction                  | SEQ                        | required (default)                  |
| Tech Plan     | Architectural Approach                 | CON                        | required (default)                  |
| Tech Plan     | Component Architecture: per-component  | CMP                        | required for ≥1 component (default) |
| Tech Plan     | Cross-component flows                  | SEQ                        | required for non-trivial flows      |
| Tech Plan     | Per-entity lifecycle (when applicable) | STT                        | conditional on §5 threshold         |
| Ticket        | (none)                                 | —                          | —                                   |
| Ticket Bundle | Dependency overview                    | `flowchart` (chain or DAG) | required when ≥3 tickets            |

**Epic Brief intentionally has no diagram.** It is intent-level, three-to-eight sentences. ArchView's "General documentation failed" finding applies most strongly here: the higher the abstraction and the more catch-all the slot, the more semantic noise an automated diagram introduces.

**Tickets intentionally have no diagram.** They are unit-of-work specs; the relevant visualization is the bundle-level dependency overview.

**State diagrams are not pinned to a default slot** in the Tech Plan structure. They appear only when the plan describes an entity with a non-trivial lifecycle (≥3 states with conditional transitions). When that condition holds, the orchestrator inserts an STT slot into the relevant component subsection.

**Context (CTX) is not currently pinned to a slot in this mapping.** This is a deliberate choice: in koan's typical setting (orchestrator working inside an existing codebase against a well-scoped change), system context is usually established by the codebase itself and the brief. Promote CTX to a Tech Plan slot only if/when greenfield workflows become common.

---

## §5. Suppression rules

A slot is rendered as prose only when its complexity falls below a measurable threshold. These thresholds exist to handle trivial cases without forcing the LLM into a judgment call.

These thresholds are an **extension of the framework**, not citations from the corpus. VisDocSketcher's input-complexity analysis motivates the principle (notebooks "with varying lengths and structural complexity" produce sketches of varying quality) but does not give numbers.

| Slot              | Suppress when                                                          |
| ----------------- | ---------------------------------------------------------------------- |
| CTX               | Fewer than 3 external actors / systems referenced                      |
| CON               | Single container, or 2 containers with one connection                  |
| CMP               | Fewer than 4 components in scope for the container                     |
| SEQ               | 2 actors, fewer than 4 messages, no branching                          |
| STT               | Fewer than 3 states, or no guards / conditional transitions            |
| Ticket bundle dep | Fewer than 3 tickets, or pure linear chain expressible in one sentence |

When a slot is suppressed, the orchestrator writes the same information as prose at the slot's location. The slot is never silently skipped, but it is also never marked as suppressed -- the prose stands on its own. Do NOT emit any "diagram suppressed" comment, banner, or placeholder; the rendered output should look exactly like normal prose.

---

## §6. LLM prompt scaffold

Each diagram slot is generated by a prompt with five fixed parts. The structure is taken almost directly from MASC4 (Persona + Task + Context) and CIAO (global + section-specific):

1. **Role / persona.** A one-sentence positioning. Example: _"You are a software architect documenting the runtime structure of a system-in-design."_
2. **Task.** The diagram ID, the concern, and the audience. Example: _"Produce a Mermaid `flowchart` diagram (CON, L2 Container view) for the audience of an engineer who will implement against this plan."_
3. **Inputs / context.** A bounded set of inputs the LLM may draw from (Epic Brief, Core Flows, codebase analysis notes). MASC4 calls this `C(s)`; CIAO calls it the _Flattened Repository_.
4. **Output schema.** A Mermaid syntax skeleton with placeholders, plus structural constraints (max nodes, allowed edge labels, allowed node shapes, suppression marker).
5. **Grounding rule.** Verbatim from CIAO's design intent: _"evidence-grounded generation requirements and explicitly forbid inventing architectural elements not present in the repository."_ For Koan: forbid introducing components, actors, or states that do not appear in the bounded inputs.

### Concrete example: the CON slot in a Tech Plan

```text
[Role]
You are a software architect documenting the runtime structure of a system-in-design.

[Task]
Produce a Mermaid `flowchart LR` diagram for the L2 Container view of the proposed system.
The audience is an engineer who will implement against this plan and needs to understand
which runtime processes/services exist and how they communicate.

[Inputs]
You may use ONLY the following:
- Epic Brief (full text)
- Core Flows (full text)
- Codebase analysis notes from this run (full text)

[Output schema]
- Use `flowchart LR`.
- Nodes: each is a runtime container (a process, service, or data store) introduced or
  modified by this plan.
  - Use shape conventions:
    - `name[Service]` for services / processes
    - `name[(Datastore)]` for databases and persistent stores
    - `name[/Queue/]` for queues, topics, streams
    - `name((External))` for external systems outside the plan's scope
- Edges: directed; label with the protocol or message type (HTTP, gRPC, SQL, file, IPC, etc.).
- Constraints:
  - Maximum 8 nodes. If more would be needed, group by responsibility and emit a higher-level
    view rather than expanding.
  - Show only direct connections. No transitive dependencies.
  - Do NOT include unchanged containers unless they appear as an external dependency of a
    changed container.

[Grounding rule]
Do NOT introduce containers, services, or data stores that are not named or directly implied
by the inputs. If the inputs do not yield at least 3 containers, emit a single-sentence prose
description in place of the diagram. Do not emit any "diagram suppressed" marker or
placeholder text -- the prose alone is the slot.
```

The same five-part scaffold is reused for every diagram ID. Only [Task] and [Output schema] vary across slots.

### What is deliberately not in the scaffold

- **No few-shot examples.** MASC4 chose schema-guided zero-shot over few-shot for this exact task and reported high compilation success across LLMs. Few-shot examples for diagrams either over-anchor the LLM to the example's domain or bloat the prompt unproductively.
- **No intermediate file format (no YAML / JSON / DSL artifact).** Per project decision: structuring intermediate thought is a prompting question, not a file-format question. The schema goes inside the prompt; the LLM emits Mermaid directly.
- **No "decide whether to draw" step.** Suppression is mechanical (count-based, see §5). The LLM never gets a should-I prompt for diagrams.
- **No glossary.** Per project decision: orchestrator is single-agent and ephemeral.

---

## §7. Anti-patterns

These are failure modes the corpus reports and the framework's structure prevents.

- **The "general documentation" diagram.** A flowchart that summarizes "the system overall." ArchView reports this as the lowest-quality view type. The framework forbids it: every slot has a specific concern (CTX, CON, CMP, SEQ, STT) and a specific abstraction level.
- **Hallucinated components.** CIAO's grounding rule (§6, step 5) is the explicit defense. Output validation should reject any diagram whose nodes include identifiers absent from the inputs.
- **Cross-level mixing.** Showing services and classes in the same diagram. C4's whole value is level separation. The output schemas in §6 disallow this per slot.
- **Notation drift across artifacts.** ArchView reports that the "formal-semiformal notation gap limits practical applicability." The framework pins one diagram type per slot; the orchestrator never switches notation within a document.
- **Diagrams as deliverables.** The framework's slot model treats diagrams as part of a document section, never as a standalone artifact. There is no "diagrams.md" in any document type.

---

## §8. Mermaid syntax hazards

Mermaid's `sequenceDiagram` grammar treats certain punctuation as statement
separators or syntax tokens. These traps appear when LLM-generated content
embeds them in Note bodies or message labels.

- **Do not use `;` inside `Note over` / `Note left of` / `Note right of`
  bodies, or inside message labels (after the `:` in `A->>B: text`).** Mermaid
  treats `;` as a statement separator, terminating the current statement
  mid-sentence and breaking the parser on the next token. Use `,`, `--`, or
  rephrase with two separate Notes.
- **For multi-line Notes, use the `<br>` HTML break tag rather than embedding
  a raw newline in the body.** Mermaid sequenceDiagram does not parse
  multi-line Note bodies across raw newlines; `<br>` is the canonical
  line-break mechanism inside Note text.

Example:

```
# Bad -- semicolon terminates the Note mid-sentence
Note over A, B: Two unrelated entry points; mutually exclusive per agent

# Good -- replace with comma or em-dash equivalent
Note over A, B: Two unrelated entry points -- mutually exclusive per agent

# Good -- multi-line via <br>
Note over A, B: Two unrelated entry points<br>Mutually exclusive per agent
```

See the [Mermaid sequence-diagram syntax docs](https://mermaid.js.org/syntax/sequenceDiagram.html)
for the full grammar.

---

## §9. Out of scope

These are deferred or explicitly not pursued, and named here so they are not silently re-litigated.

- **Evaluation metrics and eval harness wire-up.** Deferred; tracked separately as the eval task that is on the horizon for koan.
- **Glossary / shared vocabulary across documents.** Not needed in single-agent ephemeral orchestrator settings.
- **Code-level (L4) diagrams.** MASC4 defers; the framework defers.
- **Deployment diagrams.** ArchView reports automated quality drops; defer.
- **ER diagrams.** Data model is expressed as schema in fenced code blocks.
- **Non-Mermaid notations (PlantUML, DOT, Graphviz, ASCII art).** All require external rendering. Mermaid renders inline in markdown.
- **Auto-update of diagrams as the underlying documents change.** The current scope is generation at document-creation time. Re-generation on doc edit is a separate workflow concern.

---

## §10. Summary of the four key constraints

For an at-a-glance reference when prompting the orchestrator or reviewing its output:

1. **Levels.** C4 L1–L3. No L4.
2. **Notation.** Mermaid only.
3. **Decision authority.** Templates decide _whether_ and _what type_. The LLM decides _which instances_ and _whether the slot is below the suppression threshold_.
4. **Grounding.** No component, actor, or state in any diagram may appear that is not in the bounded inputs.
