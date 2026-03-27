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

  // Cached data for settings overlay cascade dropdowns
  var cachedProbeData = null;

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
            // Reset workflow state when a new workflow-decision interaction arrives
            if (evt === "workflow-decision") {
              selectedWorkflowPhase = null;
            }
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

    // Settings open (gear button on landing header)
    if (tgt.classList.contains("settings-btn") || tgt.closest(".settings-btn")) {
      // Close button inside overlay
      if (tgt.id === "btn-close-settings" || (tgt.closest("#btn-close-settings"))) {
        var ov = $("#settings-overlay");
        if (ov) ov.hidden = true;
        return;
      }
      // Close artifact overlay button (reuses settings-btn class)
      if (tgt.id === "btn-close-artifact") {
        var artOv = $(".artifact-overlay");
        if (artOv) artOv.remove();
        return;
      }
      openSettingsOverlay();
      return;
    }

    // Artifact overlay close (backdrop click)
    if (tgt.classList.contains("artifact-overlay")) {
      var ov = $(".artifact-overlay");
      if (ov) ov.remove();
      return;
    }

    // Artifact review accept
    if (tgt.id === "btn-accept-artifact" || tgt.closest("#btn-accept-artifact")) {
      submitArtifactReview(null, true);
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
      var cfg = $("#settings-overlay");
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

    var profileSel = $("#profile-select");
    var profile = profileSel ? profileSel.value : "";
    if (!profile) { notify("Please select a profile", "warning"); return; }

    var scout = $("#scout-concurrency");

    var body = { task: task, profile: profile };
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

  function submitArtifactReview(response, accepted) {
    var token = ($("#artifact-review-form") || {}).getAttribute("data-token") || "";
    var body = accepted
      ? { accepted: true, token: token }
      : { response: response, token: token };
    fetch("/api/artifact-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) notify(d.message || "Failed to submit", "error");
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function submitWorkflowDecision() {
    if (!selectedWorkflowPhase) {
      notify("Please select a phase before continuing", "warning");
      return;
    }
    var token = ($("#workflow-form") || {}).getAttribute("data-token") || "";
    var ta = $("#workflow-textarea");
    fetch("/api/workflow-decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phase: selectedWorkflowPhase,
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

  // -- Settings overlay -------------------------------------------------------

  // Comment 2 fix: one-time binding guard for delegated settings listener
  var settingsHandlersBound = false;

  function openSettingsOverlay() {
    var overlay = $("#settings-overlay");
    if (!overlay) return;
    overlay.hidden = false;

    var body = $("#settings-overlay-body");
    if (body) body.innerHTML = '<p class="settings-section-heading">Loading...</p>';

    // Fetch probe data (for cascade dropdowns) and server-rendered body fragment
    Promise.all([
      fetch("/api/probe").then(function (r) { return r.json(); }),
      fetch("/api/settings/body").then(function (r) { return r.text(); }),
    ])
      .then(function (results) {
        cachedProbeData = results[0];
        if (body) body.innerHTML = results[1];
        bindSettingsHandlers();
      })
      .catch(function () {
        notify("Failed to load settings", "error");
      });
  }

  function bindCascadeDropdowns(formEl) {
    if (!cachedProbeData) return;
    var runners = cachedProbeData.runners || [];

    formEl.querySelectorAll(".tier-runner-select").forEach(function (runnerSel) {
      var tier = runnerSel.getAttribute("data-tier");
      var modelSel = formEl.querySelector('.tier-model-select[data-tier="' + tier + '"]');
      var thinkingSel = formEl.querySelector('.tier-thinking-select[data-tier="' + tier + '"]');
      if (!modelSel || !thinkingSel) return;

      // Comment 1 fix: read initial values from data attributes
      var initialModel = modelSel.getAttribute("data-initial") || "";
      var initialThinking = thinkingSel.getAttribute("data-initial") || "";

      function populateModels() {
        var rt = runnerSel.value;
        var prev = modelSel.value || initialModel;
        modelSel.innerHTML = '<option value="">-- model --</option>';
        var matched = false;
        runners.forEach(function (r) {
          if (r.runner_type !== rt) return;
          (r.models || []).forEach(function (m) {
            var opt = document.createElement("option");
            opt.value = m.alias;
            opt.textContent = m.display_name || m.alias;
            if (m.alias === prev) { opt.selected = true; matched = true; }
            modelSel.appendChild(opt);
          });
        });
        // Clear consumed initial value
        initialModel = "";
        populateThinking();
      }

      function populateThinking() {
        var rt = runnerSel.value;
        var model = modelSel.value;
        var prev = thinkingSel.value || initialThinking;
        thinkingSel.innerHTML = '<option value="">-- thinking --</option>';
        var matched = false;
        var firstOpt = null;
        runners.forEach(function (r) {
          if (r.runner_type !== rt) return;
          (r.models || []).forEach(function (m) {
            if (m.alias !== model) return;
            (m.thinking_modes || []).forEach(function (tm) {
              var opt = document.createElement("option");
              opt.value = tm;
              opt.textContent = tm;
              if (!firstOpt) firstOpt = opt;
              if (tm === prev) { opt.selected = true; matched = true; }
              thinkingSel.appendChild(opt);
            });
          });
        });
        // Comment 4 fix: auto-select first valid thinking mode when previous is invalid
        if (!matched && firstOpt) {
          firstOpt.selected = true;
        }
        // Clear consumed initial value
        initialThinking = "";
      }

      runnerSel.addEventListener("change", function () {
        initialModel = "";
        initialThinking = "";
        populateModels();
      });
      modelSel.addEventListener("change", function () {
        initialThinking = "";
        populateThinking();
      });

      // Trigger initial cascade if runner is pre-selected
      if (runnerSel.value) populateModels();
    });
  }

  function bindSettingsHandlers() {
    // New profile toggle
    var btnNew = $("#btn-new-profile");
    var newContainer = $("#new-profile-form-container");
    if (btnNew && newContainer) {
      btnNew.onclick = function () {
        fetch("/api/settings/profile-form")
          .then(function (r) { return r.text(); })
          .then(function (html) {
            newContainer.innerHTML = html;
            newContainer.hidden = false;
            btnNew.hidden = true;
            bindCascadeDropdowns(newContainer);
          })
          .catch(function () { notify("Failed to load form", "error"); });
      };
    }

    // New installation toggle
    var btnNewInst = $("#btn-new-installation");
    var newInstContainer = $("#new-installation-form-container");
    if (btnNewInst && newInstContainer) {
      btnNewInst.onclick = function () {
        fetch("/api/settings/installation-form")
          .then(function (r) { return r.text(); })
          .then(function (html) {
            newInstContainer.innerHTML = html;
            newInstContainer.hidden = false;
            btnNewInst.hidden = true;
          })
          .catch(function () { notify("Failed to load form", "error"); });
      };
    }

    // Comment 2 fix: attach delegated listener exactly once
    var body = $("#settings-overlay-body");
    if (!body || settingsHandlersBound) return;
    settingsHandlersBound = true;

    body.addEventListener("click", function (e) {
      var tgt = e.target;

      // Cancel profile form
      if (tgt.classList.contains("btn-cancel-profile")) {
        var container = tgt.closest("#new-profile-form-container") || tgt.closest("#edit-profile-form-container");
        if (container) {
          container.hidden = true;
          var btn = $("#btn-new-profile");
          if (container.id === "new-profile-form-container" && btn) btn.hidden = false;
        }
        return;
      }

      // Cancel installation form
      if (tgt.classList.contains("btn-cancel-inst")) {
        var container = tgt.closest("#new-installation-form-container") || tgt.closest("#edit-installation-form-container");
        if (container) {
          container.hidden = true;
          var btn = $("#btn-new-installation");
          if (container.id === "new-installation-form-container" && btn) btn.hidden = false;
        }
        return;
      }

      // Save profile
      if (tgt.classList.contains("btn-save-profile")) {
        saveProfile(tgt);
        return;
      }

      // Delete profile
      if (tgt.classList.contains("btn-delete-profile")) {
        var name = tgt.getAttribute("data-name");
        fetch("/api/profiles/" + encodeURIComponent(name), { method: "DELETE" })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) { openSettingsOverlay(); refreshProfileSelect(); }
            else notify(d.message || "Failed to delete", "error");
          })
          .catch(function () { notify("Network error", "error"); });
        return;
      }

      // Edit profile -- fetch server-rendered form with initial tier values
      if (tgt.classList.contains("btn-edit-profile")) {
        var name = tgt.getAttribute("data-name");
        var editContainer = $("#edit-profile-form-container");
        if (!editContainer) return;
        fetch("/api/settings/profile-form?edit=1&name=" + encodeURIComponent(name))
          .then(function (r) { return r.text(); })
          .then(function (html) {
            editContainer.innerHTML = html;
            editContainer.hidden = false;
            bindCascadeDropdowns(editContainer);
          })
          .catch(function () { notify("Failed to load form", "error"); });
        return;
      }

      // Delete installation
      if (tgt.classList.contains("btn-delete-inst")) {
        var alias = tgt.getAttribute("data-alias");
        fetch("/api/agents/" + encodeURIComponent(alias), { method: "DELETE" })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) openSettingsOverlay();
            else notify(d.message || "Failed to delete", "error");
          })
          .catch(function () { notify("Network error", "error"); });
        return;
      }

      // Set active installation
      if (tgt.classList.contains("btn-set-active-inst")) {
        var alias = tgt.getAttribute("data-alias");
        var rt = tgt.getAttribute("data-runner");
        fetch("/api/agents/" + encodeURIComponent(rt) + "/active", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ alias: alias }),
        })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) openSettingsOverlay();
            else notify(d.message || "Failed to set active", "error");
          })
          .catch(function () { notify("Network error", "error"); });
        return;
      }

      // Edit installation -- fetch server-rendered form
      if (tgt.classList.contains("btn-edit-inst")) {
        var alias = tgt.getAttribute("data-alias");
        var editContainer = $("#edit-installation-form-container");
        if (!editContainer) return;
        fetch("/api/settings/installation-form?edit=1&alias=" + encodeURIComponent(alias))
          .then(function (r) { return r.text(); })
          .then(function (html) {
            editContainer.innerHTML = html;
            editContainer.hidden = false;
          })
          .catch(function () { notify("Failed to load form", "error"); });
        return;
      }

      // Save installation
      if (tgt.classList.contains("btn-save-inst")) {
        saveInstallation(tgt);
        return;
      }

      // Detect binary
      if (tgt.classList.contains("btn-detect-binary")) {
        var form = tgt.closest(".profile-form");
        var rtSel = form ? form.querySelector(".inst-runner-select") : null;
        var rt = rtSel ? rtSel.value : "";
        if (!rt) { notify("Select a runner type first", "warning"); return; }
        fetch("/api/agents/detect?runner_type=" + encodeURIComponent(rt))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            var binInput = form ? form.querySelector(".inst-binary-input") : null;
            if (binInput && d.path) binInput.value = d.path;
            else if (!d.path) notify("Binary not found in PATH", "warning");
          })
          .catch(function () { notify("Detection failed", "error"); });
        return;
      }
    });

    // Refresh button
    var btnRefresh = $("#btn-refresh-probe");
    if (btnRefresh) {
      btnRefresh.onclick = function () { openSettingsOverlay(); };
    }
  }

  // Comment 1 fix: preserve unchanged tiers when editing profiles
  function saveProfile(btn) {
    var isEdit = btn.getAttribute("data-edit") === "1";
    var form = btn.closest(".profile-form");
    if (!form) return;

    var nameInput = form.querySelector(".profile-name-input");
    var name = isEdit ? btn.getAttribute("data-name") : (nameInput ? nameInput.value.trim() : "");
    if (!name) { notify("Profile name is required", "warning"); return; }

    var tiers = {};
    ["strong", "standard", "cheap"].forEach(function (tier) {
      var rt = form.querySelector('.tier-runner-select[data-tier="' + tier + '"]');
      var model = form.querySelector('.tier-model-select[data-tier="' + tier + '"]');
      var thinking = form.querySelector('.tier-thinking-select[data-tier="' + tier + '"]');
      if (rt && rt.value && model && model.value) {
        tiers[tier] = {
          runner_type: rt.value,
          model: model.value,
          thinking: thinking ? thinking.value || "disabled" : "disabled",
        };
      }
    });

    var url = isEdit ? "/api/profiles/" + encodeURIComponent(name) : "/api/profiles";
    var method = isEdit ? "PUT" : "POST";
    var payload = isEdit ? { tiers: tiers } : { name: name, tiers: tiers };

    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) { openSettingsOverlay(); refreshProfileSelect(); }
        else notify(d.message || "Failed to save profile", "error");
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function saveInstallation(btn) {
    var isEdit = btn.getAttribute("data-edit") === "1";
    var form = btn.closest(".profile-form");
    if (!form) return;

    var aliasInput = form.querySelector(".inst-alias-input");
    var alias = aliasInput ? aliasInput.value.trim() : "";
    if (!alias) { notify("Alias is required", "warning"); return; }

    var rtSel = form.querySelector(".inst-runner-select");
    var binInput = form.querySelector(".inst-binary-input");
    var argsInput = form.querySelector(".inst-extra-args-input");

    var payload = {
      alias: alias,
      runner_type: rtSel ? rtSel.value : "",
      binary: binInput ? binInput.value.trim() : "",
      extra_args: argsInput && argsInput.value.trim()
        ? argsInput.value.trim().split(/\s+/) : [],
    };

    var url = isEdit ? "/api/agents/" + encodeURIComponent(alias) : "/api/agents";
    var method = isEdit ? "PUT" : "POST";

    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.ok) openSettingsOverlay();
        else notify(d.message || "Failed to save installation", "error");
      })
      .catch(function () { notify("Network error", "error"); });
  }

  function refreshProfileSelect() {
    fetch("/api/profiles")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var sel = $("#profile-select");
        if (!sel) return;
        var prev = sel.value;
        sel.innerHTML = "";
        (d.profiles || []).forEach(function (p) {
          var opt = document.createElement("option");
          opt.value = p.name;
          opt.textContent = p.name + (p.read_only ? " (built-in)" : "");
          if (p.name === prev) opt.selected = true;
          sel.appendChild(opt);
        });
      })
      .catch(function () { /* ignore */ });
  }

  // -- Init -------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    connectSSE();
    bindDynamicHandlers();
  });
})();
