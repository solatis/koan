// koan.js -- vanilla JS client for the HTMX+SSE dashboard.
// No build step, no JSX, no modules. Single file handles SSE dispatch,
// DOM patching for high-frequency events, and reconnect logic.

(function () {
  "use strict";

  // -- State ------------------------------------------------------------------

  var es = null;
  var retryDelay = 500;
  var maxRetry = 5000;
  var questionIndex = 0;
  var questionAnswers = {};
  var selectedWorkflowPhase = null;

  // -- Helpers ----------------------------------------------------------------

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function formatTokens(n) {
    if (!n) return "--";
    if (n < 1000) return String(n);
    return Math.round(n / 1000) + "k";
  }

  function formatElapsed(ms) {
    var s = Math.floor(ms / 1000);
    var m = Math.floor(s / 60);
    s = s % 60;
    return m + "m " + String(s).padStart(2, "0") + "s";
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function notify(msg, level) {
    var box = $("#notifications");
    if (!box) return;
    var el = document.createElement("div");
    el.className = "notification " + (level || "info");
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(function () {
      el.classList.add("fade-out");
      setTimeout(function () { el.remove(); }, 300);
    }, 5000);
  }

  // -- SSE connection ---------------------------------------------------------

  function connectSSE() {
    if (es) { try { es.close(); } catch (e) { /* ignore */ } }
    es = new EventSource("/events");

    es.onopen = function () {
      retryDelay = 500;
    };

    es.onerror = function () {
      es.close();
      notify("Connection lost -- reconnecting...", "warning");
      setTimeout(connectSSE, retryDelay);
      retryDelay = Math.min(retryDelay * 2, maxRetry);
    };

    // High-frequency: direct DOM manipulation
    es.addEventListener("token-delta", function (e) {
      var d = JSON.parse(e.data);
      var tgt = $("#stream-target");
      if (tgt) tgt.textContent += d.delta;
    });

    es.addEventListener("token-clear", function () {
      var tgt = $("#stream-target");
      if (tgt) tgt.textContent = "";
    });

    es.addEventListener("logs", function (e) {
      var d = JSON.parse(e.data);
      var feed = $("#activity-feed-inner");
      if (!feed) return;
      var atBottom = feed.parentElement &&
        (feed.parentElement.scrollTop + feed.parentElement.clientHeight >=
         feed.parentElement.scrollHeight - 30);
      var line = d.line;
      if (line) {
        var div = document.createElement("div");
        div.className = "activity-line" + (line.inFlight ? " activity-inflight" : "") +
          (line.highValue ? " activity-high" : "");
        div.innerHTML =
          '<span class="activity-tool">' + esc(line.tool || "") + '</span>' +
          '<span class="activity-summary">' + esc(line.summary || "") +
          (line.inFlight ? '<span class="activity-dots">...</span>' : "") +
          '</span>';
        feed.appendChild(div);
      }
      if (atBottom && feed.parentElement) {
        feed.parentElement.scrollTop = feed.parentElement.scrollHeight;
      }
    });

    es.addEventListener("notification", function (e) {
      var d = JSON.parse(e.data);
      notify(d.message || "Notification", d.level || "info");
    });

    // Low-frequency: server-rendered HTML fragment swap
    var fragmentEvents = [
      "phase", "subagent", "subagent-idle", "intake-progress",
      "stories", "scouts", "agents", "artifacts",
      "interaction", "pipeline-end", "frozen-logs",
      "workflow-decision", "workflow-decision-cancelled",
      "ask-cancelled", "artifact-review-cancelled"
    ];
    fragmentEvents.forEach(function (evt) {
      es.addEventListener(evt, function (e) {
        var d = JSON.parse(e.data);
        if (d.html && d.target) {
          var el = document.getElementById(d.target);
          if (el) {
            el.outerHTML = d.html;
            // Re-bind event listeners after swap
            bindDynamicHandlers();
          }
        }
        // Phase change: update pill strip
        if (evt === "phase" && d.phase) {
          updatePillStrip(d.phase);
        }
      });
    });
  }

  // -- Pill strip -------------------------------------------------------------

  var PHASES = [
    "intake", "brief-generation", "core-flows", "tech-plan",
    "ticket-breakdown", "cross-artifact-validation",
    "execution", "implementation-validation"
  ];

  function updatePillStrip(currentPhase) {
    var found = false;
    PHASES.forEach(function (p) {
      var pill = document.querySelector('[data-phase="' + p + '"]');
      if (!pill) return;
      pill.classList.remove("active", "done");
      if (p === currentPhase) {
        pill.classList.add("active");
        found = true;
      } else if (!found) {
        pill.classList.add("done");
      }
    });
  }

  // -- Elapsed timer ----------------------------------------------------------

  setInterval(function () {
    $$("[data-started-at]").forEach(function (el) {
      var ts = parseInt(el.getAttribute("data-started-at"), 10);
      if (!ts) return;
      var elapsed = Date.now() - ts;
      var span = el.querySelector(".elapsed-value");
      if (span) span.textContent = formatElapsed(elapsed);
    });
  }, 1000);

  // -- Dynamic event binding --------------------------------------------------

  function bindDynamicHandlers() {
    // Question form navigation
    bindQuestionNav();
    // Artifact overlay clicks
    bindArtifactClicks();
    // Workflow option clicks
    bindWorkflowOptions();
    // Activity card expand
    bindCardExpand();
    // Folder toggle
    bindFolderToggle();
  }

  // -- Question form ----------------------------------------------------------

  function bindQuestionNav() {
    var form = $("#question-form");
    if (!form) return;

    var cards = form.querySelectorAll(".question-card");
    if (!cards.length) return;

    showQuestion(questionIndex);

    form.querySelectorAll(".option").forEach(function (opt) {
      opt.onclick = function () {
        var qIdx = parseInt(opt.closest(".question-card").getAttribute("data-q-index"), 10);
        var val = opt.getAttribute("data-value");
        var multi = opt.closest(".question-card").getAttribute("data-multi") === "true";

        if (val === "__other__") {
          var inp = opt.querySelector(".other-input");
          if (inp) inp.classList.toggle("visible");
          opt.classList.toggle("selected");
        } else if (multi) {
          opt.classList.toggle("selected");
        } else {
          opt.closest(".options-list").querySelectorAll(".option").forEach(function (o) {
            if (o !== opt) o.classList.remove("selected");
          });
          opt.classList.toggle("selected");
        }
        collectAnswer(qIdx);
      };
    });
  }

  function showQuestion(idx) {
    var cards = $$("#question-form .question-card");
    cards.forEach(function (c, i) {
      c.style.display = i === idx ? "" : "none";
    });
    var prog = $("#question-progress");
    if (prog) prog.textContent = (idx + 1) + " / " + cards.length;

    var btnBack = $("#btn-back");
    var btnNext = $("#btn-next");
    var btnSubmit = $("#btn-submit-answers");
    if (btnBack) btnBack.style.display = idx > 0 ? "" : "none";
    if (btnNext) btnNext.style.display = idx < cards.length - 1 ? "" : "none";
    if (btnSubmit) btnSubmit.style.display = idx === cards.length - 1 ? "" : "none";
  }

  function collectAnswer(qIdx) {
    var card = document.querySelector('.question-card[data-q-index="' + qIdx + '"]');
    if (!card) return;
    var multi = card.getAttribute("data-multi") === "true";
    var selected = card.querySelectorAll(".option.selected");
    var vals = [];
    selected.forEach(function (opt) {
      var v = opt.getAttribute("data-value");
      if (v === "__other__") {
        var inp = opt.querySelector(".other-input");
        vals.push(inp ? inp.value : "");
      } else {
        vals.push(v);
      }
    });
    questionAnswers[qIdx] = multi ? vals : (vals[0] || null);
  }

  // Global button handlers (delegated)
  document.addEventListener("click", function (e) {
    var tgt = e.target;

    if (tgt.id === "btn-next" || tgt.closest("#btn-next")) {
      collectAnswer(questionIndex);
      var cards = $$("#question-form .question-card");
      if (questionIndex < cards.length - 1) {
        questionIndex++;
        showQuestion(questionIndex);
      }
      return;
    }

    if (tgt.id === "btn-back" || tgt.closest("#btn-back")) {
      if (questionIndex > 0) {
        questionIndex--;
        showQuestion(questionIndex);
      }
      return;
    }

    if (tgt.id === "btn-use-defaults" || tgt.closest("#btn-use-defaults")) {
      var form = $("#question-form");
      var token = form ? form.getAttribute("data-token") || "" : "";
      var cards = $$("#question-form .question-card");
      var defaults = [];
      cards.forEach(function (card) {
        var multi = card.getAttribute("data-multi") === "true";
        var recommended = card.querySelectorAll(".option.recommended");
        var vals = [];
        recommended.forEach(function (opt) {
          vals.push(opt.getAttribute("data-value"));
        });
        defaults.push(multi ? vals : (vals[0] || null));
      });
      submitAnswers(defaults, token);
      return;
    }

    if (tgt.id === "btn-submit-answers" || tgt.closest("#btn-submit-answers")) {
      collectAnswer(questionIndex);
      var answers = [];
      var cards = $$("#question-form .question-card");
      for (var i = 0; i < cards.length; i++) {
        answers.push(questionAnswers[i] !== undefined ? questionAnswers[i] : null);
      }
      var token = ($("#question-form") || {}).getAttribute("data-token") || "";
      submitAnswers(answers, token);
      return;
    }

    // Start run
    if (tgt.id === "btn-start-run" || tgt.closest("#btn-start-run")) {
      startRun();
      return;
    }

    // Settings toggle
    if (tgt.classList.contains("settings-btn") || tgt.closest(".settings-btn")) {
      var overlay = $("#model-config-overlay");
      if (overlay) overlay.hidden = !overlay.hidden;
      return;
    }

    // Save model config
    if (tgt.id === "btn-save-config" || tgt.closest("#btn-save-config")) {
      saveModelConfig();
      return;
    }

    // Artifact overlay close
    if (tgt.classList.contains("artifact-overlay") || tgt.id === "btn-close-artifact") {
      var ov = $(".artifact-overlay");
      if (ov) ov.remove();
      return;
    }

    // Artifact review accept
    if (tgt.id === "btn-accept-artifact" || tgt.closest("#btn-accept-artifact")) {
      submitArtifactReview("accept");
      return;
    }

    // Artifact review feedback
    if (tgt.id === "btn-send-feedback" || tgt.closest("#btn-send-feedback")) {
      var fb = $("#artifact-review-textarea");
      submitArtifactReview(fb ? fb.value : "");
      return;
    }

    // Workflow continue
    if (tgt.id === "btn-workflow-continue" || tgt.closest("#btn-workflow-continue")) {
      submitWorkflowDecision();
      return;
    }
  });

  // Escape key closes overlays
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var ov = $(".artifact-overlay");
      if (ov) { ov.remove(); return; }
      var cfg = $("#model-config-overlay");
      if (cfg && !cfg.hidden) { cfg.hidden = true; }
    }
  });

  // -- Artifact clicks --------------------------------------------------------

  function bindArtifactClicks() {
    $$(".tree-file").forEach(function (el) {
      el.onclick = function () {
        var path = el.getAttribute("data-path");
        if (!path) return;
        fetch("/api/artifacts/" + encodeURIComponent(path))
          .then(function (r) { return r.json(); })
          .then(function (d) { showArtifactOverlay(d.displayPath || path, d.content || ""); })
          .catch(function () { notify("Failed to load artifact", "error"); });
      };
    });
  }

  function showArtifactOverlay(path, content) {
    var existing = $(".artifact-overlay");
    if (existing) existing.remove();

    var overlay = document.createElement("div");
    overlay.className = "artifact-overlay";
    overlay.innerHTML =
      '<div class="artifact-overlay-panel">' +
        '<div class="artifact-overlay-header">' +
          '<div>' +
            '<div class="artifact-overlay-title">' + esc(path.split("/").pop()) +
              '<span class="artifact-overlay-readonly-badge">read-only</span>' +
            '</div>' +
            '<div class="artifact-overlay-path">' + esc(path) + '</div>' +
          '</div>' +
          '<button id="btn-close-artifact" class="settings-btn">X</button>' +
        '</div>' +
        '<div class="artifact-overlay-body"><pre>' + esc(content) + '</pre></div>' +
      '</div>';
    document.body.appendChild(overlay);
  }

  // -- Workflow options --------------------------------------------------------

  function bindWorkflowOptions() {
    $$(".workflow-option").forEach(function (opt) {
      opt.onclick = function () {
        $$(".workflow-option").forEach(function (o) { o.classList.remove("selected"); });
        opt.classList.add("selected");
        selectedWorkflowPhase = opt.getAttribute("data-phase");
        var ta = $("#workflow-textarea");
        if (ta && !ta.value) {
          ta.placeholder = "Optional context for " + selectedWorkflowPhase + "...";
        }
      };
    });
  }

  // -- Card expand ------------------------------------------------------------

  function bindCardExpand() {
    $$(".activity-card-more").forEach(function (el) {
      el.onclick = function () {
        var body = el.previousElementSibling;
        if (body) body.classList.toggle("expanded");
        el.textContent = body && body.classList.contains("expanded") ? "show less" : "show more";
      };
    });
  }

  // -- Folder toggle ----------------------------------------------------------

  function bindFolderToggle() {
    $$(".tree-folder-label").forEach(function (el) {
      el.onclick = function () {
        var children = el.nextElementSibling;
        if (children) {
          children.style.display = children.style.display === "none" ? "" : "none";
        }
      };
    });
  }

  // -- API calls --------------------------------------------------------------

  function startRun() {
    var taskEl = $("#task-input");
    var task = taskEl ? taskEl.value.trim() : "";
    if (!task) { notify("Please enter a task description", "warning"); return; }

    var strong = $("#tier-strong");
    var standard = $("#tier-standard");
    var cheap = $("#tier-cheap");
    var scout = $("#scout-concurrency");

    var body = { task: task };
    if (strong && strong.value) {
      body.model_tiers = {
        strong: strong.value,
        standard: standard ? standard.value : "",
        cheap: cheap ? cheap.value : "",
      };
    }
    if (scout && scout.value) {
      body.scout_concurrency = parseInt(scout.value, 10) || 8;
    }

    fetch("/api/start-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          // Navigate to / which renders live.html now that start_event is set
          window.location.href = "/";
        } else {
          notify(d.message || "Failed to start", "error");
        }
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function submitAnswers(answers, token) {
    fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: answers, token: token || "" }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) notify(d.message || "Failed to submit", "error");
        questionIndex = 0;
        questionAnswers = {};
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function submitArtifactReview(response) {
    var token = ($("#artifact-review-form") || {}).getAttribute("data-token") || "";
    fetch("/api/artifact-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response: response, token: token }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) notify(d.message || "Failed to submit", "error");
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function submitWorkflowDecision() {
    var token = ($("#workflow-form") || {}).getAttribute("data-token") || "";
    var ta = $("#workflow-textarea");
    fetch("/api/workflow-decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phase: selectedWorkflowPhase || "",
        context: ta ? ta.value : "",
        token: token,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) notify(d.message || "Failed to submit", "error");
        selectedWorkflowPhase = null;
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function saveModelConfig() {
    var strong = $("#cfg-strong");
    var standard = $("#cfg-standard");
    var cheap = $("#cfg-cheap");
    var scout = $("#cfg-scout-concurrency");

    fetch("/api/model-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_tiers: {
          strong: strong ? strong.value : "",
          standard: standard ? standard.value : "",
          cheap: cheap ? cheap.value : "",
        },
        scout_concurrency: scout ? parseInt(scout.value, 10) || 8 : 8,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) {
          notify("Configuration saved", "info");
          var overlay = $("#model-config-overlay");
          if (overlay) overlay.hidden = true;
        } else {
          notify("Failed to save config", "error");
        }
      })
      .catch(function () { notify("Network error", "error"); });
  }

  // -- Init -------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    connectSSE();
    bindDynamicHandlers();
  });
})();
