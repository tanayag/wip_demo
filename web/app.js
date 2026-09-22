(function () {
  "use strict";

  var OBJECTIVES = {};
  var CASES = [];
  var runs = [];
  var current = null;
  var running = false;
  var serverMode = "live";
  var modeOverride = null;
  var modeLabelLive = "Live";

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

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
  }).catch(function () { $("modeline").textContent = "Server not reachable"; });

  function effectiveMode() { return modeOverride || serverMode; }

  function renderModeline() {
    var m = effectiveMode();
    var el = $("modeline");
    el.textContent = m === "replay" ? "Replay (scripted)" : modeLabelLive;
    el.className = "modeline" + (m === "replay" ? " replay" : "");
    $("mode-live").className = m === "live" ? "on" : "";
    $("mode-replay").className = m === "replay" ? "on" : "";
  }

  // ----- cards ------------------------------------------------------------

  function renderCards() {
    $("cards").innerHTML = CASES.map(function (c) {
      return '<article class="card" id="card-' + c.id + '">' +
        '<div class="who"><b>' + esc(c.customer) + '</b><span>' + esc(c.order_id) + '</span></div>' +
        '<p class="msg">' + esc(c.message) + '</p>' +
        '<div class="outcome">' +
          '<div class="pills"><span class="pill none">Waiting for a run</span></div>' +
          '<p class="reply empty"></p>' +
          '<span class="trace-toggle">what it did</span>' +
          '<div class="trace"></div>' +
        '</div></article>';
    }).join("");
  }

  function pillsFor(result) {
    var st = result.state || {};
    var out = [];
    (st.refunds || []).forEach(function (r) { out.push('<span class="pill refund">Refunded Rs ' + Math.round(r.amount) + '</span>'); });
    if ((st.denials || []).length) out.push('<span class="pill deny">Denied</span>');
    (st.escalations || []).forEach(function (e) { out.push('<span class="pill escalate">Escalated to ' + esc(e.team) + '</span>'); });
    if (!out.length) out.push('<span class="pill none">No action taken</span>');
    return out.join("");
  }

  function traceFor(result) {
    return (result.actions || []).map(function (a) {
      var o = a.output || {}, g = a.args || {};
      if (a.tool === "lookup") {
        if (o.error) return "Looked up " + esc(g.order_id) + ": " + esc(o.error);
        var bits = [];
        bits.push(o.late_by_minutes > 0 ? o.late_by_minutes + " min late" : "delivered on time");
        bits.push(o.refunds_this_month + " refund" + (o.refunds_this_month === 1 ? "" : "s") + " this month");
        bits.push("Rs " + o.order_amount_inr);
        if (o.hours_since_delivery >= 24) bits.push(Math.round(o.hours_since_delivery / 24) + " days ago");
        return "Looked up " + esc(o.order_id || g.order_id) + ": " + bits.join(", ") + (o.refund_policy ? ". Read the policy." : "");
      }
      if (a.tool === "refund") return "Refunded Rs " + Math.round(g.amount || 0) + (g.reason ? ": " + esc(g.reason) : "");
      if (a.tool === "deny") return "Denied" + (g.reason ? ": " + esc(g.reason) : "");
      if (a.tool === "escalate") return "Escalated to " + esc(g.team) + (g.reason ? ": " + esc(g.reason) : "");
      return esc(a.tool);
    }).map(function (line) { return "<div>" + line + "</div>"; }).join("") || "<div>No tool calls.</div>";
  }

  function setCard(id, state, result) {
    var card = $("card-" + id);
    if (!card) return;
    var pills = card.querySelector(".pills");
    var reply = card.querySelector(".reply");
    var trace = card.querySelector(".trace");
    card.classList.remove("done");
    reply.classList.remove("open");
    if (state === "thinking") {
      pills.innerHTML = '<span class="pill thinking">Thinking</span>';
      reply.className = "reply empty"; reply.textContent = "";
      trace.innerHTML = "";
      return;
    }
    if (state === "idle") {
      pills.innerHTML = '<span class="pill none">Waiting for a run</span>';
      reply.className = "reply empty"; reply.textContent = "";
      trace.innerHTML = "";
      return;
    }
    card.classList.add("done");
    if (result.error && !result.reply) {
      pills.innerHTML = '<span class="pill error">' + esc(shortError(result.error)) + '</span>';
      reply.className = "reply empty"; reply.textContent = "The model could not be reached.";
    } else {
      pills.innerHTML = pillsFor(result);
      reply.className = "reply"; reply.textContent = result.reply;
    }
    trace.innerHTML = traceFor(result);
  }

  function shortError(e) {
    if (/credential|token|expired/i.test(e)) return "AWS credentials problem";
    if (/timeout|timed out|EndpointConnection|Connection/i.test(e)) return "No connection to Bedrock";
    if (/AccessDenied/i.test(e)) return "Bedrock access denied";
    if (/Throttl/i.test(e)) return "Bedrock throttled the request";
    return e.slice(0, 50);
  }

  // ----- run --------------------------------------------------------------

  function runAll() {
    if (running || !CASES.length) return;
    var objective = $("objective").value.trim();
    if (!objective) { $("objective").focus(); return; }
    running = true;
    $("run").disabled = true;
    document.body.classList.remove("traces");
    var run = { n: runs.length + 1, objective: objective, results: {}, mode_label: "" };
    runs.push(run);
    current = run;
    CASES.forEach(function (c) { setCard(c.id, "thinking"); });
    renderStats();
    renderHistory();
    var body = { objective: objective };
    if (modeOverride) body.mode = modeOverride;
    Promise.all(CASES.map(function (c) {
      return fetch("api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ case_id: c.id }, body)) })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
        .catch(function (err) { return { case_id: c.id, reply: "", error: String(err.message || err), state: {}, actions: [], resolved: false, refunded: false, refunded_total: 0, elapsed_s: 0, mode_label: "" }; })
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

  // ----- scoreboard -------------------------------------------------------

  function tally(run) {
    var t = { done: 0, resolved: 0, happy: 0, time: 0, refunded: 0 };
    if (!run) return t;
    CASES.forEach(function (c) {
      var r = run.results[c.id];
      if (!r) return;
      t.done += 1;
      if (r.resolved) t.resolved += 1;
      if (r.refunded) t.happy += 1;
      t.time += r.elapsed_s || 0;
      t.refunded += r.refunded_total || 0;
    });
    return t;
  }

  function stat(label, value) {
    return '<div class="stat"><div class="label">' + label + '</div><div class="value">' + value + '</div></div>';
  }

  function renderStats() {
    var t = tally(current);
    var n = CASES.length || 5;
    var el = $("stats");
    if (!current) {
      el.className = "score";
      el.innerHTML = stat("Resolved in one message", "–") + stat("Happy customers", "–") + stat("Avg time", "–");
      return;
    }
    el.className = "score" + (t.done ? " live" : "");
    el.innerHTML = stat("Resolved in one message", t.resolved + "/" + n) +
                   stat("Happy customers (refunds given)", t.happy) +
                   stat("Avg time", t.done ? (t.time / t.done).toFixed(1) + "<small>s</small>" : "–");
  }

  // ----- history ----------------------------------------------------------

  function renderHistory() {
    var el = $("history");
    if (!runs.length) { el.innerHTML = ""; return; }
    var rows = runs.slice().reverse().map(function (run) {
      var t = tally(run);
      var full = t.done === CASES.length;
      var obj = run.objective.length > 90 ? run.objective.slice(0, 88) + "…" : run.objective;
      return '<tr data-n="' + run.n + '"' + (run === current ? ' class="current"' : "") + '>' +
        '<td class="n">' + run.n + '</td>' +
        '<td class="obj">' + esc(obj) + '</td>' +
        '<td class="num">' + (full ? "resolved " + t.resolved + "/" + CASES.length + " · refunds " + t.happy : "running…") + '</td>' +
        '<td class="mode">' + esc(run.mode_label || "") + '</td></tr>';
    }).join("");
    el.innerHTML = '<div class="eyebrow">Runs</div><table><tbody>' + rows + '</tbody></table>';
  }

  // ----- events -----------------------------------------------------------

  $("run").addEventListener("click", runAll);
  $("cards").addEventListener("click", function (e) {
    var card = e.target.closest(".card"); if (!card) return;
    if (e.target.classList.contains("trace-toggle")) {
      var tr = card.querySelector(".trace");
      tr.style.display = tr.style.display === "block" ? "" : "block";
    } else if (e.target.classList.contains("reply")) {
      e.target.classList.toggle("open");
    }
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
    if (a.hasAttribute("data-preset")) $("objective").value = OBJECTIVES[a.getAttribute("data-preset")] || "";
    else if (a.hasAttribute("data-mode")) { modeOverride = a.getAttribute("data-mode"); renderModeline(); }
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
    else if (k === "t") { e.preventDefault(); document.body.classList.toggle("traces"); }
    else if (k >= "1" && k <= "5") {
      var c = CASES[parseInt(k, 10) - 1]; if (!c) return;
      var card = $("card-" + c.id);
      Array.prototype.forEach.call(document.querySelectorAll(".card.focus"), function (el) { el.classList.remove("focus"); });
      card.classList.add("focus");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(function () { card.classList.remove("focus"); }, 2500);
    }
  });
})();
