# AppState and AgentState -- in-process mutable state for the koan server.
# These are plain dataclasses mutated in place; no persistence layer here.

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .credentials import CredentialStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from .config import KoanConfig
from .projections import ProjectionStore
from .types import WorkflowPhase, ConnectionStatus, ProviderModel, ModelRegistryEntry, SubagentRole


@dataclass
class ChatMessage:
    content: str
    timestamp_ms: int
    # Upload IDs that were attached to this message at submission time.
    # IDs are resolved to paths via UploadState; files are committed to run_dir
    # before the message is buffered so handlers can always find them.
    attachments: list[str] = field(default_factory=list)
    # When set, the message is anchored to a specific run-dir artifact. Rendered
    # as an [artifact: {path}] prefix in the steering envelope so the
    # orchestrator knows which artifact the comment refers to.
    artifact_path: str | None = None


@dataclass
class PendingInteraction:
    type: Literal["ask"]
    agent_id: str
    future: asyncio.Future
    payload: dict
    token: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class AgentState:
    agent_id: str
    role: SubagentRole
    subagent_dir: str
    run_dir: str = ""
    label: str = ""
    step: int = 0
    phase_module: Any = None
    phase_ctx: Any = None
    event_log: Any = None
    # Set by run_agent_loop once the first turn reaches the End node -- the
    # bootstrap signal that replaces the removed first-tool-call handshake.
    first_turn_completed: bool = False
    pending_tool: asyncio.Future | None = None
    model: str | None = None
    # provider and context_window feed the fold's cost + context-window derivation.
    # Set from model_spec at spawn time; None/0 when agent_impl is injected in tests.
    provider: str | None = None
    context_window: int = 0
    token_count: dict = field(default_factory=lambda: {"sent": 0, "received": 0})
    final_response: str = ""
    is_primary: bool = True
    # "claude", "codex", "gemini", or "" (default -- treated as non-Claude).
    # Populated by spawn_subagent from agent_impl.name (the Agent Protocol's
    # name attribute). Used by upload_ids_to_blocks to decide whether to emit
    # File/Image blocks or a text-notice fallback, and (in M2) by
    # steering-drain routing to distinguish Claude from command-line agents.
    runner_type: str = ""
    started_at: datetime = field(default_factory=_utcnow)
    # Driver-owned conversation history (M5).
    # The multi-turn loop accumulates ModelMessage objects here across hand-backs
    # and passes them as message_history to each subsequent agent.iter() call.
    # Owning this list in the driver (not inside pydantic-ai) is what enables
    # future advanced-control features: interrupts, compaction, context surgery.
    message_history: list = field(default_factory=list)
    # Context-file injection tracking (M4).
    # injected_context_files: absolute paths already injected as
    # <project_instructions> user messages; prevents duplicate injection
    # across multiple model requests within the same agent lifetime.
    # pending_context_files: discovered-but-not-yet-injected paths; drained
    # by the history processor before each model request.
    injected_context_files: set = field(default_factory=set)
    pending_context_files: list = field(default_factory=list)


# -- Sub-state dataclasses (grouped by access pattern) ------------------------

@dataclass
class RunState:
    phase: WorkflowPhase = "intake"
    workflow: Any = None  # Workflow | None -- imported lazily to avoid circular deps
    workflow_done: bool = False
    run_dir: str | None = None
    task_description: str = ""
    project_dir: str = ""
    # Additional working directories beyond project_dir, populated from --add-dir flags.
    additional_dirs: list[str] = field(default_factory=list)
    run_installations: dict[str, str] = field(default_factory=dict)
    # Upload IDs attached at start-run time. The in-process path no longer
    # consumes start_attachments (the consuming MCP handler was removed in M1);
    # the field is retained but unused. task.json carries the IDs as a debug
    # breadcrumb only.
    start_attachments: list[str] = field(default_factory=list)
    # Handle for the per-run driver coroutine task. Authoritative source of
    # truth for the "is a run active?" guard in api_start_run; done() means
    # the previous run has finished and a new start is permitted.
    driver_task: asyncio.Task | None = None


@dataclass
class InteractionState:
    active_interaction: PendingInteraction | None = None
    interaction_queue: deque[PendingInteraction] = field(default_factory=deque)
    interaction_queue_max: int = 8
    user_message_buffer: list[ChatMessage] = field(default_factory=list)
    yield_future: asyncio.Future | None = None
    # Orchestrator-authored hand-back suggestions recorded by koan_suggest_next.
    # Consumed and cleared by the loop at the phase-boundary hand-back.
    # build_phase_suggestions is the fallback when None (koan_suggest_next never
    # called for this hand-back).
    next_suggestions: list[dict] | None = None
    # Separate future for koan_memory_propose -- same isolation rationale as
    # the removed artifact_review_future (koan_artifact_propose is gone in M5).
    memory_propose_future: asyncio.Future | None = None
    # Background reflect task and its session id for the cancel path.
    reflect_task: asyncio.Task | None = None
    reflect_session_id: str | None = None
    steering_queue: list[ChatMessage] = field(default_factory=list)


@dataclass
class UploadRecord:
    id: str
    filename: str
    size: int
    content_type: str
    path: Path          # absolute path to file on disk
    committed: bool     # False while in tempdir, True after commit_to_run


@dataclass
class UploadState:
    # tempdir is typed Any to avoid importing tempfile at module load --
    # state.py is import-sensitive and tempfile is only needed in uploads.py.
    tempdir: Any = None
    entries: dict[str, UploadRecord] = field(default_factory=dict)


@dataclass
class ProviderConfigState:
    """Mutable server-side provider configuration state.

    Renamed from RunnerConfigState (post-PydanticAI: 'runner' terminology retired).
    M5: builtin_profiles removed (compute_builtin_profiles returns {}; the shim
    is deleted); provider_status changed to list[ConnectionStatus] (per-connection
    availability replaces per-type ProviderStatus, brief D3).

    model_registry is additive -- populated at startup alongside provider_status
    and surfaced to the frontend via Settings projection initial events.
    credential_store is the decrypted, in-memory credential authority for the
    web/agent path. Set at startup (cli/run.py) before any availability check.
    provider_models is the per-provider dynamic model overlay (LM Studio + cloud),
    keyed by provider name and populated by the eager startup task.
    """

    config: KoanConfig = field(default_factory=KoanConfig)
    # M5: per-connection availability (replaces per-type ProviderStatus from M2).
    provider_status: list[ConnectionStatus] = field(default_factory=list)
    # M2: all-providers model registry sourced from MODEL_CAPABILITIES + genai-prices.
    model_registry: list[ModelRegistryEntry] = field(default_factory=list)
    config_write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Decrypted credential store; None only during test setups that do not
    # exercise the credential path (provider_available returns False when None).
    credential_store: "CredentialStore | None" = None
    # Dynamic model overlay: provider -> list of live-retrieved ProviderModel.
    # Populated by the eager startup background task; refreshed on model-test.
    provider_models: dict[str, list[ProviderModel]] = field(default_factory=dict)


@dataclass
class MemoryServices:
    # Eagerly constructed once project_dir is known, via init_memory_services().
    # Using string forward references to avoid import-time cost of loading ML models.
    memory_store: "MemoryStore | None" = None
    retrieval_index: "RetrievalIndex | None" = None


@dataclass
class ServerConfig:
    port: int = 8000
    # Default to loopback so programmatic constructors (e.g. eval harness)
    # that bypass argparse still produce safe, working connect-back URLs.
    address: str = "127.0.0.1"
    open_browser: bool = True
    yolo: bool = False
    debug: bool = False
    initial_prompt: str = ""
    # Non-None when running in directed mode (e.g. from eval harness).
    # Stores the ordered phase sequence; koan_yield steers toward the next entry.
    directed_phases: list[str] | None = None

    def connect_back_url(self, path: str = "") -> str:
        """URL a local client (browser, subagent) uses to reach this server.

        Substitutes loopback for wildcard binds (0.0.0.0 -> 127.0.0.1,
        :: -> ::1) and brackets IPv6 literals so the URL is well-formed.
        Callers never need to branch on address shape themselves.
        """
        addr = self.address
        if addr == "0.0.0.0":
            host = "127.0.0.1"
        elif addr == "::":
            host = "[::1]"
        elif ":" in addr:
            # Specific IPv6 literal -- bracket it for URL use.
            host = f"[{addr}]"
        else:
            host = addr
        return f"http://{host}:{self.port}{path}"


# -- AppState: composition root -----------------------------------------------

@dataclass
class AppState:
    run: RunState = field(default_factory=RunState)
    interactions: InteractionState = field(default_factory=InteractionState)
    provider_config: ProviderConfigState = field(default_factory=ProviderConfigState)
    memory: MemoryServices = field(default_factory=MemoryServices)
    uploads: UploadState = field(default_factory=UploadState)
    server: ServerConfig = field(default_factory=ServerConfig)
    projection_store: ProjectionStore = field(default_factory=ProjectionStore)
    agents: dict[str, AgentState] = field(default_factory=dict)
    # _active_processes removed in M4: the legacy CLI subprocess registration
    # path is deleted; in-process PydanticAI agents have no subprocess to track.
    # Track in-flight in-process subagent asyncio tasks (executor/scouts spawned
    # via the in-process koan_request_* tools, M6) so shutdown can cancel them.
    _active_tasks: dict[str, "asyncio.Task"] = field(
        default_factory=dict, repr=False,
    )

    def init_memory_services(self) -> None:
        """Eagerly construct memory services once project_dir is set.

        Called after app_state.run.project_dir is populated. RetrievalIndex.__init__
        is cheap (no model load); the store.init() call does mkdir(.koan/memory).
        """
        from pathlib import Path
        from .memory.store import MemoryStore
        from .memory.retrieval.index import RetrievalIndex
        project_dir = self.run.project_dir or "."
        store = MemoryStore(project_dir)
        store.init()
        self.memory.memory_store = store
        self.memory.retrieval_index = RetrievalIndex(
            Path(project_dir) / ".koan" / "memory"
        )


def hydrate_memory_projection(app_state: AppState) -> None:
    """Push all on-disk memory entries into the projection store at server boot.

    Called before any SSE subscribers exist, so ProjectionStore.push_event folds
    + updates prev_state without broadcasting.  The first SSE connect snapshot
    therefore includes all entries without a separate fetch.
    """
    # Local imports keep state.py free of ML-model / web-layer import costs.
    from .projections import MemoryEntrySummary
    from .events import build_memory_entry_created, build_memory_summary_updated
    from .memory.timestamps import iso_to_ms

    store = app_state.memory.memory_store
    if store is None:
        return

    entries = store.list_entries()
    for entry in entries:
        if entry.file_path is None:
            continue
        # Derive NNNN seq from filename like "0042-some-title.md".
        seq = entry.file_path.name[:4]
        eid = int(seq)
        summary = MemoryEntrySummary(
            seq=seq,
            type=entry.type,
            title=entry.title,
            created_ms=iso_to_ms(entry.created),
            modified_ms=iso_to_ms(entry.modified),
        )
        app_state.projection_store.push_event(
            "memory_entry_created",
            build_memory_entry_created(summary.to_wire()),
        )

    current_summary = store.get_summary() or ""
    app_state.projection_store.push_event(
        "memory_summary_updated",
        build_memory_summary_updated(current_summary),
    )


def drain_user_messages(app_state: AppState) -> list[ChatMessage]:
    """Atomically drain the user message buffer. Returns all buffered messages."""
    messages = list(app_state.interactions.user_message_buffer)
    app_state.interactions.user_message_buffer.clear()
    return messages


def drain_steering_messages(app_state: AppState) -> list[ChatMessage]:
    """Atomically drain the steering queue. Returns all buffered messages."""
    messages = list(app_state.interactions.steering_queue)
    app_state.interactions.steering_queue.clear()
    return messages
