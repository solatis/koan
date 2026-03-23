// Koan web UI HTTP server.
// Serves the single-page dashboard, pushes state via SSE, and receives
// user input via POST endpoints. One server per pipeline run; lifecycle
// owned by koan_plan.execute().

import http from "node:http";
import { promises as fs, readFileSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

import { readProjection, readRecentLogs } from "../lib/audit.js";
import { loadKoanConfig, loadModelTierConfig, saveModelTierConfig, saveScoutConcurrency, type ModelTierConfig } from "../model-config.js";
import type {
  WebServerHandle,
  AskQuestion,
  ReviewStory,
  ReviewResult,
  AnswerResult,
  AnswerElement,
  LogLine,
  IntakeProgressEvent,
  ArtifactReviewFeedback,
  TokenDeltaEvent,
} from "./server-types.js";
import type { ArtifactReviewPayload } from "../lib/ipc.js";
import type { EpicPhase, StoryStatus } from "../types.js";

// ---------------------------------------------------------------------------
// Static asset loading (at module init)
// ---------------------------------------------------------------------------

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadAsset(relativePath: string): string {
  try {
    return readFileSync(path.join(__dirname, relativePath), "utf8");
  } catch {
    return "";
  }
}

const HTML_TEMPLATE = loadAsset("html/index.html");

interface StaticAsset {
  content: string;
  mimeType: string;
}

// ---------------------------------------------------------------------------
// On-demand bundle build
// ---------------------------------------------------------------------------

async function ensureBundle(): Promise<void> {
  const entryPoint = path.join(__dirname, "js", "app.jsx");
  const outfile    = path.join(__dirname, "dist", "app.js");

  // Skip build if bundle exists and is newer than all source files
  try {
    const bundleStat = await fs.stat(outfile);
    const sourceDir  = path.join(__dirname, "js");
    const sourceFiles = await fs.readdir(sourceDir, { recursive: true });
    let newest = 0;
    for (const f of sourceFiles) {
      const s = await fs.stat(path.join(sourceDir, String(f)));
      if (s.mtimeMs > newest) newest = s.mtimeMs;
    }
    if (bundleStat.mtimeMs >= newest) return; // bundle is fresh
  } catch {
    // Bundle doesn't exist — build it
  }

  await fs.mkdir(path.join(__dirname, "dist"), { recursive: true });
  const esbuild = await import("esbuild");
  await esbuild.build({
    entryPoints: [entryPoint],
    bundle:      true,
    format:      "esm",
    jsx:         "automatic",
    jsxImportSource: "preact",
    alias: {
      "react":     "preact/compat",
      "react-dom": "preact/compat",
    },
    // Resolve aliases and node_modules from the koan package root, not
    // process.cwd(). Without this, running `pi -e .../koan/extensions/koan.ts`
    // from a different project directory fails because preact/compat is looked
    // up in that project's node_modules instead of koan's.
    absWorkingDir: path.resolve(__dirname, "../../.."),
    outfile,
    minify:      true,
  });
}

// ---------------------------------------------------------------------------
// Body parsing
// ---------------------------------------------------------------------------

const MAX_BODY_SIZE = 1_000_000;

function readBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    req.on("data", (chunk: Buffer) => {
      total += chunk.length;
      if (total > MAX_BODY_SIZE) {
        reject(new Error("Body too large"));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new Error("Invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res: http.ServerResponse, status: number, data: unknown): void {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function sendText(res: http.ServerResponse, status: number, text: string): void {
  res.writeHead(status, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(text);
}

function safeInlineJSON(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}

// ---------------------------------------------------------------------------
// Topic extraction from conversation.jsonl
// ---------------------------------------------------------------------------

async function extractTopic(epicDir: string): Promise<string | null> {
  try {
    const raw = await fs.readFile(path.join(epicDir, "conversation.jsonl"), "utf8");
    const lines = raw.trimEnd().split("\n").filter(Boolean);
    let lastUserContent: string | null = null;
    for (const line of lines) {
      try {
        const entry = JSON.parse(line) as { type?: string; role?: string; content?: unknown };
        if (entry.type === "message" && entry.role === "user") {
          const content = entry.content;
          if (typeof content === "string" && content.trim()) {
            lastUserContent = content.trim().slice(0, 200);
          } else if (Array.isArray(content)) {
            for (const block of content as Array<{ type?: string; text?: string }>) {
              if (block.type === "text" && block.text?.trim()) {
                lastUserContent = block.text.trim().slice(0, 200);
                break;
              }
            }
          }
        }
      } catch {
        // Skip malformed lines
      }
    }
    return lastUserContent;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Agent internal state
// ---------------------------------------------------------------------------

interface AgentInfoInternal {
  id: string;
  name: string;
  dir: string;
  role: string;
  model: string | null;
  parent: string | null;
  status: "running" | "completed" | "failed" | null;
  tokensSent: number;
  tokensReceived: number;
  recentActions: Array<{ tool: string; summary: string; inFlight: boolean; ts?: string }>;
  spawnOrder: number;
  completionOrder?: number;
  pollingTimer?: ReturnType<typeof setInterval>;
  // Internal derived fields
  subPhase: string | null;
  eventCount: number;
  completionSummary: string | null;
  // Cached most-recent projection from pollAgent(), used by the polling timer
  // to read confidence/iteration without issuing a second readProjection call.
  lastProjection?: import("../lib/audit.js").Projection;
}

// ---------------------------------------------------------------------------
// startWebServer
// ---------------------------------------------------------------------------

export async function startWebServer(epicDir: string): Promise<WebServerHandle> {
  await ensureBundle();

  // Discover available models from pi's registry
  const authStorage = new AuthStorage();
  const modelRegistry = new ModelRegistry(authStorage);
  const availableModels = modelRegistry.getAll().map((m) => ({
    id: `${m.provider}/${m.id}`,
    name: m.name,
    provider: m.provider,
  }));

  const STATIC_ASSETS: Map<string, StaticAsset> = new Map([
    ["/static/css/variables.css",  { content: loadAsset("css/variables.css"),  mimeType: "text/css; charset=utf-8" }],
    ["/static/css/layout.css",     { content: loadAsset("css/layout.css"),     mimeType: "text/css; charset=utf-8" }],
    ["/static/css/components.css", { content: loadAsset("css/components.css"), mimeType: "text/css; charset=utf-8" }],
    ["/static/css/animations.css", { content: loadAsset("css/animations.css"), mimeType: "text/css; charset=utf-8" }],
    ["/static/js/app.js",          { content: loadAsset("dist/app.js"),        mimeType: "application/javascript; charset=utf-8" }],
  ]);

  const sessionToken = randomUUID();

  // Buffered state for SSE replay on reconnect
  let currentPhase: EpicPhase | null = null;
  let currentStories: Array<{ storyId: string; status: StoryStatus }> = [];
  let currentSubagent: unknown | null = null;
  let lastLogs: LogLine[] = [];
  let pipelineEnd: { success: boolean; summary: string } | null = null;
  let lastArtifacts: ArtifactEntry[] = [];

  // Server-side accumulator for token streaming. Holds the full text produced
  // by the current subagent so reconnecting clients can catch up. Cleared on
  // subagent transitions (trackSubagent / clearSubagent).
  let streamingText = "";

  // Denormalized intake progress buffer. Includes confidence and iteration from
  // the intake agent's projection so the UI can visualize loop progress.
  // Typed as IntakeProgressEvent so the SSE payload is compile-time verified.
  let currentIntakeProgress: IntakeProgressEvent = {
    subPhase: null,
    intakeDone: false,
    confidence: null,
    iteration: 0,
  };

  // SSE clients
  const sseClients = new Set<http.ServerResponse>();

  // Pending inputs (requestReview / requestAnswer / requestModelConfig / requestArtifactReview)
  interface PendingEntry {
    type: "review" | "ask" | "model-config" | "artifact-review";
    resolve: (result: unknown) => void;
    reject: (err: Error) => void;
    payload: unknown;
  }
  const pendingInputs = new Map<string, PendingEntry>();

  // Agent registry
  const agents = new Map<string, AgentInfoInternal>();
  let spawnCounter = 0;
  let completionCounter = 0;

  // Subagent observation polling
  let trackingTimer: ReturnType<typeof setInterval> | null = null;

  // ---------------------------------------------------------------------------
  // SSE helpers
  // ---------------------------------------------------------------------------

  function pushEvent(name: string, payload: unknown): void {
    const chunk = `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
    for (const client of sseClients) {
      try {
        client.write(chunk);
      } catch {
        sseClients.delete(client);
      }
    }
  }

  function replayState(res: http.ServerResponse): void {
    const write = (name: string, payload: unknown) => {
      try {
        res.write(`event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`);
      } catch {
        // Ignore broken connection
      }
    };

    write("init", { availableModels });

    if (currentPhase) write("phase", { phase: currentPhase });
    if (currentStories.length > 0) write("stories", { stories: currentStories });

    const agentArray = buildAgentsArray();
    if (agentArray.length > 0) write("agents", { agents: agentArray });

    const scoutArray = buildScoutsArray();
    if (scoutArray.length > 0) write("scouts", { scouts: scoutArray });

    if (currentIntakeProgress.subPhase !== null || currentIntakeProgress.intakeDone || currentIntakeProgress.confidence !== null) {
      write("intake-progress", currentIntakeProgress);
    }

    if (currentSubagent) write("subagent", currentSubagent);
    // Replay accumulated streaming text as a single delta event. The frontend's
    // appendTokenDelta handles this transparently — it accumulates from zero
    // after each clear, so receiving the full text as one "delta" produces the
    // correct state.
    if (streamingText) {
      write("token-delta", { delta: streamingText } satisfies TokenDeltaEvent);
    }
    if (lastLogs.length > 0) write("logs", { lines: lastLogs });
    if (lastArtifacts.length > 0) write("artifacts", { files: withFormattedSize(lastArtifacts) });

    for (const [requestId, entry] of pendingInputs) {
      if (entry.type === "ask") {
        write("ask", { requestId, question: entry.payload });
      } else if (entry.type === "review") {
        write("review", { requestId, stories: entry.payload });
      } else if (entry.type === "model-config") {
        write("model-config", entry.payload);
      } else if (entry.type === "artifact-review") {
        const p = entry.payload as ArtifactReviewPayload;
        write("artifact-review", {
          requestId,
          artifactPath: p.artifactPath,
          content: p.content,
          description: p.description,
        });
      }
    }

    if (pipelineEnd !== null) write("pipeline-end", pipelineEnd);
  }

  // ---------------------------------------------------------------------------
  // Agent array builders
  // ---------------------------------------------------------------------------

  function buildAgentsArray(): Array<{
    id: string; name: string; role: string; model: string | null;
    parent: string | null; status: string | null; tokensSent: number;
    tokensReceived: number; recentActions: Array<{ tool: string; summary: string; inFlight: boolean; ts?: string }>; subPhase: string | null;
  }> {
    const sorted = Array.from(agents.values()).sort((a, b) => a.spawnOrder - b.spawnOrder);
    return sorted.map((a) => ({
      id: a.id,
      name: a.name,
      role: a.role,
      model: a.model,
      parent: a.parent,
      status: a.status,
      tokensSent: a.tokensSent,
      tokensReceived: a.tokensReceived,
      recentActions: a.recentActions,
      subPhase: a.subPhase,
    }));
  }

  function buildScoutsArray(): Array<{
    id: string; role: string; status: string | null; lastAction: string | null;
    eventCount: number; model: string | null; completionSummary: string | null;
    tokensSent: number; tokensReceived: number;
  }> {
    return Array.from(agents.values())
      .filter((a) => a.role === "scout")
      .map((a) => ({
        id: a.id,
        role: a.name,
        status: a.status,
        lastAction: a.recentActions.length > 0 ? (() => { const l = a.recentActions[a.recentActions.length - 1]; return l ? (l.summary ? `${l.tool}: ${l.summary}` : l.tool) : null; })() : null,
        eventCount: a.eventCount,
        model: a.model,
        completionSummary: a.completionSummary,
        tokensSent: a.tokensSent,
        tokensReceived: a.tokensReceived,
      }));
  }

  // ---------------------------------------------------------------------------
  // Agent polling
  // ---------------------------------------------------------------------------

  async function pollAgent(agent: AgentInfoInternal): Promise<void> {
    try {
      const [projection, logs] = await Promise.all([
        readProjection(agent.dir),
        readRecentLogs(agent.dir, 5),
      ]);
      if (projection) {
        agent.model = projection.model ?? agent.model;
        agent.tokensSent = projection.tokensSent;
        agent.tokensReceived = projection.tokensReceived;
        agent.eventCount = projection.eventCount;
        // Cache the latest projection so polling timers can read confidence/iteration
        // without issuing a second readProjection call for the same file in the same tick.
        agent.lastProjection = projection;
        if (projection.status !== "running") {
          agent.status = projection.status;
        }
        if (agent.role === "intake") {
          const hasPendingAsk = Array.from(pendingInputs.values()).some((p) => p.type === "ask");
          // Map intake step numbers to display sub-phase names.
          // Steps 2-4 repeat across iterations; show "questions" when user input is pending.
          const STEP_PHASE: Record<number, string> = {
            0: "extract", 1: "extract",
            2: "scout", 3: "deliberate", 4: "reflect",
            5: "synthesize",
          };
          agent.subPhase = hasPendingAsk ? "questions" : (STEP_PHASE[projection.step] ?? "reflect");
        }
      }
      if (logs.length > 0) {
        agent.recentActions = logs.slice(-5).map((l) => ({
          tool: l.tool,
          summary: l.summary || '',
          inFlight: l.inFlight,
          ...(l.ts ? { ts: l.ts } : {}),
        }));
      }
      if (agent.role === "scout" && projection?.completionSummary && !agent.completionSummary) {
        agent.completionSummary = projection.completionSummary;
      }
    } catch {
      // Non-fatal
    }
  }

  function startAgentPolling(agent: AgentInfoInternal): void {
    if (agent.pollingTimer) return;
    const timer = setInterval(async () => {
      await pollAgent(agent);
      pushEvent("agents", { agents: buildAgentsArray() });
      if (agent.role === "scout") {
        const scouts = buildScoutsArray();
        if (scouts.length > 0) pushEvent("scouts", { scouts });
      }
      // Push intake-progress event if the intake agent's sub-phase changed
      const intake = Array.from(agents.values()).find(a => a.role === "intake");
      if (intake) {
        // Use the projection already read by pollAgent (cached on agent.lastProjection)
        // to avoid a redundant readProjection call for the same file in the same tick.
        const intakeProjection = intake.lastProjection ?? null;
        const next: IntakeProgressEvent = {
          subPhase: intake.subPhase,
          intakeDone: currentPhase !== "intake" && currentPhase !== null,
          confidence: intakeProjection?.intakeConfidence ?? null,
          iteration: intakeProjection?.intakeIteration ?? 0,
        };
        const changed =
          next.subPhase !== currentIntakeProgress.subPhase ||
          next.intakeDone !== currentIntakeProgress.intakeDone ||
          next.confidence !== currentIntakeProgress.confidence ||
          next.iteration !== currentIntakeProgress.iteration;
        if (changed) {
          currentIntakeProgress = next;
          pushEvent("intake-progress", currentIntakeProgress);
        }
      }
    }, 50);
    timer.unref();
    agent.pollingTimer = timer;
  }

  function stopAgentPolling(agent: AgentInfoInternal): void {
    if (agent.pollingTimer) {
      clearInterval(agent.pollingTimer);
      agent.pollingTimer = undefined;
    }
  }

  // ---------------------------------------------------------------------------
  // HTTP server
  // ---------------------------------------------------------------------------

  const server = http.createServer(async (req, res) => {
    try {
      const method = req.method ?? "GET";
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      const { pathname } = url;

      if (method === "GET" && pathname === "/") {
        const token = url.searchParams.get("session");
        if (token !== sessionToken) { sendText(res, 403, "Invalid session token"); return; }
        const topic = await extractTopic(epicDir);
        const initialData = safeInlineJSON({ token: sessionToken, topic });
        const html = HTML_TEMPLATE.replace("/* __DATA__ */", initialData);
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
        res.end(html);
        return;
      }

      if (method === "GET" && pathname.startsWith("/static/")) {
        const asset = STATIC_ASSETS.get(pathname);
        if (!asset) { sendText(res, 404, "Not found"); return; }
        res.writeHead(200, { "Content-Type": asset.mimeType, "Cache-Control": "no-store" });
        res.end(asset.content);
        return;
      }

      if (method === "GET" && pathname === "/events") {
        const token = url.searchParams.get("session");
        if (token !== sessionToken) { sendText(res, 403, "Invalid session token"); return; }
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
        });
        res.write(": connected\n\n");
        sseClients.add(res);
        replayState(res);
        req.on("close", () => { sseClients.delete(res); });
        return;
      }

      if (method === "GET" && pathname === "/health") {
        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "GET" && pathname === "/api/model-config") {
        const config = await loadModelTierConfig();
        sendJson(res, 200, { tiers: config });
        return;
      }

      if (method === "PUT" && pathname === "/api/model-config") {
        const body = await readBody(req).catch(() => null);
        const b = body as { requestId?: string; tiers: Record<string, string | null>; scoutConcurrency?: number } | null;
        if (!b) { sendJson(res, 400, { ok: false, error: "Invalid body" }); return; }
        const { requestId, tiers } = b;

        // Save config if all 3 tiers are non-null non-empty strings
        const strong = tiers?.strong;
        const standard = tiers?.standard;
        const cheap = tiers?.cheap;
        if (strong && standard && cheap) {
          await saveModelTierConfig({ strong, standard, cheap } as ModelTierConfig);
        }

        // Save scout concurrency
        if (typeof b.scoutConcurrency === "number" && b.scoutConcurrency > 0) {
          await saveScoutConcurrency(b.scoutConcurrency);
        }

        // Resolve the blocking gate if requestId matches
        if (requestId) {
          const entry = pendingInputs.get(requestId);
          if (entry && entry.type === "model-config") {
            pendingInputs.delete(requestId);
            entry.resolve(undefined);
          }
        }

        // Push confirmation so client clears pendingInput
        pushEvent("model-config-confirmed", {});

        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "POST" && pathname === "/api/heartbeat") {
        const body = await readBody(req).catch(() => null);
        const b = body as { token?: string } | null;
        if (!b || b.token !== sessionToken) { sendJson(res, 403, { ok: false, error: "Invalid token" }); return; }
        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "POST" && pathname === "/api/answer") {
        const body = await readBody(req).catch(() => null);
        const b = body as { token?: string; requestId?: string; answer?: unknown } | null;
        if (!b) { sendJson(res, 400, { ok: false, error: "Invalid body" }); return; }
        if (b.token !== sessionToken) { sendJson(res, 403, { ok: false, error: "Invalid token" }); return; }
        const { requestId, answer } = b;
        if (!requestId || !answer || typeof answer !== "object") {
          sendJson(res, 400, { ok: false, error: "Missing requestId or answer" }); return;
        }
        const parsed = answer as {
          questionId?: unknown;
          selectedOptions?: unknown;
          customInput?: unknown;
        };
        if (
          typeof parsed.questionId !== "string" ||
          !Array.isArray(parsed.selectedOptions) ||
          parsed.selectedOptions.some((s) => typeof s !== "string") ||
          (parsed.customInput !== undefined && typeof parsed.customInput !== "string")
        ) {
          sendJson(res, 400, { ok: false, error: "Invalid answer payload" }); return;
        }

        const pending = pendingInputs.get(requestId);
        if (!pending || pending.type !== "ask") {
          sendJson(res, 409, { ok: false, error: "No pending ask with this requestId" }); return;
        }
        const normalizedAnswer: AnswerElement = {
          questionId: parsed.questionId,
          selectedOptions: parsed.selectedOptions,
          ...(parsed.customInput !== undefined ? { customInput: parsed.customInput } : {}),
        };
        const result: AnswerResult = { cancelled: false, answer: normalizedAnswer };
        pending.resolve(result);
        pendingInputs.delete(requestId);
        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "POST" && pathname === "/api/review") {
        const body = await readBody(req).catch(() => null);
        const b = body as { token?: string; requestId?: string; approved?: string[]; skipped?: string[] } | null;
        if (!b) { sendJson(res, 400, { ok: false, error: "Invalid body" }); return; }
        if (b.token !== sessionToken) { sendJson(res, 403, { ok: false, error: "Invalid token" }); return; }
        const { requestId, approved, skipped } = b;
        if (!requestId || !Array.isArray(approved) || !Array.isArray(skipped)) {
          sendJson(res, 400, { ok: false, error: "Missing fields" }); return;
        }
        const pending = pendingInputs.get(requestId);
        if (!pending || pending.type !== "review") {
          sendJson(res, 409, { ok: false, error: "No pending review with this requestId" }); return;
        }
        const result: ReviewResult = { approved, skipped };
        pending.resolve(result);
        pendingInputs.delete(requestId);
        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "POST" && pathname === "/api/artifact-review") {
        const body = await readBody(req).catch(() => null);
        const b = body as { token?: string; requestId?: string; feedback?: string } | null;
        if (!b) { sendJson(res, 400, { ok: false, error: "Invalid body" }); return; }
        if (b.token !== sessionToken) { sendJson(res, 403, { ok: false, error: "Invalid token" }); return; }
        const { requestId, feedback } = b;
        if (!requestId || typeof feedback !== "string" || feedback.trim() === "") {
          sendJson(res, 400, { ok: false, error: "Missing requestId or feedback" }); return;
        }
        const pending = pendingInputs.get(requestId);
        if (!pending || pending.type !== "artifact-review") {
          sendJson(res, 409, { ok: false, error: "No pending artifact review with this requestId" }); return;
        }
        const artifactResult: ArtifactReviewFeedback = { feedback };
        pending.resolve(artifactResult);
        pendingInputs.delete(requestId);
        sendJson(res, 200, { ok: true });
        return;
      }

      if (method === "POST" && pathname === "/api/cancel") {
        const body = await readBody(req).catch(() => null);
        const b = body as { token?: string } | null;
        if (!b || b.token !== sessionToken) { sendJson(res, 403, { ok: false, error: "Invalid token" }); return; }
        pipelineEnd = { success: false, summary: "Cancelled by user" };
        pushEvent("pipeline-end", pipelineEnd);
        const err = new Error("Pipeline cancelled by user");
        err.name = "AbortError";
        for (const [, entry] of pendingInputs) entry.reject(err);
        pendingInputs.clear();
        sendJson(res, 200, { ok: true });
        return;
      }

      sendText(res, 404, "Not found");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Server error";
      sendJson(res, 500, { ok: false, error: msg });
    }
  });

  return new Promise((resolve, reject) => {
    server.once("error", (err: Error) => {
      reject(new Error(`Failed to start koan web server: ${err.message}`));
    });

    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") {
        reject(new Error("Failed to start koan web server: invalid address"));
        return;
      }
      const { port } = addr;
      const url = `http://127.0.0.1:${port}/?session=${sessionToken}`;

      const handle: WebServerHandle = {
        url,
        port,

        pushPhase(phase: EpicPhase): void {
          currentPhase = phase;
          // Evict finished agents from the previous phase so the UI starts clean.
          for (const [id, agent] of agents) {
            if (agent.status && agent.status !== "running") {
              stopAgentPolling(agent);
              agents.delete(id);
            }
          }
          pushEvent("agents", { agents: buildAgentsArray() });
          pushEvent("scouts", { scouts: buildScoutsArray() });
          pushEvent("phase", { phase });
          currentIntakeProgress = { ...currentIntakeProgress, intakeDone: phase !== "intake" };
          pushEvent("intake-progress", currentIntakeProgress);
        },

        pushStories(stories: Array<{ storyId: string; status: StoryStatus }>): void {
          currentStories = stories;
          pushEvent("stories", { stories });
        },

        pushLogs(lines: LogLine[], currentToolCallId?: string | null): void {
          lastLogs = lines;
          pushEvent("logs", { lines, currentToolCallId: currentToolCallId ?? null });
        },

        pushNotification(message: string, level: "info" | "warning" | "error"): void {
          pushEvent("notification", { message, level });
        },

        pushTokenDelta(delta: string): void {
          // Accumulate server-side for replay on client reconnect. Without this,
          // a client that reconnects mid-stream would see an empty streaming area
          // with no error signal — a silent failure.
          streamingText += delta;
          // Push only the delta (not accumulated text) to already-connected clients.
          // This matches the provider stream's own framing and minimizes SSE payload.
          pushEvent("token-delta", { delta } satisfies TokenDeltaEvent);
        },

        clearTokenStream(): void {
          // Called on message_end boundaries. Clears stale text so it doesn't
          // persist while the LLM is executing tools or waiting on IPC.
          if (streamingText) {
            streamingText = "";
            pushEvent("token-clear", {});
          }
        },

        trackSubagent(dir: string, role: string, storyId?: string): void {
          if (trackingTimer) { clearInterval(trackingTimer); trackingTimer = null; }
          // New subagent starts — discard previous text.
          streamingText = "";
          const startedAt = Date.now();
          const timer = setInterval(async () => {
            try {
              const [projection, logs] = await Promise.all([readProjection(dir), readRecentLogs(dir, 50)]);
              if (logs.length > 0) {
                lastLogs = logs;
                pushEvent("logs", { lines: logs, currentToolCallId: projection?.currentToolCallId ?? null });
              }
              if (projection) {
                const event = {
                  role, storyId,
                  model: projection.model,
                  step: projection.step,
                  totalSteps: projection.totalSteps,
                  stepName: projection.stepName,
                  tokensSent: projection.tokensSent,
                  tokensReceived: projection.tokensReceived,
                  startedAt,
                };
                currentSubagent = event;
                pushEvent("subagent", event);
              }
            } catch { /* Non-fatal */ }
          }, 50);
          timer.unref();
          trackingTimer = timer;
        },

        clearSubagent(): void {
          if (trackingTimer) { clearInterval(trackingTimer); trackingTimer = null; }
          currentSubagent = null;
          // Subagent finished — discard text.
          streamingText = "";
          pushEvent("subagent-idle", {});
        },

        registerAgent(info: {
          id: string; name: string; dir: string; role: string;
          model: string | null; parent: string | null;
          status?: "running" | null;
        }): void {
          const agent: AgentInfoInternal = {
            ...info,
            status: info.status ?? "running",
            tokensSent: 0,
            tokensReceived: 0,
            recentActions: [],
            spawnOrder: spawnCounter++,
            subPhase: null,
            eventCount: 0,
            completionSummary: null,
          };
          agents.set(info.id, agent);
          if (agent.status === "running") startAgentPolling(agent);
          pushEvent("agents", { agents: buildAgentsArray() });
          if (info.role === "scout") pushEvent("scouts", { scouts: buildScoutsArray() });
        },

        startAgent(id: string): void {
          const agent = agents.get(id);
          if (!agent || agent.status !== null) return;
          agent.status = "running";
          startAgentPolling(agent);
          pushEvent("agents", { agents: buildAgentsArray() });
          if (agent.role === "scout") pushEvent("scouts", { scouts: buildScoutsArray() });
        },

        completeAgent(id: string): void {
          const agent = agents.get(id);
          if (!agent) return;
          stopAgentPolling(agent);
          void readProjection(agent.dir).then((projection) => {
            if (projection) {
              agent.tokensSent = projection.tokensSent;
              agent.tokensReceived = projection.tokensReceived;
              agent.status = projection.status !== "running" ? projection.status : "failed";
            } else {
              agent.status = "failed";
            }
            agent.completionOrder = completionCounter++;
            pushEvent("agents", { agents: buildAgentsArray() });
            if (agent.role === "scout") {
              agent.completionSummary = projection?.completionSummary ?? null;
              pushEvent("scouts", { scouts: buildScoutsArray() });
            }
          });
        },

        requestReview(stories: ReviewStory[], signal?: AbortSignal): Promise<ReviewResult> {
          return new Promise<ReviewResult>((res, rej) => {
            const requestId = randomUUID();
            const abortHandler = () => {
              pendingInputs.delete(requestId);
              pushEvent("review-cancelled", { requestId });
              const err = new Error(`Review cancelled: signal aborted`);
              (err as NodeJS.ErrnoException).name = "AbortError";
              rej(err);
            };
            pendingInputs.set(requestId, {
              type: "review",
              resolve: (result: unknown) => {
                signal?.removeEventListener("abort", abortHandler);
                res(result as ReviewResult);
              },
              reject: (err: Error) => {
                signal?.removeEventListener("abort", abortHandler);
                rej(err);
              },
              payload: stories,
            });
            pushEvent("review", { requestId, stories });
            if (signal?.aborted) {
              abortHandler();
            } else {
              signal?.addEventListener("abort", abortHandler, { once: true });
            }
          });
        },

        requestAnswer(question: AskQuestion, signal: AbortSignal): Promise<AnswerResult> {
          return new Promise<AnswerResult>((res, rej) => {
            const requestId = randomUUID();
            const abortHandler = () => {
              pendingInputs.delete(requestId);
              pushEvent("ask-cancelled", { requestId });
              const err = new Error(`Ask cancelled: signal aborted`);
              (err as NodeJS.ErrnoException).name = "AbortError";
              rej(err);
            };
            pendingInputs.set(requestId, {
              type: "ask",
              resolve: (result: unknown) => {
                signal.removeEventListener("abort", abortHandler);
                res(result as AnswerResult);
              },
              reject: (err: Error) => {
                signal.removeEventListener("abort", abortHandler);
                rej(err);
              },
              payload: question,
            });
            pushEvent("ask", { requestId, question });
            if (signal.aborted) {
              abortHandler();
            } else {
              signal.addEventListener("abort", abortHandler, { once: true });
            }
          });
        },

        async requestModelConfig(): Promise<void> {
          const requestId = randomUUID();
          const { modelTiers, scoutConcurrency } = await loadKoanConfig();
          const payload = { requestId, tiers: modelTiers, scoutConcurrency, availableModels };
          return new Promise<void>((resolve, reject) => {
            pendingInputs.set(requestId, {
              type: "model-config" as const,
              resolve: resolve as (v: unknown) => void,
              reject,
              payload,
            });
            pushEvent("model-config", payload);
          });
        },

        requestArtifactReview(payload: ArtifactReviewPayload, signal: AbortSignal): Promise<ArtifactReviewFeedback> {
          return new Promise<ArtifactReviewFeedback>((res, rej) => {
            const requestId = randomUUID();
            const abortHandler = () => {
              pendingInputs.delete(requestId);
              pushEvent("artifact-review-cancelled", { requestId });
              const err = new Error(`Artifact review cancelled: signal aborted`);
              (err as NodeJS.ErrnoException).name = "AbortError";
              rej(err);
            };
            pendingInputs.set(requestId, {
              type: "artifact-review",
              resolve: (result: unknown) => {
                signal.removeEventListener("abort", abortHandler);
                res(result as ArtifactReviewFeedback);
              },
              reject: (err: Error) => {
                signal.removeEventListener("abort", abortHandler);
                rej(err);
              },
              payload,
            });
            pushEvent("artifact-review", {
              requestId,
              artifactPath: payload.artifactPath,
              content: payload.content,
              description: payload.description,
            });
            if (signal.aborted) {
              abortHandler();
            } else {
              signal.addEventListener("abort", abortHandler, { once: true });
            }
          });
        },

        close(): void {
          for (const [, entry] of pendingInputs) entry.reject(new Error("Server closed"));
          pendingInputs.clear();
          if (trackingTimer) { clearInterval(trackingTimer); trackingTimer = null; }
          for (const agent of agents.values()) stopAgentPolling(agent);
          for (const client of sseClients) { try { client.end(); } catch { /* Ignore */ } }
          sseClients.clear();
          try { server.close(); } catch { /* Ignore */ }
        },
      };

      resolve(handle);
    });
  });
}

// ---------------------------------------------------------------------------
// Open browser helper (§12.2)
// ---------------------------------------------------------------------------

export async function openBrowser(pi: ExtensionAPI, url: string): Promise<void> {
  try {
    if (process.platform === "darwin") {
      await pi.exec("open", [url]);
    } else if (process.platform === "win32") {
      await pi.exec("cmd", ["/c", "start", "", url]);
    } else {
      await pi.exec("xdg-open", [url]);
    }
  } catch {
    // Non-fatal — URL is always in the tool result
  }
}
