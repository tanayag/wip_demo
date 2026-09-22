(function () {
  "use strict";

  var OBJECTIVES = {};
  var CASES = [];
  var runs = [];          // {n, objective, results: {case_id: result}, mode_label}
  var current = null;     // run being shown
  var view = "bot";
  var running = false;
  var serverMode = "live";
  var modeOverride = null; // null = server default
  var modeLabelLive = "Live";

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  // ----- boot ---------------------------------------------------------------

  fetch("api/cases").then(function (r) { return r.json(); }).then(function (d) {
    CASES = d.cases;
    OBJECTIVES = d.objectives || {};
    serverMode = d.mode;
    modeLabelLive = d.mode_label;
    if (!$("objective").value) $("objective").value = OBJECTIVES.A || "";
    renderCards();
    renderModeline();
    renderStats();
    try {
      var saved = JSON.parse(localStorage.getItem("refund-bot-runs") || "[]");
      if (Array.isArray(saved)) { runs = saved; renderHistory(); }
    } catch (e) { /* ignore */ }
  }).catch(function () {
    $("modeline").textContent = "Server not reachable";
  });

  function effectiveMode() { return modeOverride || serverMode; }

  function renderModeline() {
    var m = effectiveMode();
    var el = $("modeline");
    el.textContent = m === "replay" ? "Replay (scripted)" : modeLabelLive;
    el.className = "modeline" + (m === "replay" ? " replay" : "");
    $("mode-live").className = m === "live" ? "on" : "";
    $("mode-replay").className = m === "replay" ? "on" : "";
  }

  // ----- cards --------------------------------------------------------------

  function renderCards() {
    var html = CASES.map(function (c, i) {
      return '<article class="card" id="card-' + c.id + '" data-idx="' + (i + 1) + '">' +
        '<div class="who"><b>' + esc(c.customer) + '</b><span>' + esc(c.order_id) + '</span></div>' +
        '<p class="msg">' + esc(c.message) + '</p>' +
        '<div class="rule"></div>' +
        '<p class="reply empty">Waiting for a run.</p>' +
        '<div class="action"></div>' +
        '<div class="why"></div>' +
        '<div class="ok">Right call.</div>' +
        '</article>';
    }).join("");
    $("cards").innerHTML = html;
  }

  function setCard(id, state, result) {
    var card = $("card-" + id);
    if (!card) return;
    var reply = card.querySelector(".reply");
    var action = card.querySelector(".action");
    var why = card.querySelector(".why");
    card.classList.remove("correct", "wrong");
    if (state === "thinking") {
      reply.className = "reply thinking";
      reply.textContent = "Thinking";
      action.textContent = "";
      action.className = "action";
      why.textContent = "";
      return;
    }
    if (state === "idle") {
      reply.className = "reply empty";
      reply.textContent = "Waiting for a run.";
      action.textContent = "";
      action.className = "action";
      why.textContent = "";
      return;
    }
    if (result.error && !result.reply) {
      reply.className = "reply empty";
      reply.textContent = "The model could not be reached.";
      action.className = "action error";
      action.textContent = shortError(result.error);
    } else {
      reply.className = "reply";
      reply.textContent = result.reply;
      action.className = "action";
      action.textContent = result.action_line;
    }
    why.textContent = (result.audit && result.audit.reasons || []).join(" ");
    card.classList.add(result.audit && result.audit.correct ? "correct" : "wrong");
  }

  function shortError(e) {
    if (/credential|token|expired/i.test(e)) return "AWS credentials problem";
    if (/timeout|timed out|EndpointConnection|Connection/i.test(e)) return "No connection to Bedrock";
    if (/AccessDenied/i.test(e)) return "Bedrock access denied for this model";
    if (/Throttl/i.test(e)) return "Bedrock throttled the request";
    return e.slice(0, 60);
  }

  // ----- run ----------------------------------------------------------------

  function runAll() {
    if (running || !CASES.length) return;
    var objective = $("objective").value.trim();
    if (!objective) { $("objective").focus(); return; }
    running = true;
    $("run").disabled = true;
    var run = { n: runs.length + 1, objective: objective, results: {}, mode_label: "", started: Date.now() };
    runs.push(run);
    current = run;
    CASES.forEach(function (c) { setCard(c.id, "thinking"); });
    renderStats();
    renderHistory();
    var body = { objective: objective };
    if (modeOverride) body.mode = modeOverride;
    Promise.all(CASES.map(function (c) {
      var b = Object.assign({ case_id: c.id }, body);
      return fetch("api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .catch(function (err) {
          return { case_id: c.id, reply: "", action_line: "", error: String(err.message || err), audit: { correct: false, reasons: ["The request failed: " + (err.message || err)] }, resolved: false, refunded: false, elapsed_s: 0, mode_label: "" };
        })
        .then(function (res) {
          run.results[c.id] = res;
          if (res.mode_label) run.mode_label = res.mode_label;
          if (current === run) { setCard(c.id, "done", res); renderStats(); }
        });
    })).then(function () {
      running = false;
      $("run").disabled = false;
      renderStats();
      renderHistory();
      try { localStorage.setItem("refund-bot-runs", JSON.stringify(runs.slice(-30))); } catch (e) { /* ignore */ }
    });
  }

  function showRun(run) {
    current = run;
    $("objective").value = run.objective;
    CASES.forEach(function (c) {
      var r = run.results[c.id];
      if (r) setCard(c.id, "done", r); else setCard(c.id, running && run === runs[runs.length - 1] ? "thinking" : "idle");
    });
    renderStats();
    renderHistory();
  }

  // ----- scoreboard ---------------------------------------------------------

  function tally(run) {
    var t = { done: 0, resolved: 0, happy: 0, right: 0, time: 0, refunded: 0 };
    if (!run) return t;
    CASES.forEach(function (c) {
      var r = run.results[c.id];
      if (!r) return;
      t.done += 1;
      if (r.resolved) t.resolved += 1;
      if (r.refunded) t.happy += 1;
      if (r.audit && r.audit.correct) t.right += 1;
      t.time += r.elapsed_s || 0;
      t.refunded += r.refunded_total || 0;
    });
    return t;
  }

  function stat(cls, label, value, unit) {
    return '<div class="stat ' + cls + '"><div class="label">' + label + '</div><div class="value">' + value + (unit ? "<small>" + unit + "</small>" : "") + '</div></div>';
  }

  function renderStats() {
    var t = tally(current);
    var n = CASES.length || 5;
    var avg = t.done ? (t.time / t.done).toFixed(1) + "s" : "–";
    var html;
    if (!current) {
      html = stat("muted", "Resolved in one message", "–") + stat("muted", "Happy customers", "–") + stat("muted", "Avg time", "–");
    } else if (view === "bot") {
      html = stat("", "Resolved in one message", t.resolved + "/" + n) +
             stat("", "Happy customers (refunds given)", t.happy) +
             stat("", "Avg time", avg);
    } else {
      html = stat("headline" + (t.done === n && t.right === n ? " all-right" : ""), "Right calls", t.right + "/" + n) +
             stat("muted", "Refunded", "Rs " + Math.round(t.refunded)) +
             stat("muted", "Avg time", avg);
    }
    $("stats").innerHTML = html;
  }

  function setView(v) {
    view = v;
    document.body.className = "view-" + v;
    var btns = $("toggle").querySelectorAll("button");
    for (var i = 0; i < btns.length; i++) btns[i].className = btns[i].getAttribute("data-view") === v ? "on" : "";
    renderStats();
  }

  // ----- history ------------------------------------------------------------

  function renderHistory() {
    var el = $("history");
    if (!runs.length) { el.innerHTML = ""; return; }
    var rows = runs.slice().reverse().map(function (run) {
      var t = tally(run);
      var full = t.done === CASES.length;
      var cls = !full ? "" : (t.right === CASES.length ? "good" : "bad");
      var obj = run.objective.length > 90 ? run.objective.slice(0, 88) + "…" : run.objective;
      return '<tr data-n="' + run.n + '"' + (run === current ? ' class="current"' : "") + '>' +
        '<td class="n">' + run.n + '</td>' +
        '<td class="obj">' + esc(obj) + '</td>' +
        '<td class="right ' + cls + '">' + (full ? "right calls " + t.right + "/" + CASES.length : "running…") + '</td>' +
        '<td class="mode">' + esc(run.mode_label || "") + '</td></tr>';
    }).join("");
    el.innerHTML = '<div class="eyebrow">Runs</div><table><tbody>' + rows + '</tbody></table>';
  }

  // ----- events -------------------------------------------------------------

  $("run").addEventListener("click", runAll);
  $("toggle").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (b) setView(b.getAttribute("data-view"));
  });
  $("history").addEventListener("click", function (e) {
    var tr = e.target.closest("tr"); if (!tr) return;
    var n = parseInt(tr.getAttribute("data-n"), 10);
    var run = runs.filter(function (r) { return r.n === n; })[0];
    if (run) showRun(run);
  });
  document.querySelector(".foot").addEventListener("click", function (e) {
    var a = e.target.closest("a"); if (!a) return;
    e.preventDefault();
    if (a.hasAttribute("data-preset")) {
      $("objective").value = OBJECTIVES[a.getAttribute("data-preset")] || "";
    } else if (a.hasAttribute("data-mode")) {
      modeOverride = a.getAttribute("data-mode");
      renderModeline();
    }
  });
  $("objective").addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); runAll(); }
    if (e.key === "Escape") $("objective").blur();
  });
  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "input" || e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key.toLowerCase();
    if (k === "r") { e.preventDefault(); runAll(); }
    else if (k === "e") { e.preventDefault(); setView(view === "bot" ? "policy" : "bot"); }
    else if (k >= "1" && k <= "5") {
      var c = CASES[parseInt(k, 10) - 1]; if (!c) return;
      var card = $("card-" + c.id);
      var all = document.querySelectorAll(".card.focus");
      for (var i = 0; i < all.length; i++) all[i].classList.remove("focus");
      card.classList.add("focus");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(function () { card.classList.remove("focus"); }, 2500);
    }
  });

  setView("bot");
})();
