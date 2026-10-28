/* Report front end. Numbers come from window.SEASON (season analyses), window.EXPLORER_INDEX
   (per-track sums for the track views) and per-track files loaded on demand from
   data/explorer/ and data/events/, all written by `aerotwin report`. One filter bar (season,
   Aston Martin drivers, tracks) drives the page; each section says which filters it follows. */
(function () {
  "use strict";
  var S = window.SEASON;
  var XI = window.EXPLORER_INDEX || { events: [], drivers: {}, names: {} };
  var TARGET = "Aston Martin";
  var SECS = ["straights", "high", "medium", "low"];
  var SEC_LABEL = { straights: "straights", high: "high-speed corners", medium: "medium-speed corners", low: "low-speed corners" };
  var SEC_SHORT = { straights: "Straights", high: "High-speed", medium: "Medium", low: "Low-speed" };
  var groups = { season: [], tracks: [], detail: [], fixed: [] };
  var state = { season: null, drivers: {}, tracks: {}, focus: {}, mapDriver: null, straight: 0 };
  var current = { event: null, detail: null, entry: null };

  // Helpers
  function $(id) { return document.getElementById(id); }
  // A CSS custom property where `el` sits (bands set their own colours), else at the root
  function css(name, el) { return getComputedStyle(el || document.documentElement).getPropertyValue(name).trim(); }
  // Typographic minus; a value that rounds to zero loses its sign
  function f(x, d) { return x == null || !isFinite(x) ? "–" : Number(x).toFixed(d == null ? 1 : d).replace(/^-(?=.*[1-9])/, "−").replace(/^-/, ""); }
  function sgn(x, d) {
    if (x == null || !isFinite(x)) return "–";
    var s = Math.abs(x).toFixed(d == null ? 1 : d);
    return (+s === 0 ? "" : x > 0 ? "+" : "−") + s;  // a value that rounds to zero has no sign
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function short(ev) { return ev.replace(" Grand Prix", ""); }
  function fill(key, html) { document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (el) { el.innerHTML = html; }); }
  function byKey(arr, k) { var o = {}; arr.forEach(function (r) { (o[r[k]] = o[r[k]] || []).push(r); }); return o; }
  function mean(a) { a = a.filter(function (v) { return v != null && isFinite(v); }); return a.length ? a.reduce(function (s, v) { return s + v; }, 0) / a.length : NaN; }
  function median(a) { a = a.filter(function (v) { return v != null && isFinite(v); }).sort(function (x, y) { return x - y; }); return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : NaN; }
  function ord(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function day(iso) { var p = String(iso || "").split("-"); return p.length === 3 ? +p[2] + " " + MONTHS[+p[1] - 1] + " " + p[0] : String(iso || ""); }
  function shortDay(iso) { var p = String(iso || "").split("-"); return p.length === 3 ? +p[2] + " " + MONTHS[+p[1] - 1].slice(0, 3) : String(iso || ""); }
  function lapTime(s) { if (s == null || !isFinite(s)) return "–"; var m = Math.floor(s / 60), r = s - 60 * m; return m + ":" + (r < 10 ? "0" : "") + r.toFixed(3); }
  function list(a) { return a.length < 2 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1]; }
  function pct(x, d) { return x == null || !isFinite(x) ? "–" : f(100 * x, d == null ? 0 : d) + "%"; }
  var CARD = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  function count(n) { return n >= 0 && n < CARD.length && n % 1 === 0 ? CARD[n] : String(n); }
  function cap1(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function sum(a) { return a.reduce(function (s, v) { return s + v; }, 0); }
  function corr(a, b) {
    var ma = mean(a), mb = mean(b), sab = 0, saa = 0, sbb = 0;
    a.forEach(function (x, i) { var da = x - ma, db = b[i] - mb; sab += da * db; saa += da * da; sbb += db * db; });
    return sab / Math.sqrt(saa * sbb);
  }
  // Label and value pairs as numbers on rules
  function dl(rows) { return rows.filter(function (r) { return r; }).map(function (r) { return "<div><dt>" + r[0] + "</dt><dd>" + r[1] + "</dd></div>"; }).join(""); }
  var ARROW = '<svg width="18" height="12" viewBox="0 0 18 12" fill="none" aria-hidden="true"><path d="M0 6h16M11 1l5 5-5 5" stroke="currentColor" stroke-width="1.5"/></svg>';
  function hexA(hex, a) {
    var h = hex.replace("#", ""); if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + a + ")";
  }
  function interp(xs, ys, x) {
    var lo = 0, hi = xs.length - 1;
    if (x <= xs[0]) return ys[0]; if (x >= xs[hi]) return ys[hi];
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
    return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]);
  }

  // Chart colours from the tokens where the chart sits (`el`), else the root's. Green is always
  // Aston Martin and other teams are grey; loss and gain only mark time lost or gained.
  function theme(el) {
    function c(n) { return css(n, el); }
    return { ink: c("--ink"), ink2: c("--ink-2"), muted: c("--muted"), rule: c("--rule"), surface: c("--surface"),
      amr: c("--amr"), ref: c("--ref"), alt: c("--alt"), field: c("--field"), field2: c("--field-2"), loss: c("--loss"), gain: c("--gain"),
      bg: c("--band-bg"), font: c("--font") };
  }
  function axis(t, extra) {
    return Object.assign({ gridcolor: t.rule, zerolinecolor: t.muted, linecolor: t.rule, tickfont: { color: t.muted, family: t.font, size: 11 },
      titlefont: { color: t.ink2, size: 12 }, automargin: true, zeroline: false }, extra || {});
  }
  function layout(t, extra) {
    var base = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { family: t.font, color: t.ink2, size: 12 },
      margin: { l: 56, r: 16, t: 10, b: 44 }, hoverlabel: { bgcolor: t.surface, bordercolor: t.rule, font: { color: t.ink, family: t.font, size: 12 } },
      legend: { orientation: "h", x: 0, y: 1.12, font: { size: 11, color: t.ink2 } }, showlegend: false };
    var out = Object.assign(base, extra || {});
    if (out.showlegend && !(extra || {}).margin) out.margin = { l: 56, r: 16, t: 48, b: 44 };
    if (out.showlegend && !(extra || {}).legend) out.legend = { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", traceorder: "normal", font: { size: 11, color: t.ink2 } };
    out.xaxis = axis(t, (extra || {}).xaxis); out.yaxis = axis(t, (extra || {}).yaxis);
    ["xaxis2", "yaxis2", "xaxis3"].forEach(function (k) { if (extra && extra[k]) out[k] = axis(t, extra[k]); });
    return out;
  }
  // Replace one colour string everywhere in a trace or layout (numeric data arrays are skipped)
  function swapColor(o, a, b) {
    Object.keys(o).forEach(function (k) {
      var v = o[k];
      if (v === a) o[k] = b;
      else if (Array.isArray(v)) { if (v.length && typeof v[0] !== "number") swapColor(v, a, b); }
      else if (v && typeof v === "object") swapColor(v, a, b);
    });
  }
  function plot(id, traces, lay) {
    var el = $(id); if (!el || !window.Plotly) return;
    // Marker rings and hover labels take the panel colour of the band the chart sits in
    var s0 = css("--surface"), s1 = css("--surface", el);
    if (s1 && s0 && s1 !== s0) { swapColor(traces, s0, s1); swapColor(lay, s0, s1); }
    var msg = el.querySelector(":scope > .empty"); if (msg) msg.remove();
    Plotly.react(el, traces, lay, { displayModeBar: false, responsive: true });
  }
  function empty(id, text) {
    var el = $(id); if (!el) return;
    if (window.Plotly) Plotly.purge(el);
    el.innerHTML = '<p class="empty">' + esc(text) + "</p>";
  }
  function register(group, fn) { groups[group].push(fn); fn(); }
  function rerender(which) {
    var t0 = theme();
    (which || ["fixed", "season", "tracks", "detail"]).forEach(function (g) { groups[g].forEach(function (fn) { try { fn(t0); } catch (e) { console.error(e); } }); });
  }
  // Segmented control; calling it again replaces the options and the handler
  function seg(containerId, options, value, onChange) {
    var c = $(containerId); if (!c) return;
    c.innerHTML = options.map(function (o) {
      var v = Array.isArray(o) ? o[0] : o, label = Array.isArray(o) ? o[1] : o;
      return '<button type="button" data-v="' + esc(v) + '" aria-pressed="' + (String(v) === String(value)) + '">' + esc(label) + "</button>";
    }).join("");
    c.onclick = function (e) {
      var b = e.target.closest("button"); if (!b) return;
      c.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      onChange(b.getAttribute("data-v"));
    };
  }
  var loaded = {};
  function loadScript(src, ready, failed) {
    if (loaded[src] === true) return ready();
    if (loaded[src]) { loaded[src].push([ready, failed]); return; }
    loaded[src] = [[ready, failed]];
    var s = document.createElement("script");
    s.src = src;
    s.onload = function () { var q = loaded[src]; loaded[src] = true; q.forEach(function (c) { c[0](); }); };
    s.onerror = function () { var q = loaded[src]; delete loaded[src]; q.forEach(function (c) { if (c[1]) c[1](); }); };
    document.head.appendChild(s);
  }

  // Filter state
  var ALL_DRIVERS = Array.from(new Set([].concat.apply([], Object.keys(XI.drivers || {}).map(function (y) { return XI.drivers[y]; })))).sort();
  function drvColor(t, d) { var i = ALL_DRIVERS.indexOf(d); return [t.amr, t.alt][i] || t.ink2; }
  function drvSymbol(d) { return ["circle", "diamond", "square", "triangle-up"][Math.max(0, ALL_DRIVERS.indexOf(d))] || "circle"; }
  function fullName(d) { return (XI.names || {})[d] || d; }
  function lastName(d) { var n = fullName(d).split(" "); return n[n.length - 1]; }
  function seasons() { var o = {}; Object.keys(S.section_rates || {}).concat(Object.keys(XI.drivers || {})).forEach(function (y) { o[y] = 1; }); return Object.keys(o).sort(); }
  function seasonEvents(y) { return (XI.events || []).filter(function (e) { return String(e.season) === String(y); }); }
  function selEvents() { var k = state.tracks[state.season] || []; return seasonEvents(state.season).filter(function (e) { return k.indexOf(e.key) >= 0; }); }
  function selDrivers() { var d = state.drivers[state.season] || []; return ((XI.drivers || {})[state.season] || []).filter(function (x) { return d.indexOf(x) >= 0; }); }
  function entry(key) { return (XI.events || []).filter(function (e) { return e.key === key; })[0] || null; }
  function trk(e) { return e.location || short(e.event); }
  function wetNames(evs) { return evs.filter(function (e) { return e.wet; }).map(trk); }

  function initState() {
    var ys = seasons();
    state.season = ys[ys.length - 1];
    ys.forEach(function (y) {
      state.drivers[y] = ((XI.drivers || {})[y] || []).slice();
      state.tracks[y] = seasonEvents(y).filter(function (e) { return !e.wet; }).map(function (e) { return e.key; });
      state.focus[y] = defaultFocus(y);
    });
  }
  // Silverstone first (the team's home race), otherwise the latest selected track
  function defaultFocus(y) {
    var keys = state.tracks[y] || [], evs = seasonEvents(y).filter(function (e) { return keys.indexOf(e.key) >= 0; });
    var home = evs.filter(function (e) { return e.event === "British Grand Prix"; })[0];
    return home ? home.key : (evs.length ? evs[evs.length - 1].key : null);
  }

  // Multi-select dropdown: a button that opens a panel of checkboxes
  function MultiSelect(rootId, label, opts) {
    var root = $(rootId), self = this, pid = rootId + "-panel";
    this.root = root; this.opts = opts;
    root.innerHTML = '<button type="button" class="ms-btn" aria-haspopup="true" aria-expanded="false" aria-controls="' + pid + '">' +
      '<span class="ms-k">' + esc(label) + '</span><span class="ms-v"></span><span class="ms-caret" aria-hidden="true"></span></button>' +
      '<div class="ms-panel" id="' + pid + '" role="group" aria-label="' + esc(label) + '" hidden>' +
      (opts.bulk ? '<div class="ms-actions"><button type="button" data-act="all">All</button><button type="button" data-act="none">None</button><button type="button" data-act="dry">Dry only</button></div>' : "") +
      '<ul class="ms-list"></ul></div>';
    this.btn = root.querySelector(".ms-btn"); this.panel = root.querySelector(".ms-panel"); this.list = root.querySelector(".ms-list");
    this.btn.addEventListener("click", function () { if (self.panel.hidden) self.open(); else self.close(); });
    this.panel.addEventListener("change", function () { self.changed(); });
    this.panel.addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]"); if (!b) return;
      var act = b.getAttribute("data-act");
      self.list.querySelectorAll("input:not([disabled])").forEach(function (i) { i.checked = act === "all" || (act === "dry" && i.getAttribute("data-wet") !== "1"); });
      self.changed();
    });
    document.addEventListener("click", function (e) { if (!root.contains(e.target)) self.close(); });
    root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !self.panel.hidden) { self.close(); self.btn.focus(); } });
  }
  MultiSelect.prototype.set = function (options, selected) {
    this.options = options;
    this.list.innerHTML = options.map(function (o) {
      return '<li><label' + (o.title ? ' title="' + esc(o.title) + '"' : "") + '><input type="checkbox" value="' + esc(o.value) + '"' + (selected.indexOf(o.value) >= 0 && !o.disabled ? " checked" : "") + (o.disabled ? " disabled" : "") + (o.wet ? ' data-wet="1"' : "") + ">" +
        '<span class="ms-text">' + o.label + (o.sub ? ' <span class="ms-sub">' + o.sub + "</span>" : "") + "</span>" +
        (o.badge ? '<span class="ms-badge">' + esc(o.badge) + "</span>" : "") + "</label></li>";
    }).join("");
    this.summary();
  };
  MultiSelect.prototype.values = function () { return Array.from(this.list.querySelectorAll("input:checked")).map(function (i) { return i.value; }); };
  MultiSelect.prototype.summary = function () { this.root.querySelector(".ms-v").innerHTML = this.opts.summary(this.values(), this.options.filter(function (o) { return !o.disabled; }).length); };
  MultiSelect.prototype.changed = function () { this.summary(); this.opts.onChange(this.values()); };
  MultiSelect.prototype.open = function () {
    this.panel.hidden = false; this.btn.setAttribute("aria-expanded", "true");
    this.panel.style.left = "0px";
    var r = this.panel.getBoundingClientRect(), over = r.right - (document.documentElement.clientWidth - 12);
    if (over > 0) this.panel.style.left = -over + "px";
    var first = this.panel.querySelector("input, button"); if (first) first.focus();
  };
  MultiSelect.prototype.close = function () { if (!this.panel.hidden) { this.panel.hidden = true; this.btn.setAttribute("aria-expanded", "false"); } };

  var MS = {};
  function buildFilters() {
    seg("f-season", seasons(), state.season, function (y) { state.season = y; refreshFilters(); onFiltersChanged(true); });
    MS.drivers = new MultiSelect("f-drivers", "Drivers", {
      summary: function (v) { return !v.length ? "no driver" : esc(v.map(lastName).join(", ")); },
      onChange: function (v) { state.drivers[state.season] = v; onFiltersChanged(false); } });
    MS.tracks = new MultiSelect("f-tracks", "Tracks", { bulk: true,
      summary: function (v, n) { var u = '<span class="ms-unit"> tracks</span>'; return !v.length ? "none" + u : v.length === n ? '<span class="ms-all">all </span>' + n + u : v.length === 1 ? esc(trk(entry(v[0]))) : v.length + " of " + n + u; },
      onChange: function (v) { state.tracks[state.season] = v; onFiltersChanged(false); } });
    refreshFilters();
  }
  function refreshFilters() {
    var y = state.season, evs = seasonEvents(y);
    MS.drivers.set(((XI.drivers || {})[y] || []).map(function (d) {
      var n = evs.filter(function (e) { return e.drivers[d]; }).length, m = evs.filter(function (e) { return e.timing[d]; }).length;
      return { value: d, label: esc(fullName(d)), sub: d + " · telemetry at " + n + " of " + m + " tracks" };
    }), state.drivers[y]);
    MS.tracks.set(evs.map(function (e) {
      var tel = Object.keys(e.drivers).length;
      return { value: e.key, wet: e.wet, label: '<span class="rd">R' + e.round + "</span> " + esc(trk(e)), sub: esc(short(e.event)) + " GP",
        badge: e.wet ? "wet" : !tel ? "lap times only" : "" };
    }).concat((XI.failed || []).filter(function (x) { return String(x.season) === String(y); }).map(function (x) {
      return { value: x.key, disabled: true, title: x.error, label: '<span class="rd">R' + x.round + "</span> " + esc(short(x.event)), sub: "GP", badge: "no per-track data" };
    })), state.tracks[y]);
  }
  function onFiltersChanged(seasonChanged) {
    var y = state.season, keys = state.tracks[y];
    if (keys.indexOf(state.focus[y]) < 0) state.focus[y] = defaultFocus(y);
    status();
    if (seasonChanged) rerender(["season"]);
    rerender(["tracks"]);
    fillTrackSelect();
    setFocus(state.focus[y]);
  }
  function status() {
    var y = state.season, evs = selEvents(), n = seasonEvents(y).length, d = selDrivers();
    var tracks = !evs.length ? "no tracks" : evs.length === n ? "all " + n + " tracks" : evs.length + " of " + n + " tracks";
    $("f-status").textContent = y + " · " + (d.length ? d.map(lastName).join(", ") : "no driver") + " · " + tracks;
    var team = "team level, all " + (seasonEvents(y).some(function (e) { return e.wet; }) ? "dry " : "") + y + " tracks (season model)";
    var focus = current.entry ? trk(current.entry) + " " + y : "the track picked in Track detail";
    var scopes = {
      finding: "Each part says what it shows. The loss-rate chart follows the season picked at the top (now " + y + ", " + team + "); the findings are " + Y + ", with " + Y0 + " for comparison.",
      tracks: "Showing " + $("f-status").textContent,
      detail: "Showing " + (current.entry ? trk(current.entry) + " " + y : "the track picked below") + " · " + (d.length ? d.map(lastName).join(", ") : "no driver"),
      sim: "The simulator, calibration, surrogate, reduced-order and discrepancy charts follow the track picked in Track detail, now " + focus + ". Model tests and season charts use every event.",
      energy: "The speed chart follows the track picked in Track detail (now " + focus + "); the bars show " + Y + ", team level.",
      race: "Showing " + $("f-status").textContent,
      upgrades: "Showing " + y + ", " + team + ".",
      aero: "Showing " + y + ", " + team + ".",
      corners: "Corner-speed chart: " + y + ", " + team + ".",
      checks: "This section shows " + Y + " and the model tests over every event. The season picked at the top doesn't change it.",
    };
    document.querySelectorAll("[data-scope]").forEach(function (el) { el.textContent = scopes[el.getAttribute("data-scope")] || ""; });
  }

  // Text for the latest season, with the one before (no filters)
  var RATES = S.section_rates || {};
  var YS = Object.keys(RATES).sort(), Y = YS[YS.length - 1] || "", Y0 = YS.length > 1 ? YS[YS.length - 2] : "";
  // _LAST and _PREV hold the latest season and the one before it
  var PROF = (S.straight_profile || {});
  var SP_LAST = (PROF[Y] || {})[TARGET] || {};
  var SP_PREV = (PROF[Y0] || {})[TARGET] || {};
  var REL_LAST = ((S.target_relative || {})[Y]) || {};
  var CP_LAST = (S.changepoints || {})[Y] || {};
  var PT_LAST = ((S.powertrain || {})[Y] || {})[TARGET] || {};
  function upgradeComponent(season) { return (S.upgrade_components || []).filter(function (u) { return u.season === season; })[0]; }
  var UPG = upgradeComponent(+Y);
  // Method settings written by the pipeline, so the text quotes what the code used
  var MTH = S.method || {}, LVL = pct(MTH.interval_level);
  // Choices made here: which teams the text compares Aston Martin with
  var MIN_EVENTS = 5, OFF_PACE_PCT = 1;
  var DISC_K = 2;  // discrepancy band: GP mean ± DISC_K sd

  function ci(a, d, unit) { return a && a.length === 2 ? f(a[0], d) + " to " + f(a[1], d) + (unit || "") : "–"; }
  // "7%": how far off the fastest lap a lap may be and still count (the 107% rule)
  function repOff() { return f(MTH.representative_pct - 100, 0) + "%"; }
  function interval(a, d, unit) { return LVL + " interval " + ci(a, d, unit); }
  function sgnRange(a, d, unit) { return a && a.length === 2 ? sgn(a[0], d) + " to " + sgn(a[1], d) + (unit || "") : "–"; }
  // "loses 3.4 km/h" or "gains 0.6 km/h"
  function lossGain(v, d) { return v < 0 ? "loses " + f(-v, d == null ? 1 : d) : "gains " + f(v, d == null ? 1 : d); }

  function rate(season, team) { return (RATES[season] || {})[team] || {}; }
  function secRate(r, name) { var i = (r.sections || []).indexOf(name); return i < 0 ? {} : { v: r.rate_pct[i], lo: r.ci_lo[i], hi: r.ci_hi[i] }; }
  function others(season, offPace) {
    var o = RATES[season] || {};
    // offPace: teams at least OFF_PACE_PCT off pole over a lap; nearer the front the corner deficit
    // is too small for a stable straights-to-corners ratio
    return Object.keys(o).filter(function (k) { return k !== TARGET && o[k].n_events >= MIN_EVENTS && (!offPace || o[k].lap_rate_pct >= OFF_PACE_PCT); }).map(function (k) { return { team: k, r: o[k] }; });
  }

  // How another team's lap deficit compares with Aston Martin's (same rule as report/note.py pace_words)
  function paceWords(other, target) {
    if (!(isFinite(other) && isFinite(target)) || target === 0) return "–";
    return Math.abs(other / target - 1) <= 0.10 ? "about as slow" : other < target ? "faster" : "slower";
  }
  // A whole or half multiple in words, and the paired straight-line ratio worded only when its
  // interval excludes 1 (same rules as report/note.py multiple_words and straight_multiple)
  function multipleWords(h) {
    var whole = Math.floor(h);
    if (whole >= CARD.length) return h + " times";
    if (h % 1 === 0.5) return CARD[whole] + " and a half times";
    return { 1: "once", 2: "twice" }[whole] || CARD[whole] + " times";
  }
  function straightMultiple(vf) {
    var r = vf.ratio, lo = (vf.ratio_ci90 || [NaN])[0];
    if (r == null || !isFinite(r) || !(lo > 1)) return null;
    var h = Math.floor(2 * r + 0.5) / 2;
    return h >= 1.5 ? multipleWords(h) : null;
  }
  function verdict(e) { return e.lead_p_holm <= MTH.did_alpha ? "clear after correction" : (e.lead_p <= MTH.did_alpha ? "suggestive, not after correction" : "not distinguishable"); }
  function upgradeEffect(u) { return u ? ((S.upgrades || {}).effects || []).filter(function (x) { return x.season === u.season && x.event === u.event; })[0] : null; }

  function introText() {
    fill("hero_kicker", list(YS) + " qualifying | " + S.n_events + " Grands Prix");
    var last = XI.events.reduce(function (a, e) { return e.date && (!a || e.date > a.date) ? e : a; }, null);
    fill("data_through", last ? "Data through qualifying at the " + esc(last.event) + ", " + day(last.date) : "");
    fill("lvl", LVL);
    fill("corner_window", MTH.corner_window_m != null ? f(MTH.corner_window_m, 0) + " m" : "–");
    fill("profile_bins", SP_LAST.bins ? count(SP_LAST.bins.length) : "–");
    fill("halves_sub", "km/h, " + Y + ", " + LVL + " interval over events");
    fill("clip_sub", "s a lap, mean over " + Y + " events");
    fill("hero_fig_title", "Straight-line loss rate, " + Y);
    fill("hero_fig_sub", "% of the time the reference lap spends on the straights, every team with " + count(MIN_EVENTS) + " or more events, " + LVL + " interval");
  }

  // Three numbers under the hero
  function numbersBand() {
    var a = rate(Y, TARGET), st = secRate(a, "straights"), vf = (S.straight_vs_field || {})[Y] || {};
    var b = SP_LAST.bins || [], b0 = (b[0] || {}).gap_kmh, bN = (b[b.length - 1] || {}).gap_kmh, out = [];
    function item(label, num, unit, ctx) {
      return '<div class="num-item"><p class="label">' + label + '</p><p class="big">' + num + (unit ? '<span class="unit">' + unit + "</span>" : "") + '</p><p class="ctx">' + ctx + "</p></div>";
    }
    if (st.v != null) out.push(item("Straight-line loss rate, " + Y, f(st.v, 2), "%", "of the time the reference lap spends on the straights. " + interval([st.lo, st.hi], 2) + "."));
    if (vf.ratio != null) out.push(item("Against the next highest rate", f(vf.ratio, 2), "×", esc(vf.next_team) + "'s, on the same " + vf.n_events + " tracks. " + interval(vf.ratio_ci90, 2) + "."));
    if (bN != null) out.push(item("Speed gap at the braking point", f(Math.abs(bN), 1), "km/h", (bN < 0 ? "Slower" : "Faster") + " than the other teams' median at the end of the main straights. At the corner exit the gap is " +
      f(Math.abs(b0), 1) + " km/h" + (b0 < 0 && bN < b0 ? ", so it grows along the straight." : ".")));
    $("numbers").innerHTML = out.join("");
  }

  // Findings, each worded from its own numbers
  // Each returns [label, heading, body, number, number note, evidence anchor, method] or null without data
  function fStraights() {
    var a = rate(Y, TARGET), a0 = rate(Y0, TARGET), st = secRate(a, "straights"), r = a.straight_to_corner_ratio, rc = a.straight_to_corner_ci90 || [];
    if (r == null || st.v == null) return null;
    var off = others(Y, true).map(function (x) { return x.r.straight_to_corner_ratio; }).filter(isFinite);
    var off0 = others(Y0, true).map(function (x) { return x.r.straight_to_corner_ratio; }).filter(isFinite);
    var below = off.filter(function (v) { return v < 1; }).length, offTxt = "at least " + OFF_PACE_PCT + "% off the pace";
    var head = "The straights cost Aston Martin " + (rc[0] > 1 ? "more than" : rc[1] < 1 ? "less than" : "about as much as") + " the corners.";
    // Nearer the front the corner loss is close to zero, so the ratio swings; name the teams it swings for
    var front = others(Y, false).filter(function (x) { var s = secRate(x.r, "straights"); return x.r.lap_rate_pct < OFF_PACE_PCT && s.v > x.r.corner_rate_pct; });
    var body = (off.length ? (below === off.length ? "Every other team " + offTxt + " loses time faster in the corners than on the straights. "
        : below + " of the " + off.length + " other teams " + offTxt + " lose time faster in the corners than on the straights. ") : "") +
      (front.length ? "Teams nearer the front are left out because their corner loss is close to zero, so the ratio swings: " +
        list(front.map(function (x) { return esc(x.team) + " loses " + f(secRate(x.r, "straights").v, 2) + "% on the straights and " + f(x.r.corner_rate_pct, 2) + "% in the corners"; })) + ". " : "") +
      "In " + Y + " Aston Martin loses " + f(st.v, 2) + "% of the time the reference lap spends on the straights and " + f(a.corner_rate_pct, 2) + "% of its time in the corners." +
      (a0.straight_to_corner_ratio != null && off0.length ? " In " + Y0 + " its ratio of the two was " + f(a0.straight_to_corner_ratio, 2) + ", " +
        (a0.straight_to_corner_ratio < Math.min.apply(null, off0) ? "lower than any other team " + offTxt : a0.straight_to_corner_ratio > Math.max.apply(null, off0) ? "higher than any other team " + offTxt : "in line with the other teams " + offTxt) + "." : "");
    var ctx = "Straights-to-corners ratio, " + interval(rc, 2) + "." + (off.length ? " Other teams " + offTxt + ": " + f(Math.min.apply(null, off), 2) + " to " + f(Math.max.apply(null, off), 2) + "." : "");
    return ["Straights | " + Y, head, body, f(r, 2), ctx, "#ev-rates",
      "Laps lined up on a shared distance grid and split into corners and straights; " + LVL + " intervals from a bootstrap over " + a.n_events + " events, widened for small samples."];
  }
  function fField() {
    var vf = (S.straight_vs_field || {})[Y] || {}, a = rate(Y, TARGET), nx = rate(Y, vf.next_team);
    if (vf.ratio == null) return null;
    var m = straightMultiple(vf), lo = (vf.ratio_ci90 || [])[0], nt = esc(vf.next_team);
    var head = m ? "On the straights it loses time about " + m + " as fast as any other team." :
      lo > 1 ? "On the straights it loses time faster than any other team." :
      vf.ratio > 1 ? "Its straight-line loss rate is the highest, though not by a clear margin." : "Another team loses time faster on the straights.";
    // Whole-lap rates on the same tracks when the results carry them, else over each team's own events
    var same = vf.next_lap_rate_pct != null, nl = same ? vf.next_lap_rate_pct : nx.lap_rate_pct, al = same ? vf.target_lap_rate_pct : a.lap_rate_pct;
    var pw = paceWords(nl, al), lap = " (" + f(nl, 2) + "% of the reference lap, against " + f(al, 2) + "%" + (same ? "" : ", over each team's own events") + ")";
    var body = "On the " + vf.n_events + " tracks where Aston Martin set a lap that passed the data checks, the next highest straight-line loss rate is " + nt + "'s, at " + f(vf.next_rate_pct, 2) + "%. " +
      (pw === "about as slow" ? nt + " is about as slow over a whole lap" + (same ? " on those tracks" : "") + lap + ". It loses its time in other places." :
        pw === "slower" ? nt + " is slower over a whole lap" + (same ? " on those tracks" : "") + lap + ", but loses less of it on the straights." :
        pw === "faster" ? nt + " is faster over a whole lap" + (same ? " on those tracks" : "") + lap + "." : "");
    var ctx = interval(vf.ratio_ci90, 2) + "." + (vf.p_ratio_above_2 != null ? " In " + pct(vf.p_ratio_above_2) + " of bootstrap draws the ratio is above 2." : "");
    return ["Against the field | " + Y, head, body, f(vf.ratio, 2) + "<small>×</small>", ctx, "#ev-rates",
      "Paired bootstrap over the " + vf.n_events + " events, with the worst rival picked inside each draw."];
  }
  function fAlong() {
    var b = SP_LAST.bins || [];
    if (!b.length) return null;
    var b0 = b[0], bN = b[b.length - 1], c1 = SP_LAST.first_half_ci90 || [], c2 = SP_LAST.second_half_ci90 || [], g = SP_LAST.growth_ci90 || [];
    var starts = b0.ci_hi < 0, grows1 = c1[1] < 0, grows2 = c2[1] < 0;
    var head = starts && grows1 && grows2 ? "The loss starts at the corner exit and keeps growing." :
      starts && grows2 ? "It leaves the corners slower and loses more late on the straights." :
      starts ? "It leaves the corners slower, and the gap holds along the straight." :
      grows2 ? "The gap opens late on the straights." : "The speed gap doesn't grow clearly along the straights.";
    function gap(v) { return f(Math.abs(v), 1) + " km/h " + (v < 0 ? "down on" : "up on"); }
    var body = "On the main straights the car is " + gap(b0.gap_kmh) + " the other teams as it leaves the corner and " + gap(bN.gap_kmh) + " them at the braking point. " +
      "The gap grows in the second half on " + SP_LAST.n_straights_losing_late + " of " + SP_LAST.n_straights + " straights, at " + SP_LAST.n_events + " events.";
    var lost = SP_LAST.growth_kmh < 0;
    var ctx = (lost ? "Lost" : "Gained") + " between the corner exit and the braking point. " + LVL + " interval " + (lost ? f(-g[1], 1) + " to " + f(-g[0], 1) : ci(g, 1)) + ".";
    return ["Along the straight | " + Y, head, body, f(Math.abs(SP_LAST.growth_kmh), 1) + "&nbsp;<small>km/h</small>", ctx, "#ev-straight",
      "Speed in " + count(b.length) + " equal pieces of each main straight against the other teams' median, with a leave-one-event-out check."];
  }
  // With very few events the bootstrap interval of the power and drag fit reaches the extremes,
  // so it is just the range of the per-event estimates; say so rather than call it a 90% interval
  function spansRange(p) {
    var pe = (p.per_event || []).map(function (r) { return r.d_power_kw; }), dp = p.d_power_ci90 || [];
    return pe.length > 0 && Math.abs(dp[0] - Math.min.apply(null, pe)) < 0.5 && Math.abs(dp[1] - Math.max.apply(null, pe)) < 0.5;
  }
  function fPower() {
    var p = PT_LAST, dp = p.d_power_ci90 || [], dc = p.d_cda_ci90 || [];
    var method = "Power and drag fitted together on full-throttle acceleration, with gravity taken out using GPS altitude; bootstrap over events.";
    if (!p.n_events) return ["Power or drag | " + Y, "Public data can't separate power from drag.", "In " + Y + " too few straights were long and clean enough to fit the two together.", "–", "", "#ev-power", method];
    var spanP = dp[0] < 0 && dp[1] > 0, spanD = dc[0] < 0 && dc[1] > 0;
    var head = spanP && spanD ? "Public data can't say whether it's power or drag." :
      !spanP && spanD ? "The fit points to " + (dp[1] < 0 ? "less" : "more") + " power, while drag isn't pinned down." :
      spanP ? "The fit points to " + (dc[0] > 0 ? "more" : "less") + " drag, while power isn't pinned down." :
      "The fit points to " + (dp[1] < 0 ? "less" : "more") + " power and " + (dc[0] > 0 ? "more" : "less") + " drag.";
    var tied = Math.abs(p.correlation) >= 0.9;
    var body = (tied ? "Over one straight, a car with more power and more drag looks almost the same as one with less of both: the two estimates move together (correlation " + f(p.correlation, 3) + ")."
        : "The power and drag estimates are correlated (" + f(p.correlation, 2) + ").") +
      (spanP && spanD ? " Fitted together, each could still go either way, so I report them together and don't pick one." : "");
    var ctx = "of power, and " + sgnRange(dc, 2, " m²") + " of drag area. " + (spansRange(p)
      ? "The range of the estimates from the " + count(p.n_events) + " events where a fit is possible: with so few, that's all a " + LVL + " interval can be."
      : LVL + " intervals from the " + p.n_events + " events where a fit is possible.");
    return ["Power or drag | " + Y, head, body, sgnRange(dp, 0) + "&nbsp;<small>kW</small>", ctx, "#ev-power", method];
  }
  function fOrder() {
    var V = (S.variance_split || {})[Y], V0 = (S.variance_split || {})[Y0];
    if (!V) return null;
    var c = V.car_share_ci90 || [];
    var head = c[0] > 0.5 ? "In " + Y + " the qualifying order is mostly set by the teams." : c[1] < 0.5 ? "In " + Y + " team-mates differ more than teams do." : "In " + Y + " teams and team-mates matter about equally.";
    var body = "Differences between teams (the car and the driver line-up together) explain " + pct(V.car_share) + " of the spread in qualifying gaps in " + Y +
      (V0 ? ", " + (V.car_share > V0.car_share ? "up" : "down") + " from " + pct(V0.car_share) + " in " + Y0 : "") + ". The rest comes from differences between team-mates: driver, lap execution and session timing.";
    return ["Who sets the order | " + Y, head, body, pct(V.car_share), "Between teams in " + Y + ". " + LVL + " interval " + pct(c[0]) + " to " + pct(c[1]) + ".", "#ev-order",
      "One-way random-effects split of the qualifying gaps at each event, averaged over events; bootstrap over events."];
  }
  function fUpgrade() {
    var u = UPG, e = upgradeEffect(u), cp = CP_LAST;
    if (!u || !e || !u.grip_high_rel) return null;
    var gh = u.grip_high_rel, v = verdict(e), where = "the " + esc(u.event);
    var head = v === "clear after correction" ? "The upgrade at " + where + " made a measurable difference." :
      e.effect_pct < 0 && v === "suggestive, not after correction" ? "The upgrade at " + where + " may have helped. I can't prove it." :
      "I can't see an effect from the upgrade at " + where + ".";
    var body = "Fast-corner grip went from " + f(gh.before.mean * 100, 1) + "% to " + f(gh.after.mean * 100, 1) + "% of the field median, but only " + gh.after.n + " events with usable data came after it. " +
      (cp.map_event === u.event ? "A changepoint model that isn't told the upgrade dates picks the same race as the likeliest place for a single change (" + f(cp.map_probability, 2) + ")"
        : "A changepoint model that isn't told the upgrade dates puts the likeliest single change at the " + esc(cp.map_event) + " (" + f(cp.map_probability, 2) + ")") +
      (cp.p_no_change > cp.map_probability ? ", but no change at all scores higher (" + f(cp.p_no_change, 2) + ")." : ", against " + f(cp.p_no_change, 2) + " for no change at all.");
    var nPl = e.lead_test === "time" ? e.n_time_placebos : e.n_team_placebos, floor = 1 / (1 + nPl), nTested = ((S.upgrades || {}).effects || []).length;
    var ctx = "Difference-in-differences: " + sgn(e.effect_pct, 2) + "% of lap time. With " + nPl + (e.lead_test === "time" ? " placebo dates" : " rival teams as placebos") + ", " +
      (e.lead_p <= floor + 1e-9 ? f(floor, 2) + " is the lowest p this test can give." : "the lowest p this test can give is " + f(floor, 2) + ".") +
      " Adjusted for the " + nTested + " upgrades tested (Holm): " + f(e.lead_p_holm, 2) + ".";
    return ["Upgrades | " + Y, head, body, "p = " + f(e.lead_p, 2), ctx, "#upgrades",
      "A Bayesian changepoint model that isn't told the dates, and difference-in-differences against placebo dates and teams, Holm-adjusted."];
  }
  function fRace() {
    var rp = S.race_pace || [], cur = rp.filter(function (r) { return String(r.season) === Y; }), prev = rp.filter(function (r) { return String(r.season) === Y0; });
    var me = cur.filter(function (r) { return r.team === TARGET; })[0], me0 = prev.filter(function (r) { return r.team === TARGET; })[0];
    if (!me) return null;
    var order = cur.slice().sort(function (a, b) { return a.mean - b.mean; }), rank = order.indexOf(me) + 1, n = order.length;
    var laps = Object.keys(RATES[Y] || {}).map(function (k) { return RATES[Y][k].lap_rate_pct; });
    var qualiLast = rate(Y, TARGET).lap_rate_pct >= Math.max.apply(null, laps);
    var head = rank === n ? (qualiLast ? "On average it's the slowest car in races as well as in qualifying." : "On average it's the slowest car in races.") : "On average it ranks " + ord(rank) + " of " + n + " teams in races.";
    var next = rank > 1 ? order[rank - 2] : null;
    // Race by race: which team was slowest at each race with a fit
    var byRace = byKey((S.race_pace_by_event || []).filter(function (r) { return String(r.season) === Y; }), "round"), tally = {}, nRaces = 0;
    Object.keys(byRace).forEach(function (k) {
      var w = byRace[k].slice().sort(function (p, q) { return q.gap_s - p.gap_s; })[0];
      tally[w.team] = (tally[w.team] || 0) + 1; nRaces++;
    });
    var slowTeams = Object.keys(tally).sort(function (p, q) { return tally[q] - tally[p] || (q === TARGET) - (p === TARGET); });
    var body = "Corrected for fuel and tyres, Aston Martin averaged " + f(me.mean, 2) + " s a lap off the best team over " + me.count + " races in " + Y +
      (me0 ? ", against " + f(me0.mean, 2) + " s over " + me0.count + " races in " + Y0 : "") + "." +
      (rank === n && next ? " The next slowest team, " + esc(next.team) + ", averaged " + f(next.mean, 2) + " s over " + next.count + " races." : "") +
      (nRaces ? " Race by race, the slowest team was " + list(slowTeams.map(function (k) { return esc(k) + " in " + tally[k]; })) + " of the " + nRaces + " races." : "");
    return ["Race pace | " + Y, head, body, f(me.mean, 2) + "&nbsp;<small>s</small>", "A lap off the best team in " + Y + ", mean over races.", "#race",
      "Fixed-effects model of green-flag race laps (driver, tyre compound and wear, fuel), with jackknife intervals over stints."];
  }

  function findingsList() {
    var rows = [fStraights, fField, fAlong, fPower, fOrder, fUpgrade, fRace].map(function (fn, i) {
      try { var r = fn(); return r ? { n: i + 1, r: r } : null; } catch (err) { console.error(err); return null; }
    }).filter(Boolean);
    $("findings-list").innerHTML = rows.map(function (x) {
      var r = x.r;
      return '<li class="finding"><p class="f-n">' + (x.n < 10 ? "0" : "") + x.n + '</p><div class="f-main"><p class="label">' + r[0] + "</p><h3>" + r[1] + '</h3><p class="body">' + r[2] + "</p>" +
        (r[6] ? '<p class="method"><span class="k">Method</span> ' + r[6] + "</p>" : "") +
        (r[5] ? '<a class="go" href="' + r[5] + '">See the evidence' + ARROW + "</a>" : "") + '</div><div class="f-num"><p class="v' + (r[3].replace(/<[^>]+>/g, "").length > 9 ? " long" : "") + '">' + r[3] + '</p><p class="ctx">' + r[4] + "</p></div></li>";
    }).join("");
    fill("findings_intro", cap1(count(rows.length)) + " results, in the order I'd explain them to an engineer, each with how sure I am and the method behind it.");
  }

  // Text beside the evidence charts that does not follow the filters
  function evidenceText() {
    fill("hero_note", "A loss rate is the time lost to the pole lap in a section divided by the time the pole lap spends there, summed over events. A car that is slower by the same factor everywhere has the same rate everywhere, so rates show where a car is weak. In raw seconds the slow corners usually come out worst, because cars spend the most time there. Comparisons use the same piece of track, so geometry and gradient cancel. Laps can be set at different times of the session, though, and track evolution mostly adds grip, which inflates corner rates more than straight-line ones. \"Pole lap\" means the fastest lap of qualifying" + (function () {
      var np = (XI.events || []).filter(function (e) { return !e.wet && e.fastest_lap && e.fastest_lap.segment && e.fastest_lap.segment !== "Q3"; });
      return np.length ? " (" + list(np.map(function (e) { return "at the " + e.season + " " + esc(e.event) + " that was a " + esc(e.fastest_lap.segment) + " lap"; })) + ", faster than the Q3 pole)" : "";
    })() + ". " + ((S.reference_not_fastest || []).length ? "Where the fastest lap's data failed a check, losses are measured against the fastest lap that passed (" +
      list(S.reference_not_fastest.map(function (x) { return "at the " + x.season + " " + esc(x.event) + ", " + esc(x.reference) + "'s, " + f(x.gap_s, 2) + " s slower than " + esc(x.fastest) + "'s"; })) + "). " : "") +
      ((S.wet_events_excluded || []).length ? "Wet qualifying (" + list(S.wet_events_excluded.map(esc)) + ") is left out. " : "") +
      "Intervals are " + LVL + " bootstrap intervals over events, widened for small samples: with this few events, plain percentile intervals cover less often than they claim, which the tests check by simulation.");

    var b = SP_LAST.bins || [], b0 = (b[0] || {}).gap_kmh, bN = (b[b.length - 1] || {}).gap_kmh, c1 = SP_LAST.first_half_ci90 || [NaN, NaN], loo = SP_LAST.second_half_loo_range || [];
    var holds = c1[0] <= 0 && c1[1] >= 0;
    fill("finding_text", "Each main straight is split into " + count(b.length) + " equal pieces, and speeds are compared piece by piece with the median of the other teams. The straights are the stretches where the pole lap is flat out from corner exit to braking point. In " + Y + " Aston Martin starts them " +
      f(Math.abs(b0), 1) + " km/h " + (b0 < 0 ? "down" : "up") + ", " +
      (holds ? "holds that through the first half (" + sgn(SP_LAST.first_half_kmh, 1) + " km/h, " + interval(c1, 1) + ") and " + lossGain(SP_LAST.second_half_kmh) + " km/h in the second half"
        : lossGain(SP_LAST.first_half_kmh) + " km/h over the first half (" + interval(c1, 1) + ") and " + lossGain(SP_LAST.second_half_kmh) + " km/h more in the second half") +
      " (" + interval(SP_LAST.second_half_ci90, 1) + "). The late loss shows on " + SP_LAST.n_straights_losing_late + " of " + SP_LAST.n_straights + " main straights that start and end away from the timing line, at " + SP_LAST.n_events +
      " events. Leaving out any one event keeps the second-half average between " + f(loo[1], 1) + " and " + f(loo[0], 1) + " km/h. " +
      (b0 < 0 ? (c1[1] < 0 ? "Losing ground from the first metres means weaker acceleration than the field, not only a lower top speed. " : "Holding the gap while starting slower already means weaker acceleration than the field. ") : "") +
      "The gap reaches " + f(Math.abs(bN), 1) + " km/h at the braking point. Extra drag, deployment ending earlier and harvesting at full throttle can all open a gap along a straight, and public timing data can't tell them apart. " +
      (function () {
        var o = PROF[Y] || {}, rows = Object.keys(o).filter(function (k) { return k !== TARGET && o[k].second_half_kmh != null; });
        if (!rows.length) return "";
        var late = rows.slice().sort(function (p, q) { return o[p].second_half_kmh - o[q].second_half_kmh; })[0], lv = o[late].second_half_kmh;
        var starts = rows.map(function (k) { return Math.abs(((o[k].bins || [])[0] || {}).gap_kmh || 0); }), top = Math.max.apply(null, starts), topTeam = rows[starts.indexOf(top)];
        return (lv < 0 ? "A late loss on its own isn't unusual: " + esc(late) + " " + lossGain(lv) + " km/h in the second half too, " + (lv > SP_LAST.second_half_kmh ? "the next largest after Aston Martin. " : "more than Aston Martin. ") : "") +
          (b0 < 0 && Math.abs(b0) > top ? "What sets Aston Martin apart is the size of both parts: the next largest gap at the start of the straights is " + esc(topTeam) + "'s, " + f(top, 1) + " km/h. " : "");
      })() + "In " + Y0 + " the same second-half change was " + sgn(SP_PREV.second_half_kmh, 1) + " km/h (" + interval(SP_PREV.second_half_ci90, 1) + ").");

    var ptPrev = ((S.powertrain || {})[Y0] || {})[TARGET] || {};
    fill("joint_text", "Fitting power and drag directly from acceleration on the first part of each straight, with gravity removed using the GPS altitude, doesn't separate them. Over a single straight the two terms move together, so a fit needs at least " +
      f(MTH.powertrain_min_straight_m, 0) + " m of clean straight and a " + f(MTH.powertrain_min_speed_span_kmh, 0) + " km/h speed range. " +
      (PT_LAST.n_events ? "Aston Martin passes that at " + PT_LAST.n_events + " events in " + Y + ", and " + (spansRange(PT_LAST) ? "the estimates from those events" : "the " + LVL + " intervals") + " still span " + sgnRange(PT_LAST.d_power_ci90, 0, " kW") + " of power and " + sgnRange(PT_LAST.d_cda_ci90, 2, " m²") + " of drag area."
        : "In " + Y + " Aston Martin's laps pass that at too few events for a fit. In " + Y0 + " (" + (ptPrev.n_events || 0) + " events) the fitted power and drag move together (correlation " + f(ptPrev.correlation, 2) + ")."));

    fill("decomp_text", "In " + Y + ", against the other teams' median, the main straights alone cost " + f(SP_LAST.time_total_s, 2) + " s a lap (" + interval(SP_LAST.time_total_ci90, 2) + "). Of that, " + f(SP_LAST.time_build_s, 2) +
      " s (" + interval(SP_LAST.time_build_ci90, 2) + ") is speed lost along the straight rather than carried from the corner.");
  }

  function declaredParts(event, season) {
    var u = ((S.upgrades || {}).declared || []).filter(function (d) { return d.season === season && d.grand_prix === event; })[0];
    var n = u && (u.components.match(/(\d+) items/) || [])[1];
    return n ? n + "-part" : null;
  }

  function upgradeText() {
    var y = state.season, cp = (S.changepoints || {})[y] || {}, effs = ((S.upgrades || {}).effects || []).filter(function (e) { return String(e.season) === y; });
    var cpS = cp.prior_sensitivity || [], p0s = cpS.map(function (r) { return r.p_no_change; });
    var pm = cpS.filter(function (r) { return r.map_event === cp.map_event; }).map(function (r) { return r.map_probability; });
    function span(a) { return f(Math.min.apply(null, a), 2) + " to " + f(Math.max.apply(null, a), 2); }
    if (y === Y && UPG) {
      var gh = UPG.grip_high_rel, uh = upgradeEffect(UPG) || {}, v = verdict(uh), steps = cp.two_change_steps_pct || [];
      fill("upgrade_text", "Aston Martin declared a " + (declaredParts(UPG.event, +Y) || "major") + " upgrade at the " + esc(UPG.event) +
        ". A changepoint model that isn't told the upgrade dates rates the " + esc(cp.map_event || "–") + " the likeliest place for a single shift in its qualifying pace (posterior " + f(cp.map_probability, 2) +
        ", against " + f(cp.p_no_change, 2) + " for no change). Across the prior settings tried, the chance of no change runs from " + span(p0s) + " and the " + esc(cp.map_event || "–") + " from " + span(pm) + ". Given a change, the step is " +
        sgn(cp.effect_pct, 2) + "% of lap time (" + interval(cp.effect_ci90_pct, 2) + "); allowing for no change it averages " + sgn(cp.effect_avg_pct, 2) + "% (" + interval(cp.effect_avg_ci90_pct, 2) + "). " +
        (cp.two_change_events && cp.bf_two_vs_one > 3 ? "But a model with two changes (" + sgn(steps[0], 1) + "% at the " + esc(cp.two_change_events[0]) + ", " + sgn(steps[1], 1) + "% at the " + esc(cp.two_change_events[1]) +
          ") fits the season better than one step, with a Bayes factor of " + f(cp.bf_two_vs_one, 1) + (steps[0] > 0 && steps[1] < 0 ? ", so much of the drop undoes a rise in the gap earlier in the season. " : ". ") : "") +
        "Fast-corner grip relative to the other teams went from " + f(gh.before.mean * 100, 1) + "% to " + f(gh.after.mean * 100, 1) + "% (" + gh.before.n + " events before, only " + gh.after.n +
        " after with usable Aston Martin telemetry). The difference-in-differences test can't settle it either. Aston Martin's own " + Y + " estimates at other dates are spread about " + f(uh.noise_ratio, 0) +
        " times as widely as the rivals' estimates at this date, so beating every rival's placebo means little, and against its own " + (uh.n_time_placebos || "–") + " other dates no test can go below p = " + f(1 / (1 + (uh.n_time_placebos || 0)), 2) +
        " (the " + esc(UPG.event) + " gets " + f(uh.time_placebo_p, 2) + "). " +
        (v === "clear after correction" ? "The effect holds after correcting for the number of upgrades tested." : v === "suggestive, not after correction" ? "Suggestive, not established." : "No effect stands out from the noise."));
      return;
    }
    // Any other season: the declared upgrades, the changepoint result and each test's verdict
    var decl = upgradeEvents(+y).map(function (u) { return (u.major_performance_upgrade === "major" ? "a major upgrade" : "a partial upgrade") + " at the " + esc(u.grand_prix); });
    var clear = cp.p_no_change >= 0.5;
    fill("upgrade_text", "In " + y + " Aston Martin declared " + (decl.length ? list(decl) : "no major upgrade") + ". " +
      (clear ? "A changepoint model that isn't told the upgrade dates finds no clear shift in its qualifying pace: the chance of no change all season is " + f(cp.p_no_change, 2) + " (" + span(p0s) +
        " across the prior settings tried), and the likeliest single shift, at the " + esc(cp.map_event || "–") + ", has posterior " + f(cp.map_probability, 2) + ". "
        : "A changepoint model that isn't told the upgrade dates rates the " + esc(cp.map_event || "–") + " the likeliest place for a single shift (posterior " + f(cp.map_probability, 2) + ", against " + f(cp.p_no_change, 2) + " for no change). ") +
      (effs.length ? "Difference-in-differences, each upgrade against " + (effs[0].lead_test === "time" ? "Aston Martin at its other dates" : "the rivals at the same date") + ": " + list(effs.map(function (e) {
        return esc(short(e.event)) + " " + sgn(e.effect_pct, 2) + "% of lap time (" + verdict(e) + ", Holm-adjusted p = " + f(e.lead_p_holm, 2) + ")";
      })) + ". " + (effs.some(function (e) { return verdict(e) === "clear after correction"; }) ? "" : "None stands out from the noise after correcting for testing several upgrades.") : ""));
  }

  // Evidence charts for the latest season and the one before (no filters), except renderRates (season filter)
  // The hero chart sits on the dark band and takes that band's colours
  function renderHero() {
    var el = $("ch-hero"); if (!el) return;
    var t = theme(el), o = RATES[Y] || {};
    var rows = Object.keys(o).filter(function (k) { return o[k].n_events >= MIN_EVENTS; }).map(function (k) { var r = secRate(o[k], "straights"); return { k: k, v: r.v, lo: r.lo, hi: r.hi }; })
      .filter(function (x) { return x.v != null; }).sort(function (a, b) { return a.v - b.v; });
    function tr(sel, color, size) {
      var r = rows.filter(sel);
      return { y: r.map(function (x) { return x.k; }), x: r.map(function (x) { return x.v; }), type: "scatter", mode: "markers",
        marker: { size: size, color: color, line: { color: t.surface, width: 2 } },
        error_x: { type: "data", symmetric: false, array: r.map(function (x) { return x.hi - x.v; }), arrayminus: r.map(function (x) { return x.v - x.lo; }), color: color, thickness: 1.5, width: 0 },
        customdata: r.map(function (x) { return [x.lo, x.hi]; }),
        hovertemplate: "%{y}: %{x:.2f}%<br>" + LVL + " interval %{customdata[0]:.2f} to %{customdata[1]:.2f}<extra></extra>" };
    }
    var me = rows.filter(function (x) { return x.k === TARGET; })[0];
    plot("ch-hero", [tr(function (x) { return x.k !== TARGET; }, t.field, 9), tr(function (x) { return x.k === TARGET; }, t.amr, 14)],
      layout(t, { margin: { l: 130, r: 24, t: 8, b: 48 }, xaxis: { title: { text: "straight-line loss rate" }, ticksuffix: "%" },
        yaxis: { type: "category", categoryorder: "array", categoryarray: rows.map(function (x) { return x.k; }) },
        shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }],
        annotations: me ? [{ x: me.hi, y: me.k, xanchor: "left", xshift: 10, text: f(me.v, 2) + "%", showarrow: false, font: { size: 14, color: t.ink } }] : [] }));
  }

  function renderProfile(t) {
    t = t || theme();
    var traces = [], pl = PROF[Y] || {};
    Object.keys(pl).filter(function (k) { return k !== TARGET; }).forEach(function (k, i) {
      var b = pl[k].bins;
      traces.push({ x: b.map(function (r) { return r.fraction * 100; }), y: b.map(function (r) { return r.gap_kmh; }), type: "scatter", mode: "lines",
        line: { color: t.field, width: 1 }, opacity: 0.6, name: k, showlegend: i === 0, legendgroup: "field", hovertemplate: k + ": %{y:+.1f} km/h<extra></extra>" });
    });
    traces[0] && (traces[0].name = "other teams, " + Y);
    [[SP_PREV, t.alt, "Aston Martin " + Y0, "dash"], [SP_LAST, t.amr, "Aston Martin " + Y, "solid"]].forEach(function (r) {
      var b = r[0].bins || [];
      var x = b.map(function (q) { return q.fraction * 100; });
      traces.push({ x: x.concat(x.slice().reverse()), y: b.map(function (q) { return q.ci_hi; }).concat(b.map(function (q) { return q.ci_lo; }).reverse()),
        type: "scatter", mode: "lines", fill: "toself", fillcolor: hexA(r[1], 0.14), line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      traces.push({ x: x, y: b.map(function (q) { return q.gap_kmh; }), name: r[2], type: "scatter", mode: "lines+markers",
        line: { color: r[1], width: 2.2, dash: r[3] }, marker: { size: 7, color: r[1], line: { color: t.surface, width: 1.5 } },
        hovertemplate: r[2] + "<br>%{x:.0f}% along: %{y:+.1f} km/h<extra></extra>" });
    });
    plot("ch-profile", traces, layout(t, { showlegend: true, xaxis: { title: { text: "position along the straight, % (corner exit → braking point)" }, range: [0, 100] },
      yaxis: { title: { text: "speed against the other teams, km/h" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } },
        { type: "rect", x0: 50, x1: 100, yref: "paper", y0: 0, y1: 1, fillcolor: t.ink2, opacity: 0.04, line: { width: 0 } }],
      annotations: [{ x: 75, yref: "paper", y: 0.02, yanchor: "bottom", text: "second half of the straight", showarrow: false, font: { size: 10, color: t.muted } }] }));
  }

  function renderHalves(t) {
    t = t || theme();
    var pl = PROF[Y] || {};
    var teams = Object.keys(pl).sort(function (a, b) { return pl[a].second_half_kmh - pl[b].second_half_kmh; });
    function tr(key, name, color, sym) {
      return { y: teams, x: teams.map(function (k) { return pl[k][key]; }), name: name, type: "scatter", mode: "markers",
        marker: { size: 9, symbol: sym, color: teams.map(function (k) { return k === TARGET ? color : t.field; }),
          line: { color: teams.map(function (k) { return k === TARGET ? color : t.field; }), width: 1.5 } },
        error_x: { type: "data", symmetric: false, array: teams.map(function (k) { return pl[k][key + "_ci90"] ? pl[k][key + "_ci90"][1] - pl[k][key] : 0; }),
          arrayminus: teams.map(function (k) { return pl[k][key + "_ci90"] ? pl[k][key] - pl[k][key + "_ci90"][0] : 0; }), color: t.rule, thickness: 1, width: 0 },
        hovertemplate: "%{y}, " + name + ": %{x:+.1f} km/h<extra></extra>" };
    }
    plot("ch-halves", [tr("first_half_kmh", "first half", t.alt, "circle-open"), tr("second_half_kmh", "second half", t.amr, "circle")],
      layout(t, { showlegend: true, margin: { l: 110, r: 16, t: 40, b: 44 }, xaxis: { title: { text: "change in the speed gap within that half, km/h" } },
        shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function rateGuides(t, lim) {
    var guide = [0.25, 0.5, 1].map(function (r) {
      return { x: [0, lim], y: [0, lim * r], type: "scatter", mode: "lines", line: { color: t.rule, width: 1, dash: r === 1 ? "solid" : "dot" }, hoverinfo: "skip", showlegend: false };
    });
    var notes = [0.25, 0.5, 1].map(function (r) { return { x: lim, y: lim * r, xanchor: "right", yanchor: "bottom", text: r === 1 ? "straights = corners" : "× " + r, showarrow: false, font: { size: 10, color: t.muted } }; });
    return { traces: guide, notes: notes };
  }

  function renderRates(t) {
    t = t || theme();
    var season = state.season, o = RATES[season] || {};
    fill("rates_sub", "% of the pole lap's time in each, summed over events, " + season + ", bars = " + LVL + " interval");
    var teams = Object.keys(o).filter(function (k) { return o[k].n_events >= MIN_EVENTS; });
    var xs = teams.map(function (k) { return o[k].corner_rate_pct; }), ys = teams.map(function (k) { return secRate(o[k], "straights").v; });
    var lim = Math.max.apply(null, xs.concat(ys).filter(isFinite)) * 1.15;
    var g = rateGuides(t, lim);
    plot("ch-rates", g.traces.concat([{
      x: xs, y: ys, text: teams.map(function (k) { return k === TARGET || o[k].lap_rate_pct > 2.5 ? k : ""; }), hovertext: teams,
      type: "scatter", mode: "markers+text", textposition: "top left", textfont: { size: 11, color: t.ink2 },
      marker: { size: teams.map(function (k) { return k === TARGET ? 13 : 9; }), color: teams.map(function (k) { return k === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 2 } },
      error_y: { type: "data", symmetric: false, array: teams.map(function (k) { var r = secRate(o[k], "straights"); return r.hi - r.v; }), arrayminus: teams.map(function (k) { var r = secRate(o[k], "straights"); return r.v - r.lo; }), color: t.rule, thickness: 1, width: 0 },
      customdata: teams.map(function (k) { return [o[k].lap_rate_pct, o[k].straight_to_corner_ratio, o[k].n_events]; }),
      hovertemplate: "%{hovertext}<br>corners %{x:.2f}% · straights %{y:.2f}%<br>lap %{customdata[0]:.2f}% · ratio %{customdata[1]:.2f} · %{customdata[2]} events<extra></extra>",
    }]), layout(t, { margin: { l: 56, r: 16, t: 26, b: 44 }, xaxis: { title: { text: "loss rate in corners, % of pole's time there" }, range: [0, lim] },
      yaxis: { title: { text: "loss rate on straights, %" }, range: [-0.6, lim] }, annotations: g.notes }));
  }

  function renderJoint(t) {
    t = t || theme();
    var series = [[Y, t.amr, "Aston Martin " + Y], [Y0, t.alt, "Aston Martin " + Y0]].filter(function (r) { return ((((S.powertrain || {})[r[0]] || {})[TARGET]) || {}).draws; });
    plot("ch-joint", series.map(function (r) {
      var d = ((((S.powertrain || {})[r[0]] || {})[TARGET]) || {}).draws || [];
      return { x: d.map(function (q) { return q[0]; }), y: d.map(function (q) { return q[1]; }), name: r[2], type: "scatter", mode: "markers",
        marker: { size: 5, color: r[1], opacity: 0.35 }, hovertemplate: r[2] + "<br>ΔP %{x:.0f} kW · ΔCdA %{y:.2f} m²<extra></extra>" };
    }), layout(t, { showlegend: true, xaxis: { title: { text: "power against the field, kW (bootstrap draws)" } }, yaxis: { title: { text: "drag area against the field, m²" } } }));
  }

  // Track by track (all filters)
  var TM = window.TrackMath, sumRates = TM.sumRates, bestDriver = TM.bestDriver, amrPick = TM.amrPick, drvPick = TM.drvPick, teamPick = TM.teamPick, rep = TM.rep;
  function otherTeams(evs) {
    var s = {}; evs.forEach(function (e) { Object.keys(e.team_sections_s).forEach(function (k) { if (k !== TARGET) s[k] = 1; }); });
    return Object.keys(s).sort();
  }
  function noTelemetry(evs, d) { return evs.filter(function (e) { return rep(e, d) && !e.drivers[d]; }); }
  // A team that was the reference at every one of these tracks has zero loss by definition
  function referenceOnly(evs, team) { return evs.every(function (e) { return !e.team_sections_s[team] || e.reference.team === team; }); }
  function lostOrGained(v) { return v == null || !isFinite(v) ? "–" : v >= 0 ? "lost " + f(v, 1) + "%" : "gained " + f(-v, 1) + "%"; }
  // A median rank; halfway between two ranks reads as both ("10th to 11th")
  function medRank(pos) { var m = median(pos); return m % 1 ? ord(Math.floor(m)) + " to " + ord(Math.ceil(m)) : ord(m); }
  // Why a lap has lap time only, as a short phrase ("frozen telemetry")
  function reasonShort(r) { var m = /^failed data checks(?:: (.*))?$/.exec(r || ""); return m ? (m[1] || "failed the data checks") : "no usable telemetry"; }

  function tracksText(evs, ds) {
    if (!evs.length || !ds.length) { fill("tracks_text", !evs.length ? "Pick at least one track in the bar at the top." : "Pick at least one driver in the bar at the top."); return; }
    var y = state.season, parts = [], many = evs.length > 1;
    var where = many ? "Over the " + evs.length + " selected " + y + " tracks" : "At " + trk(evs[0]) + " in " + y;
    var gaps = ds.map(function (d) { var g = evs.filter(function (e) { return rep(e, d); }); return { d: d, n: g.length, v: mean(g.map(function (e) { return e.timing[d].gap_pct; })) }; });
    var withLap = gaps.filter(function (g) { return g.n; });
    if (withLap.length) parts.push(where + ", " + list(withLap.map(function (g, i) {
      return lastName(g.d) + (i ? "'s " : "'s fastest lap was " + (many ? "on average " : "")) + f(g.v, 2) + "%" + (i ? "" : " off the fastest lap of qualifying") + (many && g.n < evs.length ? " (" + g.n + " track" + (g.n > 1 ? "s" : "") + " with a representative lap)" : "");
    })) + ".");
    gaps.filter(function (g) { return !evs.some(function (e) { return e.timing[g.d]; }); }).forEach(function (g) {
      parts.push((withLap.length ? "" : where + ", ") + lastName(g.d) + " set no lap time" + (many ? " at any of them" : withLap.length ? " there" : "") + ".");
    });
    if (ds.length === 2) {
      var both = evs.filter(function (e) { return rep(e, ds[0]) && rep(e, ds[1]); });
      var a = both.filter(function (e) { return e.timing[ds[0]].lap_time_s < e.timing[ds[1]].lap_time_s; }).length;
      if (both.length > 1) parts.push(2 * a === both.length ? "Each was the faster of the two at " + a + " of " + both.length + "." :
        lastName(a > both.length - a ? ds[0] : ds[1]) + " was the faster of the two at " + Math.max(a, both.length - a) + " of " + both.length + ".");
    }
    ds.forEach(function (d) {
      var slow = evs.filter(function (e) { return e.timing[d] && !rep(e, d); });
      if (slow.length) parts.push(lastName(d) + "'s fastest lap at " + list(slow.map(trk)) + " was more than " + repOff() + " off the fastest lap (" + list(slow.map(function (e) { return "+" + f(e.timing[d].gap_pct, 1) + "%"; })) + "), not a representative lap under the " + f(MTH.representative_pct, 0) + "% rule, so it is left out of the gap figures.");
    });
    var pos = evs.map(function (e) { return e.team_position; }).filter(function (v) { return v != null; });
    if (pos.length > 1) parts.push("As a team Aston Martin's best lap ranked " + medRank(pos) + " of " + evs[0].n_teams + " in the median track (best " + ord(Math.min.apply(null, pos)) + ", worst " + ord(Math.max.apply(null, pos)) + ").");
    var pickA = amrPick(ds), amEvs = evs.filter(function (e) { return pickA(e); }), am = sumRates(amEvs, pickA);
    if (am) {
      var rival = otherTeams(amEvs).filter(function (k) { return !referenceOnly(amEvs, k); }).map(function (k) { return { k: k, r: sumRates(amEvs, teamPick(k)) }; }).filter(function (x) { return x.r; });
      var higher = rival.filter(function (x) { return x.r.straights > am.straights; });
      var top = rival.slice().sort(function (a2, b) { return b.r.straights - a2.r.straights; })[0];
      var on = am.n > 1 ? "On those " + am.n + " tracks" : "There";
      parts.push("Compared with the reference lap, " + (ds.length > 1 ? "the faster passing Aston Martin lap" + (am.n > 1 ? " at each track" : "") : lastName(ds[0]) + "'s lap" + (am.n > 1 ? "s" : "")) + " " + lostOrGained(am.straights) + " of the time spent on the straights and " +
        lostOrGained(am.corners) + " in the corners (" + am.n + " track" + (am.n > 1 ? "s" : "") + " with usable telemetry). " +
        (top ? on + ", with each team summed over the tracks where it also had a passing lap, " + (higher.length ? higher.length + " other team" + (higher.length > 1 ? "s" : "") + " had a higher straight-line loss rate; the highest was " : "no other team had a higher straight-line loss rate; the highest was ") +
          esc(top.k) + " at " + f(top.r.straights, 1) + "%." : ""));
    }
    ds.forEach(function (d) {
      var miss = noTelemetry(evs, d);
      if (miss.length) parts.push(lastName(d) + "'s lap" + (miss.length > 1 ? "s" : "") + " at " + list(miss.map(function (e) { return trk(e) + " (" + esc(reasonShort(e.timing[d].reason)) + ")"; })) + (miss.length > 1 ? " count" : " counts") + " for lap time only.");
    });
    var wet = wetNames(evs);
    if (wet.length) parts.push("Includes wet qualifying at " + list(wet) + ", which the season analyses leave out.");
    parts.push("These are point estimates for the tracks picked; the intervals for whole seasons are in the evidence above.");
    fill("tracks_text", parts.join(" "));
  }

  function trackTiles(evs, ds) {
    var el = $("trk-tiles");
    if (!evs.length || !ds.length) { el.innerHTML = ""; return; }
    function perDriver(fn) { return ds.map(function (d) { return '<span class="dv"><i class="key" style="--c:var(--drv-' + ALL_DRIVERS.indexOf(d) + ', var(--ink-2))"></i>' + esc(lastName(d)) + " <b>" + fn(d) + "</b></span>"; }).join(""); }
    var pos = evs.map(function (e) { return e.team_position; }).filter(function (v) { return v != null; });
    var am = sumRates(evs, amrPick(ds));  // tracks without an Aston Martin lap drop out of the sums
    var race = ds.map(function (d) { return evs.filter(function (e) { return e.race && e.race.drivers[d]; }).map(function (e) { return e.race.drivers[d].gap_s; }); });
    var tiles = [
      { k: "Gap to the fastest lap", html: perDriver(function (d) { var g = evs.filter(function (e) { return rep(e, d); }); return g.length ? f(mean(g.map(function (e) { return e.timing[d].gap_pct; })), 2) + "%" : evs.some(function (e) { return e.timing[d]; }) ? "over " + f(MTH.representative_pct, 0) + "%" : "no lap"; }), ci: "mean over tracks with a representative lap" },
      { k: "Team rank, median track", v: pos.length ? medRank(pos) : "–", ci: pos.length ? "of " + evs[0].n_teams + " · best " + ord(Math.min.apply(null, pos)) + ", worst " + ord(Math.max.apply(null, pos)) : "no lap times" },
      { k: "Straights against corners", v: am && am.corners ? f(am.straights / am.corners, 2) : "–", ci: am ? "loss rates " + f(am.straights, 1) + "% and " + f(am.corners, 1) + "% · " + am.n + " track" + (am.n > 1 ? "s" : "") : "no usable telemetry", amr: true },
      { k: "Race pace gap to the best team", html: race.some(function (r) { return r.length; }) ? perDriver(function (d) { var r = race[ds.indexOf(d)]; return r.length ? f(mean(r), 2) + " s" : "–"; }) : null, v: "–",
        ci: "per lap, mean over dry races: " + list(ds.map(function (d) { var n = race[ds.indexOf(d)].length; return lastName(d) + " " + n + " race" + (n === 1 ? "" : "s"); })) },
    ];
    el.innerHTML = tiles.map(function (t) {
      return '<div class="tile"><span class="k">' + t.k + "</span>" + (t.html ? '<span class="v multi">' + t.html + "</span>" : '<span class="v' + (t.amr ? " amr" : "") + '">' + t.v + "</span>") + '<span class="ci">' + t.ci + "</span></div>";
    }).join("");
  }

  function renderTrackGap(t, evs, ds) {
    if (!evs.length || !ds.length) return empty("ch-trk-gap", "Pick at least one track and one driver.");
    var x = evs.map(function (e) { return trk(e); });
    var traces = [
      { x: x, y: evs.map(function (e) { return e.field_gap_pct ? e.field_gap_pct.p75 : null; }), type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
      { x: x, y: evs.map(function (e) { return e.field_gap_pct ? e.field_gap_pct.p25 : null; }), type: "scatter", mode: "lines", fill: "tonexty", fillcolor: hexA(t.field, 0.25), line: { width: 0 }, name: "other teams, middle half", hoverinfo: "skip" },
    ];
    ds.forEach(function (d) {
      var c = drvColor(t, d);
      traces.push({ x: x, y: evs.map(function (e) { return rep(e, d) ? e.timing[d].gap_pct : null; }), name: fullName(d), type: "scatter", mode: evs.length > 1 ? "lines+markers" : "markers",
        line: { color: c, width: 2 }, marker: { size: 9, symbol: drvSymbol(d), color: c, line: { color: t.surface, width: 1.5 } }, connectgaps: false,
        customdata: evs.map(function (e) { var r = e.timing[d]; return r ? [lapTime(r.lap_time_s), r.gap_s, ord(r.rank), r.n_drivers, r.telemetry ? "" : " · no usable telemetry"] : null; }),
        hovertemplate: fullName(d) + " · %{x}<br>%{customdata[0]} · +%{customdata[1]:.3f} s · %{y:.2f}%<br>%{customdata[2]} fastest of %{customdata[3]}%{customdata[4]}<extra></extra>" });
    });
    plot("ch-trk-gap", traces, layout(t, { showlegend: true, yaxis: { title: { text: "% slower than the fastest lap" }, rangemode: "tozero" }, xaxis: { tickangle: evs.length > 8 ? -40 : 0, type: "category" } }));
  }

  function renderTrackRates(t, evs, ds) {
    if (!evs.length || !ds.length) return empty("ch-trk-rates", "Pick at least one track and one driver.");
    var pickA = amrPick(ds), amEvs = evs.filter(function (e) { return pickA(e); });
    var teams = otherTeams(amEvs).map(function (k) { return { k: k, r: sumRates(amEvs, teamPick(k)) }; }).filter(function (x) { return x.r; });
    var am = sumRates(amEvs, pickA);
    var drv = ds.map(function (d) { return { d: d, r: sumRates(evs, drvPick(d)) }; }).filter(function (x) { return x.r; });
    if (!am) return empty("ch-trk-rates", "No usable Aston Martin telemetry at the selected tracks.");
    var all = teams.map(function (x) { return x.r; }).concat([am]).concat(drv.map(function (x) { return x.r; }));
    var lim = Math.max(1, Math.max.apply(null, all.map(function (r) { return Math.max(r.corners, r.straights); }).filter(isFinite)) * 1.15);
    var lo = Math.min(-0.3, Math.min.apply(null, all.map(function (r) { return Math.min(r.corners, r.straights); }).filter(isFinite)) - 0.3);
    var g = rateGuides(t, lim);
    var traces = g.traces.concat([{
      x: teams.map(function (x) { return x.r.corners; }), y: teams.map(function (x) { return x.r.straights; }), hovertext: teams.map(function (x) { return x.k; }),
      text: teams.map(function (x) { return x.r.lap > 2.5 ? x.k : ""; }), type: "scatter", mode: "markers+text", textposition: "top left", textfont: { size: 10, color: t.muted },
      name: "other teams", marker: { size: 9, color: t.field, line: { color: t.surface, width: 2 } },
      customdata: teams.map(function (x) { return [x.r.lap, x.r.n]; }),
      hovertemplate: "%{hovertext}<br>corners %{x:.2f}% · straights %{y:.2f}%<br>lap %{customdata[0]:.2f}% · %{customdata[1]} tracks<extra></extra>" }]);
    if (ds.length > 1) {
      traces.push({ x: [am.corners], y: [am.straights], type: "scatter", mode: "markers",
        name: "Aston Martin, faster passing lap", marker: { size: 13, color: t.amr, symbol: "star", line: { color: t.surface, width: 1.5 } },
        hovertemplate: "Aston Martin (faster passing lap at each track)<br>corners %{x:.2f}% · straights %{y:.2f}%<br>" + am.n + " tracks<extra></extra>" });
    }
    drv.forEach(function (x) {
      var c = drvColor(t, x.d);
      traces.push({ x: [x.r.corners], y: [x.r.straights], text: [x.d], type: "scatter", mode: "markers+text", textposition: "top right", textfont: { size: 11, color: t.ink2 },
        name: fullName(x.d), marker: { size: 11, symbol: drvSymbol(x.d), color: c, line: { color: t.surface, width: 1.5 } },
        hovertemplate: fullName(x.d) + "<br>corners %{x:.2f}% · straights %{y:.2f}%<br>lap " + f(x.r.lap, 2) + "% · " + x.r.n + " tracks<extra></extra>" });
    });
    plot("ch-trk-rates", traces, layout(t, { showlegend: true, margin: { l: 56, r: 16, t: 48, b: 44 },
      xaxis: { title: { text: "loss rate in corners, % of the reference lap's time there" }, range: [lo, lim] },
      yaxis: { title: { text: "loss rate on straights, %" }, range: [lo, lim] }, annotations: g.notes }));
  }

  function renderTrackHeat(t, evs, ds) {
    var el = $("ch-trk-heat");
    if (!evs.length || !ds.length) return empty("ch-trk-heat", "Pick at least one track and one driver.");
    var ylab = evs.map(function (e) { return trk(e); }), xlab = SECS.map(function (k) { return SEC_SHORT[k]; });
    var vals = [];
    var z = ds.map(function (d) {
      return evs.map(function (e) { var s = e.drivers[d]; return SECS.map(function (k) { var v = s && e.ref_time_s[k] > 0 ? 100 * s.sections_s[k] / e.ref_time_s[k] : null; if (v != null) vals.push(Math.abs(v)); return v; }); });
    });
    if (!vals.length) return empty("ch-trk-heat", "No usable telemetry for the selected drivers at these tracks.");
    vals.sort(function (a, b) { return a - b; });
    var cap = Math.max(1, vals[Math.floor(0.95 * (vals.length - 1))]);
    var gap = 0.04, w = (1 - gap * (ds.length - 1)) / ds.length, lay = {}, notes = [];
    var traces = ds.map(function (d, i) {
      var ax = i ? String(i + 1) : "";
      lay["xaxis" + ax] = { domain: [i * (w + gap), i * (w + gap) + w], side: "top", tickfont: { size: 10 }, anchor: "y", fixedrange: true };
      notes.push({ xref: "x" + ax + " domain", yref: "paper", x: 0.5, y: 0, yanchor: "top", yshift: -6, showarrow: false, text: esc(fullName(d)), font: { size: 11, color: t.ink2 } });
      return { type: "heatmap", x: xlab, y: ylab, z: z[i], xaxis: "x" + ax, yaxis: "y", zmin: -cap, zmax: cap, zmid: 0,
        colorscale: [[0, t.gain], [0.5, t.rule], [1, t.loss]], showscale: i === ds.length - 1, xgap: 2, ygap: 2,
        colorbar: { title: { text: "%", font: { size: 10, color: t.muted } }, thickness: 8, len: 0.7, tickfont: { size: 10, color: t.muted }, outlinewidth: 0 },
        texttemplate: evs.length <= 16 ? "%{z:.1f}" : "", textfont: { size: 10, color: t.ink },
        customdata: evs.map(function (e) { var s = e.drivers[d]; return SECS.map(function (k) { return s ? s.sections_s[k] : null; }); }),
        hovertemplate: esc(fullName(d)) + " · %{y}<br>%{x}: %{z:.2f}% · %{customdata:+.3f} s<extra></extra>", hoverongaps: false };
    });
    var h = Math.max(320, 24 * evs.length + 90);
    el.style.height = h + "px";
    var base = layout(t, { height: h, margin: { l: 110, r: 16, t: 34, b: 30 }, yaxis: { autorange: "reversed", type: "category", fixedrange: true, ticks: "", dtick: 1 }, annotations: notes });
    Object.keys(lay).forEach(function (k) { base[k] = axis(t, lay[k]); });
    plot("ch-trk-heat", traces, base);
  }

  function renderTrackCorners(t, evs, ds) {
    if (!evs.length || !ds.length) return empty("ch-trk-corners", "Pick at least one track and one driver.");
    var cls = ["high", "medium", "low"], traces = [];
    ds.forEach(function (d) {
      var c = drvColor(t, d);
      var agg = cls.map(function (k) { var s = 0, n = 0, m = 0; evs.forEach(function (e) { var x = e.drivers[d]; if (x && x.corner_class_kmh[k].n) { s += x.corner_class_kmh[k].sum; n += x.corner_class_kmh[k].n; m++; } }); return { v: n ? s / n : null, n: n, m: m }; });
      traces.push({ y: cls.map(function (k) { return SEC_LABEL[k]; }), x: agg.map(function (a) { return a.v; }), name: fullName(d), type: "scatter", mode: "markers",
        marker: { size: 11, symbol: drvSymbol(d), color: c, line: { color: t.surface, width: 1.5 } },
        customdata: agg.map(function (a) { return [a.n, a.m]; }), hovertemplate: fullName(d) + " · %{y}<br>%{x:+.1f} km/h against the other teams' median · %{customdata[0]} corners, %{customdata[1]} tracks<extra></extra>" });
    });
    if (!traces.some(function (tr) { return tr.x.some(function (v) { return v != null; }); })) return empty("ch-trk-corners", "No usable corner speeds for the selected drivers at these tracks.");
    plot("ch-trk-corners", traces, layout(t, { showlegend: ds.length > 1, margin: { l: 150, r: 16, t: ds.length > 1 ? 40 : 10, b: 44 },
      xaxis: { title: { text: "km/h against the other teams" } }, yaxis: { type: "category", autorange: "reversed" },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderTrackStraights(t, evs, ds) {
    if (!evs.length || !ds.length) return empty("ch-trk-straights", "Pick at least one track and one driver.");
    var rows = [["entry_kmh", "start of the straight"], ["peak_kmh", "peak speed"], ["end_kmh", "braking point"], ["ftl", "held at full throttle"]], traces = [], counts = [];
    ds.forEach(function (d) {
      var c = drvColor(t, d), S0 = { entry_kmh: 0, peak_kmh: 0, end_kmh: 0, ftl: 0, n: 0, m: 0 };
      evs.forEach(function (e) {
        var x = e.drivers[d]; if (!x || !x.straights.n) return;
        ["entry_kmh", "peak_kmh", "end_kmh"].forEach(function (k) { S0[k] += x.straights[k]; });
        S0.ftl += x.straights.field_full_throttle_loss_kmh - x.straights.full_throttle_loss_kmh; // negative: drops more speed than the field
        S0.n += x.straights.n; S0.m++;
      });
      counts.push(lastName(d) + " " + S0.n + " at " + S0.m + " track" + (S0.m === 1 ? "" : "s"));
      traces.push({ y: rows.map(function (r) { return r[1]; }), x: rows.map(function (r) { return S0.n ? S0[r[0]] / S0.n : null; }), name: fullName(d), type: "scatter", mode: "markers",
        marker: { size: 11, symbol: drvSymbol(d), color: c, line: { color: t.surface, width: 1.5 } },
        hovertemplate: fullName(d) + " · %{y}<br>%{x:+.1f} km/h against the other teams' median · " + S0.n + " straights, " + S0.m + " tracks<extra></extra>" });
    });
    // Only long full-throttle runs count as straights, so a track's main straight can be missing
    fill("trk_straights_sub", "km/h, mean over the straights long enough to count (at least " + f(XI.straight_min_m, 0) + " m at full throttle in a straight line, clear of the timing line): " +
      list(counts) + ". Negative = slower or more speed lost");
    if (!traces.some(function (tr) { return tr.x.some(function (v) { return v != null; }); })) return empty("ch-trk-straights", "No straights with usable telemetry for the selected drivers.");
    plot("ch-trk-straights", traces, layout(t, { showlegend: ds.length > 1, margin: { l: 150, r: 16, t: ds.length > 1 ? 40 : 10, b: 44 },
      xaxis: { title: { text: "km/h against the other teams" } }, yaxis: { type: "category", autorange: "reversed" },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderTrackTable(evs, ds) {
    var tb = $("tbl-tracks");
    if (!evs.length || !ds.length) { tb.innerHTML = ""; return; }
    var head = "<thead><tr><th>Track</th><th>Date (UTC)</th>" + ds.map(function (d) { return '<th class="num">' + esc(d) + " gap · rank</th>"; }).join("") +
      '<th class="num">Team</th><th class="num">Straights</th><th class="num">Corners</th>' + ds.map(function (d) { return '<th class="num">' + esc(d) + " race</th>"; }).join("") + "</tr></thead>";
    var body = evs.map(function (e) {
      var b = bestDriver(e, ds), s = b ? e.drivers[b].sections_s : null;
      return '<tr data-key="' + e.key + '" tabindex="0"' + (e.key === state.focus[state.season] ? ' class="on"' : "") + '><td><span class="rd">R' + e.round + "</span>" + esc(trk(e)) + (e.wet ? ' <span class="pill">wet</span>' : "") + "</td><td>" + shortDay(e.date) + "</td>" +
        ds.map(function (d) {
          var r = e.timing[d];
          return r ? '<td class="num">' + (r.representative === false ? '<span class="hint" title="more than ' + repOff() + ' off the fastest lap: not a representative lap">‡ </span>' : "") + (r.telemetry ? "" : '<span class="hint" title="' + esc(r.reason || "") + '">† </span>') + "+" + f(r.gap_s, 3) + " s · " + r.rank + "/" + r.n_drivers + "</td>" : '<td class="num"><span class="hint">no lap</span></td>';
        }).join("") +
        '<td class="num">' + (e.team_position ? e.team_position + "/" + e.n_teams : "–") + '</td><td class="num">' + (s ? sgn(s.straights, 3) + " s" : "–") + '</td><td class="num">' + (s ? sgn(s.high + s.medium + s.low, 3) + " s" : "–") + "</td>" +
        ds.map(function (d) { var r = e.race && e.race.drivers[d]; return '<td class="num">' + (r ? "+" + f(r.gap_s, 2) + " s" : '<span class="hint">' + (e.race ? "–" : "no fit") + "</span>") + "</td>"; }).join("") + "</tr>";
    }).join("");
    tb.innerHTML = "<caption>Gap and rank: each driver's fastest lap against the fastest lap and every driver's († = the lap failed the data checks, so lap time only; ‡ = more than " + repOff() + " off, not a representative lap) · Team: rank of the team's fastest lap · Straights, corners: seconds " + (ds.length > 1 ? "the faster passing Aston Martin lap" : esc(lastName(ds[0])) + "'s lap") + " lost to the reference lap there · Race: corrected pace, s per lap behind the best team. Click a row to open the track below.</caption>" + head + "<tbody>" + body + "</tbody>";
  }
  function onTableActivate(e) {
    var tr = e.target.closest("tr[data-key]"); if (!tr) return;
    if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    setFocus(tr.getAttribute("data-key"));
    $("detail").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  function renderTracks(t) {
    t = t || theme();
    var evs = selEvents(), ds = selDrivers();
    tracksText(evs, ds); trackTiles(evs, ds);
    renderTrackGap(t, evs, ds); renderTrackRates(t, evs, ds); renderTrackHeat(t, evs, ds);
    renderTrackCorners(t, evs, ds); renderTrackStraights(t, evs, ds); renderTrackTable(evs, ds);
  }

  // Race pace (all filters)
  function renderRace(t) {
    t = t || theme();
    var evs = selEvents(), ds = selDrivers();
    var by = byKey(S.race_pace || [], "season");
    var gPrev = (by[Y0] || []).filter(function (r) { return r.team === TARGET; })[0] || {}, gLast = (by[Y] || []).filter(function (r) { return r.team === TARGET; })[0] || {};
    var sel = ds.map(function (d) { var r = evs.filter(function (e) { return e.race && e.race.drivers[d]; }); return { d: d, n: r.length, v: mean(r.map(function (e) { return e.race.drivers[d].gap_s; })), single: r.filter(function (e) { return e.race.drivers[d].single_stint; }).map(function (e) { return trk(e); }) }; });
    var noRace = evs.filter(function (e) { return !e.race; }).map(function (e) { return trk(e); });
    fill("race_text", "Every green-flag lap of every dry race is fitted with driver pace, compound offsets, tyre degradation per lap of age and a fuel effect per lap, so the comparison is at equal fuel and fresh tyres. Intervals come from a delete-one-stint jackknife: each stint is left out in turn and the model refitted, so stint-level offsets such as traffic or tyre preparation enter the uncertainty; the tests check by simulation that the intervals cover about as often as they claim. A driver with only one stint cannot be left out, so intervals involving them are too narrow. Aston Martin's corrected race pace averaged " +
      f(gPrev.mean, 2) + " s a lap off the best team in " + Y0 + " (" + gPrev.count + " races) and " + f(gLast.mean, 2) + " s in " + Y + " (" + gLast.count + " races). " +
      (sel.some(function (x) { return x.n; }) ? "Over the selected tracks, " + list(sel.filter(function (x) { return x.n; }).map(function (x) { return lastName(x.d) + " averaged " + f(x.v, 2) + " s per lap (" + x.n + " race" + (x.n > 1 ? "s" : "") + ")"; })) + ". " : "") +
      (noRace.length ? "No race-pace fit at " + list(noRace) + " (wet, or too little green-flag running on slicks). " : "") +
      sel.filter(function (x) { return x.single.length; }).map(function (x) { return lastName(x.d) + " ran a single stint at " + list(x.single) + ", so " + (x.single.length > 1 ? "those intervals are" : "that interval is") + " too narrow. "; }).join(""));
    if (!evs.length || !ds.length) return empty("ch-race", "Pick at least one track and one driver.");
    var x = evs.map(function (e) { return trk(e); }), traces = [];
    ds.forEach(function (d, i) {
      var c = drvColor(t, d), off = (i - (ds.length - 1) / 2) * 0.18;
      var xi = evs.map(function (e, j) { return j + off; });
      traces.push({ x: xi, y: evs.map(function (e) { return rep(e, d) ? e.timing[d].gap_s : null; }), name: d + " qualifying", type: "scatter", mode: "markers",
        marker: { size: 8, symbol: "diamond-open", color: c, line: { width: 2, color: c } }, customdata: x, hovertemplate: fullName(d) + " · %{customdata}<br>qualifying +%{y:.2f} s to the fastest lap<extra></extra>" });
      traces.push({ x: xi, y: evs.map(function (e) { var r = e.race && e.race.drivers[d]; return r ? r.gap_s : null; }), name: d + " race pace", type: "scatter", mode: "markers",
        marker: { size: 9, symbol: drvSymbol(d), color: c, line: { color: t.surface, width: 1.5 } }, customdata: x,
        error_y: { type: "data", symmetric: false, array: evs.map(function (e) { var r = e.race && e.race.drivers[d]; return r ? r.gap_hi - r.gap_s : null; }), arrayminus: evs.map(function (e) { var r = e.race && e.race.drivers[d]; return r ? r.gap_s - r.gap_lo : null; }), color: c, thickness: 1.2, width: 0 },
        hovertemplate: fullName(d) + " · %{customdata}<br>race pace +%{y:.2f} s per lap behind the best team<extra></extra>" });
    });
    plot("ch-race", traces, layout(t, { showlegend: true, yaxis: { title: { text: "s per lap behind the best team" }, rangemode: "tozero" },
      xaxis: { tickmode: "array", tickvals: x.map(function (v, j) { return j; }), ticktext: x, tickangle: evs.length > 8 ? -40 : 0, range: [-0.6, evs.length - 0.4] } }));
  }

  // Track detail (season, drivers and the focus track)
  function fillTrackSelect() {
    var sel = $("sel-track"), evs = selEvents(), y = state.season;
    sel.innerHTML = evs.map(function (e) {
      return '<option value="' + e.key + '">R' + e.round + " · " + esc(trk(e)) + " · " + esc(e.event) + (e.wet ? " (wet)" : Object.keys(e.drivers).length ? "" : " (lap times only)") + "</option>";
    }).join("");
    sel.disabled = !evs.length;
    if (state.focus[y]) sel.value = state.focus[y];
  }
  function setFocus(key) {
    var y = state.season;
    state.focus[y] = key;
    if ($("sel-track").value !== key && key) $("sel-track").value = key;
    document.querySelectorAll("#tbl-tracks tr[data-key]").forEach(function (r) { r.classList.toggle("on", r.getAttribute("data-key") === key); });
    current.entry = key ? entry(key) : null;
    current.failed = [];
    status();
    if (!key) { current.detail = null; current.event = null; rerender(["detail"]); return; }
    var pending = 2, fail = [];
    function done() {
      if (--pending || state.focus[state.season] !== key) return;
      current.detail = (window.EXPLORER || {})[key] || null; current.event = (window.EVENTS || {})[key] || null; current.failed = fail;
      rerender(["detail"]);
    }
    loadScript("data/explorer/" + key + ".js", done, function () { fail.push("track"); done(); });
    loadScript("data/events/" + key + ".js", done, function () { fail.push("lap"); done(); });
  }

  // "failed data checks: frozen telemetry" -> "failed the data checks (frozen telemetry)"
  function whyNot(reason) {
    var m = /^failed data checks(?:: (.*))?$/.exec(reason || "");
    return m ? "failed the data checks" + (m[1] ? " (" + m[1] + ")" : "") : "has no usable telemetry";
  }
  function amrLap(e, ds) { var d = bestDriver(e, ds); return d ? { d: d, s: e.drivers[d].sections_s, lap: e.timing[d].lap_time_s } : null; }
  // The team the analysed Aston Martin lap is compared with: the closest team whose compared lap (its fastest
  // passing lap) is faster. `direct`: it is also directly ahead of Aston Martin on official lap times, and the
  // analysed lap is Aston Martin's fastest. `skipped`: teams in between whose fastest lap has no usable telemetry.
  function rivalOf(e, D, ds) {
    var me = amrLap(e, ds); if (!me) return null;
    var lapOf = function (team) { return TM.comparedLap(e, e.team_sections_s[team]); };
    var cands = D.order.filter(function (r) { return r.team !== TARGET && lapOf(r.team) != null && lapOf(r.team) < me.lap - 1e-9; })
      .sort(function (a, b) { return lapOf(b.team) - lapOf(a.team); });
    var mine = D.order.filter(function (r) { return r.team === TARGET; })[0];
    var above = mine ? D.order[D.order.indexOf(mine) - 1] : null;
    var teamBest = Math.min.apply(null, Object.keys(e.timing).map(function (d) { return e.timing[d].lap_time_s; }));
    var r = cands[0];
    if (!r) return { me: me };
    var skipped = D.order.filter(function (o) { return o.team !== TARGET && !e.team_sections_s[o.team] && o.lap_time_s < me.lap && o.lap_time_s > r.lap_time_s; }).map(function (o) { return o.team; });
    return { team: r.team, driver: r.driver, tel: r.telemetry_driver, lap: lapOf(r.team), s: e.team_sections_s[r.team], me: me, skipped: skipped,
      direct: !!above && above.team === r.team && me.lap <= teamBest + 1e-9 };
  }
  // "1.636 s slower, 0.930 s of it on the straights", in whichever form the numbers allow
  function gapPhrase(rv) {
    var diff = 0, st = rv.me.s.straights - rv.s.straights; SECS.forEach(function (k) { diff += rv.me.s[k] - rv.s[k]; });
    var co = diff - st, head = lastName(rv.me.d) + "'s lap was " + f(diff, 3) + " s slower";
    if (st > 0 && co >= 0) return head + ", " + f(st, 3) + " s of it on the straights";
    if (st > 0) return head + ": " + f(st, 3) + " s slower on the straights and " + f(-co, 3) + " s faster in the corners";
    return head + ": " + f(co, 3) + " s slower in the corners and " + f(-st, 3) + " s faster on the straights";
  }

  function detailText(e, D, ds) {
    var y = state.season, fl = e.fastest_lap, parts = [];
    parts.push("<b>" + esc(e.event) + " " + y + "</b>, " + esc(e.circuit) + ", qualifying on " + day(e.date) + " (UTC). The fastest lap was " + esc(fl.driver) + "'s (" + esc(fl.team) + ") " + lapTime(fl.lap_time_s) +
      (fl.is_pole ? ", on pole." : ", set in " + esc(fl.segment || "an earlier session") + "."));
    var tm = ds.filter(function (d) { return e.timing[d]; }).sort(function (a, b) { return e.timing[a].lap_time_s - e.timing[b].lap_time_s; });
    if (tm.length) parts.push(list(tm.map(function (d) { var r = e.timing[d]; return lastName(d) + "'s best was " + lapTime(r.lap_time_s) + " (+" + f(r.gap_s, 3) + " s, " + ord(r.rank) + " fastest of " + r.n_drivers + (r.representative === false ? "; more than " + repOff() + " off, so not a representative lap" : "") + ")"; })) + ".");
    ds.filter(function (d) { return !e.timing[d]; }).forEach(function (d) { parts.push(lastName(d) + " set no lap time."); });
    if (e.team_position) parts.push("Ranked by each team's fastest lap of the session, Aston Martin was " + ord(e.team_position) + " of " + e.n_teams + ".");
    var rv = rivalOf(e, D, ds);
    if (rv && rv.team) {
      var lead = rv.direct ? "Against " + esc(rv.team) + ", the team directly ahead, " :
        rv.skipped.length ? list(rv.skipped.map(esc)) + (rv.skipped.length > 1 ? " were" : " was") + " closer but " + (rv.skipped.length > 1 ? "have" : "has") + " no lap with usable telemetry. Against " + esc(rv.team) + ", the closest team ahead with one, " :
        "Against " + esc(rv.team) + ", the closest team ahead of that lap, ";
      parts.push(lead + gapPhrase(rv) + "." + (rv.tel !== rv.driver ? " (" + esc(rv.team) + "'s fastest lap, by " + esc(rv.driver) + ", has no usable telemetry, so its comparison uses " + esc(rv.tel) + "'s.)" : ""));
    } else if (rv && e.team_position === 1) parts.push("No team was ahead.");
    var miss = ds.filter(function (d) { return e.timing[d] && !e.timing[d].telemetry; });
    if (miss.length) {
      var analysed = ds.some(function (d) { return e.drivers[d]; }), other = Object.keys(e.drivers).filter(function (d) { return ds.indexOf(d) < 0; });
      parts.push(list(miss.map(function (d) { return lastName(d) + "'s lap " + esc(whyNot(e.timing[d].reason)); })) + ", so " +
        (analysed ? "only the other lap is analysed below." : other.length ? "there is no section or corner analysis for the selected driver" + (miss.length > 1 ? "s" : "") + "; add " + list(other.map(lastName)) + " in the Drivers filter to see the lap" + (other.length > 1 ? "s" : "") + " that " + (other.length > 1 ? "were" : "was") + " analysed." : "this track has lap times but no section or corner analysis."));
    }
    fill("detail_text", parts.join(" "));
  }

  function detailTiles(e, D, ds) {
    var tiles = [], rv = rivalOf(e, D, ds), me = amrLap(e, ds);
    var all = Object.keys(e.timing).map(function (d) { return e.timing[d].gap_s; });
    tiles.push({ k: "Team rank by fastest lap", v: e.team_position ? ord(e.team_position) : "–", ci: "of " + e.n_teams + (all.length ? " · fastest Aston Martin +" + f(Math.min.apply(null, all), 3) + " s" : ""), amr: true });
    if (rv && rv.team) {
      var diff = 0; SECS.forEach(function (k) { diff += rv.me.s[k] - rv.s[k]; });
      tiles.push({ k: "Gap to " + rv.team, v: sgn(diff, 3) + " s", ci: sgn(rv.me.s.straights - rv.s.straights, 3) + " s on the straights · " + lastName(rv.me.d) + "'s lap" });
    }
    if (me) {
      var rates = SECS.filter(function (k) { return e.ref_time_s[k] > 0; }).map(function (k) { return { k: k, v: 100 * me.s[k] / e.ref_time_s[k] }; }).sort(function (a, b) { return b.v - a.v; });
      if (rates.length) tiles.push({ k: "Highest loss rate", v: f(rates[0].v, 1) + "%", ci: SEC_LABEL[rates[0].k] + " · " + sgn(me.s[rates[0].k], 3) + " s · " + lastName(me.d) });
    }
    if (e.race) tiles.push({ k: "Race pace gap", v: e.race.team_gap_s != null ? "+" + f(e.race.team_gap_s, 2) + " s" : "–", ci: "per lap · " + (e.race.team_rank ? ord(e.race.team_rank) + " of " + e.race.n_teams + " · " : "") + LVL + " interval " + (e.race.team_ci ? ci(e.race.team_ci, 2) : "–") });
    $("det-tiles").innerHTML = tiles.map(function (x) { return '<div class="tile"><span class="k">' + esc(x.k) + '</span><span class="v' + (x.amr ? " amr" : "") + '">' + x.v + '</span><span class="ci">' + x.ci + "</span></div>"; }).join("");
  }

  function renderOrder(t, e, D) {
    var o = D.order;
    plot("ch-order", [{ y: o.map(function (r) { return r.team; }), x: o.map(function (r) { return r.gap_s; }), type: "bar", orientation: "h",
      marker: { color: o.map(function (r) { return r.team === TARGET ? t.amr : t.field; }) },
      text: o.map(function (r) { return r.gap_s ? "+" + f(r.gap_s, 3) : lapTime(r.lap_time_s); }), textposition: "outside", textfont: { size: 10, color: t.ink2, family: t.font }, cliponaxis: false,
      customdata: o.map(function (r) { return [r.driver, lapTime(r.lap_time_s)]; }), hovertemplate: "%{y} · %{customdata[0]}<br>%{customdata[1]} · +%{x:.3f} s<extra></extra>" }],
      layout(t, { bargap: 0.3, margin: { l: 120, r: 50, t: 10, b: 44 }, xaxis: { title: { text: "s behind the fastest lap" }, rangemode: "tozero" }, yaxis: { autorange: "reversed", type: "category" } }));
  }

  function renderRival(t, e, D, ds) {
    var rv = rivalOf(e, D, ds);
    if (!rv || !rv.team) { $("rival-sub").textContent = ""; return empty("ch-rival", rv ? "No team with usable telemetry was ahead." : noLapText(e, ds)); }
    $("rival-sub").textContent = lastName(rv.me.d) + " against " + rv.team + " (" + rv.tel + "), s, + = Aston Martin slower";
    var vals = SECS.map(function (k) { return rv.me.s[k] - rv.s[k]; }), tot = vals.reduce(function (a, b) { return a + b; }, 0);
    var y = SECS.map(function (k) { return SEC_LABEL[k]; }).concat(["whole lap"]), x = vals.concat([tot]);
    plot("ch-rival", [{ y: y, x: x, type: "bar", orientation: "h", marker: { color: x.map(function (v, i) { return i === x.length - 1 ? t.ink2 : v >= 0 ? t.loss : t.gain; }) },
      text: x.map(function (v) { return sgn(v, 3) + " s"; }), textposition: "outside", textfont: { size: 11, color: t.ink2, family: t.font }, cliponaxis: false,
      hovertemplate: "%{y}: %{x:+.3f} s<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 150, r: 64, t: 10, b: 44 }, xaxis: { title: { text: "s, Aston Martin minus " + rv.team } }, yaxis: { type: "category", autorange: "reversed" },
        shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function noLapText(e, ds) {
    if (!ds.length) return "Pick at least one driver in the bar at the top.";
    return Object.keys(e.drivers).length ? "No usable telemetry for the selected driver" + (ds.length > 1 ? "s" : "") + " here." : "No usable Aston Martin telemetry here.";
  }
  function cornerName(c) { return c.label + (c.name ? " " + c.name : ""); }
  function renderSpeed(t, e, D, ds) {
    var d = D.distance_m, rd = e.reference.driver, have = ds.filter(function (x) { return D.drivers[x]; });
    $("speed-sub").textContent = "reference lap " + rd + " (" + e.reference.team + ") " + lapTime(e.reference.lap_time_s) + (have.length ? " against " + have.map(function (x) { return x + " " + lapTime(D.drivers[x].lap_time_s); }).join(", ") : "");
    // Corner labels along the top; on a phone-width chart they would run into each other
    var ann = $("ch-speed").clientWidth < 600 ? [] : D.corners.map(function (c) { return { x: c.distance_m, yref: "paper", y: 1, yanchor: "bottom", text: c.label, showarrow: false, font: { size: 9, color: t.muted, family: t.font } }; });
    var traces = [{ x: d, y: D.reference_trace.speed_kmh, name: rd + " (reference)", type: "scatter", mode: "lines", line: { color: t.ref, width: 1.5 }, hovertemplate: rd + " %{y:.0f} km/h<extra></extra>" }];
    have.forEach(function (x) { traces.push({ x: d, y: D.drivers[x].trace.speed_kmh, name: x, type: "scatter", mode: "lines", line: { color: drvColor(t, x), width: 1.5 }, hovertemplate: x + " %{y:.0f} km/h<extra></extra>" }); });
    plot("ch-speed", traces, layout(t, { showlegend: true, legend: { orientation: "h", x: 0, y: 1.14 }, hovermode: "x unified", margin: { l: 56, r: 16, t: 30, b: 10 },
      xaxis: { showticklabels: false }, yaxis: { title: { text: "km/h" } }, annotations: ann }));
    if (!have.length) return empty("ch-delta", noLapText(e, ds));
    plot("ch-delta", have.map(function (x) {
      return { x: d, y: D.drivers[x].trace.delta_s, name: x, type: "scatter", mode: "lines", line: { color: drvColor(t, x), width: 1.6 }, hovertemplate: x + " gap %{y:+.3f} s<extra></extra>" };
    }), layout(t, { hovermode: "x unified", margin: { l: 56, r: 16, t: 4, b: 40 }, xaxis: { title: { text: "distance from the line, m" } }, yaxis: { title: { text: "gap, s" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderMap(t, e, D, ds) {
    var have = ds.filter(function (x) { return D.drivers[x]; });
    if (!have.length) { $("seg-map").innerHTML = ""; $("map-sub").textContent = ""; return empty("ch-map", noLapText(e, ds)); }
    if (have.indexOf(state.mapDriver) < 0) state.mapDriver = have[0];
    seg("seg-map", have.map(function (x) { return [x, lastName(x)]; }), state.mapDriver, function (v) { state.mapDriver = v; renderMap(theme(), e, D, ds); });
    $("seg-map").hidden = have.length < 2;
    var dv = state.mapDriver, mp = D.map, loss = D.drivers[dv].loss_per_100m_s.map(function (v) { return v * 1000; });
    var abs = loss.map(Math.abs).sort(function (a, b) { return a - b; }), cap = Math.max(abs[Math.floor(abs.length * 0.95)] || 1, 1);
    $("map-sub").textContent = fullName(dv) + " against " + e.reference.driver + ", ms lost (brick) or gained (slate) per 100 m";
    var cx = D.corners.map(function (c) { return interp(D.distance_m, mp.x, c.distance_m); }), cy = D.corners.map(function (c) { return interp(D.distance_m, mp.y, c.distance_m); });
    plot("ch-map", [
      { x: mp.x, y: mp.y, type: "scatter", mode: "markers", marker: { size: 6, color: loss, cmin: -cap, cmid: 0, cmax: cap,
        colorscale: [[0, t.gain], [0.5, t.rule], [1, t.loss]], colorbar: { title: { text: "ms/100 m", font: { size: 10, color: t.muted } }, thickness: 8, len: 0.6, tickfont: { size: 10, color: t.muted }, outlinewidth: 0 } },
        customdata: D.distance_m.map(function (s, i) { return [s, loss[i]]; }), hovertemplate: "%{customdata[0]:.0f} m: %{customdata[1]:+.0f} ms per 100 m<extra></extra>" },
      { x: cx, y: cy, text: D.corners.map(function (c) { return c.label; }), type: "scatter", mode: "text", textfont: { size: 10, color: t.ink2, family: t.font }, hoverinfo: "skip" },
    ], layout(t, { margin: { l: 8, r: 8, t: 8, b: 8 }, xaxis: { visible: false, scaleanchor: "y" }, yaxis: { visible: false } }));
  }

  function renderDetailRates(t, e, D, ds) {
    var teams = Object.keys(e.team_sections_s).filter(function (k) { return k !== TARGET; }).map(function (k) { return { k: k, r: sumRates([e], teamPick(k)) }; });
    var drv = ds.filter(function (d) { return e.drivers[d]; }).map(function (d) { return { d: d, r: sumRates([e], drvPick(d)) }; });
    var all = teams.map(function (x) { return x.r; }).concat(drv.map(function (x) { return x.r; }));
    var lim = Math.max(1, Math.max.apply(null, all.map(function (r) { return Math.max(r.corners, r.straights); })) * 1.15);
    var lo = Math.min(-0.3, Math.min.apply(null, all.map(function (r) { return Math.min(r.corners, r.straights); })) - 0.3);
    var g = rateGuides(t, lim);
    // Name the team ahead (the one in the chart beside this) and the reference team; the rest on hover
    var rv = rivalOf(e, D, ds), named = [rv && rv.team, e.reference.team];
    var traces = g.traces.concat([{ x: teams.map(function (x) { return x.r.corners; }), y: teams.map(function (x) { return x.r.straights; }), hovertext: teams.map(function (x) { return x.k; }),
      text: teams.map(function (x) { return named.indexOf(x.k) >= 0 ? x.k : ""; }), type: "scatter", mode: "markers+text", textfont: { size: 10, color: t.muted }, name: "other teams",
      textposition: teams.map(function (x) { return x.r.corners < lim / 4 ? "top right" : "top left"; }),
      marker: { size: 9, color: t.field, line: { color: t.surface, width: 2 } }, hovertemplate: "%{hovertext}<br>corners %{x:.2f}% · straights %{y:.2f}%<extra></extra>" }]);
    drv.forEach(function (x) {
      traces.push({ x: [x.r.corners], y: [x.r.straights], text: [x.d], type: "scatter", mode: "markers+text", textposition: "bottom right", textfont: { size: 11, color: t.ink2 }, name: fullName(x.d),
        marker: { size: 12, symbol: drvSymbol(x.d), color: drvColor(t, x.d), line: { color: t.surface, width: 1.5 } }, hovertemplate: fullName(x.d) + "<br>corners %{x:.2f}% · straights %{y:.2f}%<extra></extra>" });
    });
    plot("ch-det-rates", traces, layout(t, { showlegend: false, margin: { l: 56, r: 16, t: 20, b: 44 }, xaxis: { title: { text: "loss rate in corners, %" }, range: [lo, lim] },
      yaxis: { title: { text: "loss rate on straights, %" }, range: [lo, lim] }, annotations: g.notes }));
  }

  function renderCorners(t, e, D, ds) {
    var have = ds.filter(function (x) { return D.drivers[x]; });
    var x = D.corners.map(cornerName);
    if (!have.length) { $("tbl-corners").innerHTML = ""; return empty("ch-corners", noLapText(e, ds)); }
    plot("ch-corners", have.map(function (dv) {
      var cr = D.drivers[dv].corners;
      return { x: x, y: cr.map(function (c) { return c.total_s; }), name: fullName(dv), type: "bar", marker: { color: drvColor(t, dv) },
        customdata: cr.map(function (c) { return [c.entry_s, c.apex_s, c.exit_s]; }),
        hovertemplate: dv + " · %{x}<br>%{y:+.3f} s · braking %{customdata[0]:+.3f}, apex %{customdata[1]:+.3f}, exit %{customdata[2]:+.3f}<extra></extra>" };
    }), layout(t, { barmode: "group", bargap: 0.25, bargroupgap: 0.05, showlegend: have.length > 1, yaxis: { title: { text: "s lost to the reference" } }, xaxis: { tickangle: -45, type: "category" },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
    var na = '<span class="hint" title="the speed channel disagrees with GPS here">n/a</span>';
    $("tbl-corners").innerHTML = "<thead><tr><th>Corner</th><th>Class</th><th class=\"num\">Reference min</th><th class=\"num\">Other teams</th>" +
      have.map(function (dv) { return '<th class="num">' + dv + ' min speed Δ</th><th class="num">' + dv + " lost</th>"; }).join("") + "</tr></thead><tbody>" +
      D.corners.map(function (c, i) {
        return "<tr><td>" + esc(cornerName(c)) + '</td><td><span class="hint">' + c.speed_class + '</span></td><td class="num">' + (c.pole_ok ? f(c.pole_kmh, 0) : na) + '</td><td class="num">' + f(c.field_median_kmh, 0) + "</td>" +
          have.map(function (dv) {
            var r = D.drivers[dv].corners[i];
            return '<td class="num">' + (r.ok && c.field_median_kmh != null ? sgn(r.min_kmh - c.field_median_kmh, 1) : na) + '</td><td class="num">' + sgn(r.total_s, 3) + "</td>";
          }).join("") + "</tr>";
      }).join("") + "</tbody>";
  }

  function renderStraight(t, e, D, ds) {
    var st = D.straights || [];
    if (!st.length) { $("seg-straight").innerHTML = ""; $("straight-sub").textContent = ""; var none = "No straight here of " + f(D.straight_min_m, 0) + " m or more at full throttle in a straight line, clear of the timing line."; empty("ch-ftl", none); return empty("ch-straight", none); }
    if (state.straight >= st.length) state.straight = 0;
    seg("seg-straight", st.map(function (s, i) { return [i, s.name]; }), state.straight, function (v) { state.straight = +v; renderStraight(theme(), e, D, ds); });
    var s = st[state.straight], x = s.distance_m.map(function (v) { return v - s.start_m; });
    $("straight-sub").textContent = f(s.start_m, 0) + " to " + f(s.end_m, 0) + " m from the line, grey band = range of the other teams. Straights are full-throttle runs of at least " +
      f(D.straight_min_m, 0) + " m in a straight line, clear of the timing line";
    var traces = [];
    if (s.field_max_kmh) {
      traces.push({ x: x, y: s.field_max_kmh, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      traces.push({ x: x, y: s.field_min_kmh, type: "scatter", mode: "lines", fill: "tonexty", fillcolor: hexA(t.field, 0.3), line: { width: 0 }, name: "other teams, range", hoverinfo: "skip" });
      traces.push({ x: x, y: s.field_median_kmh, type: "scatter", mode: "lines", line: { color: t.muted, width: 1.2, dash: "dash" }, name: "other teams, median", hovertemplate: "median %{y:.0f} km/h<extra></extra>" });
    }
    traces.push({ x: x, y: s.pole_kmh, type: "scatter", mode: "lines", line: { color: t.ref, width: 1.5 }, name: e.reference.driver + " (reference)", hovertemplate: e.reference.driver + " %{y:.0f} km/h<extra></extra>" });
    ds.filter(function (d) { return s.drivers[d]; }).forEach(function (d) {
      traces.push({ x: x, y: s.drivers[d].speed_kmh, type: "scatter", mode: "lines", line: { color: drvColor(t, d), width: 2 }, name: d, hovertemplate: d + " %{y:.0f} km/h<extra></extra>" });
    });
    plot("ch-straight", traces, layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "m from the start of the straight" } }, yaxis: { title: { text: "km/h" } } }));

    // Full-throttle speed loss per straight: every other team as a grey dot, the drivers on top
    var names = st.map(function (q) { return q.name; }), ftl = [];
    ftl.push({ x: [].concat.apply([], st.map(function (q) { return Object.keys(q.teams).map(function () { return q.name; }); })), y: [].concat.apply([], st.map(function (q) { return Object.keys(q.teams).map(function (k) { return q.teams[k].full_throttle_loss_kmh; }); })),
      text: [].concat.apply([], st.map(function (q) { return Object.keys(q.teams); })), type: "scatter", mode: "markers", name: "other teams", marker: { size: 8, color: t.field, opacity: 0.8 },
      hovertemplate: "%{text}: %{y:.1f} km/h<extra>%{x}</extra>" });
    ds.forEach(function (d) {
      if (!st.some(function (q) { return q.drivers[d]; })) return;
      ftl.push({ x: names, y: st.map(function (q) { return q.drivers[d] ? q.drivers[d].full_throttle_loss_kmh : null; }), type: "scatter", mode: "markers", name: fullName(d),
        marker: { size: 12, symbol: drvSymbol(d), color: drvColor(t, d), line: { color: t.surface, width: 1.5 } }, hovertemplate: d + ": %{y:.1f} km/h<extra>%{x}</extra>" });
    });
    plot("ch-ftl", ftl, layout(t, { showlegend: true, yaxis: { title: { text: "km/h lost at full throttle" }, rangemode: "tozero" }, xaxis: { type: "category" } }));
  }

  function renderDetailRace(t, e, D, ds) {
    var fig = $("det-race-fig");
    if (!D.race_teams || !D.race_teams.length) { fig.hidden = true; return; }
    fig.hidden = false;
    var rows = D.race_teams.filter(function (r) { return r.team !== TARGET; }), traces = [];
    traces.push({ y: rows.map(function (r) { return r.team; }), x: rows.map(function (r) { return r.gap_s; }), type: "scatter", mode: "markers", name: "other teams",
      marker: { size: 9, color: t.field }, error_x: { type: "data", symmetric: false, array: rows.map(function (r) { return r.ci_hi - r.gap_s; }), arrayminus: rows.map(function (r) { return r.gap_s - r.ci_lo; }), color: t.field, thickness: 1, width: 0 },
      hovertemplate: "%{y}: +%{x:.2f} s per lap<extra></extra>" });
    ds.forEach(function (d) {
      var r = e.race && e.race.drivers[d]; if (!r) return;
      traces.push({ y: [fullName(d)], x: [r.gap_s], type: "scatter", mode: "markers", name: fullName(d), marker: { size: 11, symbol: drvSymbol(d), color: drvColor(t, d), line: { color: t.surface, width: 1.5 } },
        error_x: { type: "data", symmetric: false, array: [r.gap_hi - r.gap_s], arrayminus: [r.gap_s - r.gap_lo], color: drvColor(t, d), thickness: 1.2, width: 0 },
        hovertemplate: fullName(d) + ": +%{x:.2f} s per lap · " + r.n_laps + " laps" + (r.single_stint ? " · one stint: interval too narrow" : "") + "<extra></extra>" });
    });
    var cats = rows.map(function (r) { return { y: r.team, v: r.gap_s }; }).concat(ds.filter(function (d) { return e.race && e.race.drivers[d]; }).map(function (d) { return { y: fullName(d), v: e.race.drivers[d].gap_s }; }))
      .sort(function (a, b) { return a.v - b.v; }).map(function (c) { return c.y; });
    var h = Math.max(260, 22 * cats.length + 70);
    $("ch-det-race").style.height = h + "px";
    plot("ch-det-race", traces, layout(t, { height: h, margin: { l: 130, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "s per lap behind the fastest team" } },
      yaxis: { type: "category", categoryorder: "array", categoryarray: cats, autorange: "reversed" } }));
  }

  function detailNotes(e, D, ds) {
    var n = [];
    if (e.reference.driver !== e.fastest_lap.driver) n.push("The reference lap is " + esc(e.reference.driver) + "'s " + lapTime(e.reference.lap_time_s) + ": the fastest lap (" + esc(e.fastest_lap.driver) + "'s) has no telemetry that passes the data checks. Lap-time gaps use the fastest lap; section and corner times use the reference lap.");
    if (e.wet) n.push("Wet qualifying: kept here, left out of the season analyses.");
    (D.flagged_corners || []).filter(function (c) { return ds.indexOf(c.driver) >= 0; }).forEach(function (c) {
      // Differences are taken between the rounded readings, so the printed numbers add up
      function r1(x) { return Math.round(10 * x) / 10; }
      var w = r1(c.wheel_kmh), g = r1(c.gps_kmh), fo = r1(c.field_offset_kmh);
      n.push(esc(c.driver) + " at " + esc(c.corner + (c.name ? " " + c.name : "")) + ": the speed channel reads " + f(w, 1) + " km/h and GPS " + f(g, 1) + " km/h (" + sgn(w - g, 1) +
        " km/h), against " + sgn(fo, 1) + " km/h for the median car at that corner, so the reading is " + f(Math.abs(w - g - fo), 1) + " km/h out of line with the other cars' and that minimum speed is not used.");
    });
    if (!e.race && e.race_note) n.push("Race pace: " + esc(e.race_note) + ".");
    $("det-notes").innerHTML = n.map(function (x) { return "<li>" + x + "</li>"; }).join("");
  }

  function renderDetail(t) {
    t = t || theme();
    var e = current.entry, D = current.detail, ds = selDrivers();
    var ids = ["ch-order", "ch-rival", "ch-speed", "ch-delta", "ch-map", "ch-det-rates", "ch-corners", "ch-straight", "ch-ftl", "ch-det-race"];
    if (!e || !D || D.key !== e.key) {
      var why = !e ? "Pick at least one track in the bar at the top." : (current.failed || []).indexOf("track") >= 0 ? "Could not load this track's data file." : "Loading…";
      fill("detail_text", esc(why)); $("det-tiles").innerHTML = ""; $("det-notes").innerHTML = ""; $("tbl-corners").innerHTML = "";
      ["rival-sub", "speed-sub", "map-sub", "straight-sub", "trk-hint"].forEach(function (id) { $(id).textContent = ""; });
      ["seg-map", "seg-straight"].forEach(function (id) { $(id).innerHTML = ""; $(id).onclick = null; });
      $("det-race-fig").hidden = true;
      ids.forEach(function (id) { empty(id, why); });
      return;
    }
    $("trk-hint").textContent = e.wet ? "wet session" : "";
    detailText(e, D, ds); detailTiles(e, D, ds);
    renderOrder(t, e, D); renderRival(t, e, D, ds); renderSpeed(t, e, D, ds); renderMap(t, e, D, ds);
    renderDetailRates(t, e, D, ds); renderCorners(t, e, D, ds); renderStraight(t, e, D, ds); renderDetailRace(t, e, D, ds);
    detailNotes(e, D, ds);
  }

  // Upgrades (season filter; the difference-in-differences table covers both seasons)
  function upgradeEvents(season) {
    return ((S.upgrades || {}).declared || []).filter(function (u) { return u.season === season && (u.major_performance_upgrade === "major" || u.major_performance_upgrade === "partial"); });
  }
  function renderUpgradeParts(t) {
    t = t || theme();
    var y = state.season, season = +y;
    var series = (S.amr_component_series || {})[y] || [];
    var comp = upgradeComponent(season);
    fill("season_upg_sub", y + " · ratio · upgrade events marked");
    fill("season_kmh_sub", y + " · km/h");
    var loo = {}; ((comp || {}).grip_high_rel || { per_event: [] }).per_event.forEach(function (r) { loo[r.round] = r; });
    var gs = series.filter(function (r) { return loo[r.round]; });
    plot("ch-season-grip", [{ x: gs.map(function (r) { return short(r.event); }), y: gs.map(function (r) { return loo[r.round].ratio; }), type: "scatter", mode: "lines+markers",
      error_y: { type: "data", array: gs.map(function (r) { return MTH.interval_z * loo[r.round].se; }), color: t.amr, thickness: 1, width: 0 },
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.3f} of the other teams' median<extra></extra>", connectgaps: false }],
      layout(t, { yaxis: { title: { text: "ratio to other teams' median" }, tickformat: ".2f" }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, gs, season).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, season) }));
    plot("ch-season-speed", [{ x: series.map(function (r) { return short(r.event); }), y: series.map(function (r) { return r.straight_speed_delta_kmh; }), type: "scatter", mode: "lines+markers",
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.1f} km/h<extra></extra>", connectgaps: false }],
      layout(t, { yaxis: { title: { text: "km/h against the field median" } }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, series, season).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, season) }));
    upgradeText();
  }
  function upgradeShapes(t, series, season) {
    var names = series.map(function (r) { return r.event; });
    return upgradeEvents(season).filter(function (u) { return names.indexOf(u.grand_prix) >= 0; }).map(function (u) {
      return { type: "line", x0: short(u.grand_prix), x1: short(u.grand_prix), yref: "paper", y0: 0, y1: 1, line: { color: u.major_performance_upgrade === "major" ? t.ink2 : t.muted, width: 1, dash: u.major_performance_upgrade === "major" ? "solid" : "dot" } };
    });
  }
  function upgradeNotes(t, series, season) {
    var names = series.map(function (r) { return r.event; });
    return upgradeEvents(season).filter(function (u) { return names.indexOf(u.grand_prix) >= 0 && u.major_performance_upgrade === "major"; }).map(function (u) {
      return { x: short(u.grand_prix), yref: "paper", y: 1, yanchor: "bottom", text: "upgrade", showarrow: false, font: { size: 10, color: t.muted } };
    });
  }

  function renderGap(t) {
    t = t || theme();
    var season = Number(state.season);
    var rows = (S.supertimes || []).filter(function (r) { return r.season === season; });
    var byRound = byKey(rows, "round");
    var rounds = Object.keys(byRound).map(Number).sort(function (a, b) { return a - b; });
    var x = rounds.map(function (r) { return short(byRound[r][0].event); });
    function q(arr, p) { arr = arr.slice().sort(function (a, b) { return a - b; }); var i = (arr.length - 1) * p, lo = Math.floor(i); return arr[lo] + (arr[Math.ceil(i)] - arr[lo]) * (i - lo); }
    var lo = rounds.map(function (r) { return q(byRound[r].map(function (x) { return x.gap_pct; }), 0.25); });
    var hi = rounds.map(function (r) { return q(byRound[r].map(function (x) { return x.gap_pct; }), 0.75); });
    var amr = rounds.map(function (r) { var a = byRound[r].filter(function (x) { return x.team === TARGET; })[0]; return a ? a.gap_pct : null; });
    var series = rounds.map(function (r) { return { event: byRound[r][0].event }; });
    plot("ch-gap", [
      { x: x, y: hi, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: x, y: lo, type: "scatter", mode: "lines", fill: "tonexty", fillcolor: hexA(t.field, 0.25), line: { width: 0 }, hoverinfo: "skip" },
      { x: x, y: amr, type: "scatter", mode: "lines+markers", name: TARGET, line: { color: t.amr, width: 2 }, marker: { size: 8, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>Aston Martin %{y:.2f}%<extra></extra>" },
    ], layout(t, { yaxis: { title: { text: "% slower than fastest lap" }, rangemode: "tozero" }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, series, season), annotations: upgradeNotes(t, series, season) }));
  }

  function renderCP(t) {
    t = t || theme();
    var cp = (S.changepoints || {})[state.season] || {};
    var ev = (cp.events || []).map(short);
    plot("ch-cp", [{ x: ev, y: cp.posterior_tau || [], type: "bar", marker: { color: (cp.events || []).map(function (e) { return e === cp.map_event ? t.amr : t.field; }) },
      hovertemplate: "%{x}<br>P(change here) = %{y:.2f}<extra></extra>" }],
      layout(t, { bargap: 0.3, yaxis: { title: { text: "posterior probability" }, range: [0, 1] }, xaxis: { tickangle: -40 },
        annotations: [{ xref: "paper", yref: "paper", x: 0, y: 1, xanchor: "left", yanchor: "top", showarrow: false, font: { size: 11, color: t.muted },
          text: "P(no change all season) = " + f(cp.p_no_change, 2) }] }));
  }

  function renderDiD() {
    var up = S.upgrades || {}, eff = up.effects || [];
    var rows = eff.map(function (e) {
      var detectable = e.mde_pct != null && Math.abs(e.effect_pct) >= e.mde_pct;
      var ref = e.lead_test === "time" ? "own other dates" : "rivals";
      return "<tr><td>" + e.season + " " + esc(short(e.event)) + '</td><td class="num">' + sgn(e.effect_pct, 2) + '%</td><td class="num">' + (e.mde_pct == null ? "not reachable" : f(e.mde_pct, 2) + "%") +
        '</td><td class="num">' + e.n_pre + " / " + e.n_post + '</td><td class="num">' + f(e.team_placebo_p, 2) + '</td><td class="num">' + f(e.time_placebo_p, 2) + "</td><td>" + ref +
        ' <span class="hint">(noise ×' + f(e.noise_ratio, 1) + ')</span></td><td class="num">' + f(e.lead_p_holm, 2) + "</td><td>" +
        '<span class="pill ' + (verdict(e) === "clear after correction" ? "yes" : "no") + '">' + verdict(e) + "</span>" + (e.overlapping && e.overlapping.length ? ' <span class="hint">overlaps ' + e.overlapping.map(short).join(", ") + "</span>" : "") +
        (detectable ? "" : ' <span class="hint">below detectable size</span>') + "</td></tr>";
    });
    var floors = [].concat.apply([], eff.map(function (e) { return [1 / (1 + e.n_team_placebos), 1 / (1 + e.n_time_placebos)]; })).filter(isFinite);
    $("tbl-did").innerHTML = "<caption>Declared upgrades, both seasons: difference-in-differences, " + (eff.length ? count(eff[0].n_pre) : "–") + " events either side. A placebo p can't go below 1 / (1 + number of placebos), " +
      f(Math.min.apply(null, floors), 2) + " to " + f(Math.max.apply(null, floors), 2) + " here.</caption>" +
      '<thead><tr><th>Upgrade</th><th class="num">Effect on gap</th><th class="num">Detectable</th><th class="num">Events pre / post</th><th class="num">p against rivals</th><th class="num">p against own dates</th><th>Reference used</th><th class="num">Holm-adjusted</th><th>Verdict</th></tr></thead><tbody>' +
      rows.join("") + '</tbody><tfoot><tr><td colspan="9">Each upgrade is compared with rivals given the same date (team placebos) and with Aston Martin at its other dates (time placebos). When Aston Martin\'s own estimates are much noisier than its rivals\' (noise ratio above ' +
      f(MTH.did_noise_ratio_max, 1) + "), only the second is a fair reference. Detectable means the effect the reference test finds with " + pct(MTH.did_power) + " power at the " + pct(MTH.did_alpha) + " level. With " +
      eff.length + " upgrades tested, the smallest Holm-adjusted p any of them could reach is " + f(up.holm_floor_lead, 2) + (up.holm_floor_lead > MTH.did_alpha ? ", so none can be called significant after correction, whatever its size." : ".") + "</td></tr></tfoot>";
  }

  // Aero map from the linear surrogate (season filter) and circuit sensitivities (both seasons)
  function renderAero(t) {
    t = t || theme();
    var am = (S.aero_map || {})[state.season] || {};
    var teams = am.teams || [];
    var sens = am.season_sensitivity || {};
    var xs = teams.map(function (r) { return r.d_cla_equiv_pct[0]; }), ys = teams.map(function (r) { return r.d_cda_equiv_pct[0]; });
    var lim = Math.max(10, Math.ceil(Math.max.apply(null, xs.concat(ys).map(Math.abs).filter(isFinite)) / 5) * 5 + 5);
    var lines = [];
    if (sens.cla_plus_1pct_s && sens.cda_plus_1pct_s) {
      [-2, -1, 0, 1, 2].forEach(function (dt) {
        // Lines of equal lap-time change: dt = s_cla * x + s_cda * y, so y = (dt - s_cla * x) / s_cda
        var x = [-lim, lim], y = x.map(function (v) { return (dt - sens.cla_plus_1pct_s * v) / sens.cda_plus_1pct_s; });
        lines.push({ x: x, y: y, type: "scatter", mode: "lines", line: { color: t.rule, width: 1, dash: dt === 0 ? "solid" : "dot" }, hoverinfo: "skip" });
        var lx = -lim * 0.9, ly = (dt - sens.cla_plus_1pct_s * lx) / sens.cda_plus_1pct_s;
        if (Math.abs(ly) < lim) lines.push({ x: [lx], y: [ly], type: "scatter", mode: "text", text: [(dt > 0 ? "+" : "") + dt + " s"], textfont: { size: 10, color: t.muted }, hoverinfo: "skip" });
      });
    }
    // Direct labels only for the target and clear outliers; the rest are named on hover
    var labelled = teams.map(function (r) { return r.team === TARGET || Math.abs(r.d_cla_equiv_pct[0]) > 8 || Math.abs(r.d_cda_equiv_pct[0]) > 3; });
    var pts = { x: xs, y: ys, text: teams.map(function (r, i) { return labelled[i] ? r.team : ""; }), hovertext: teams.map(function (r) { return r.team; }),
      type: "scatter", mode: "markers+text", textposition: "top right",
      textfont: { size: 11, color: t.ink2 },
      marker: { size: teams.map(function (r) { return r.team === TARGET ? 13 : 9; }), color: teams.map(function (r) { return r.team === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: teams.map(function (r) { return r.d_cla_equiv_pct[2] - r.d_cla_equiv_pct[0]; }), arrayminus: teams.map(function (r) { return r.d_cla_equiv_pct[0] - r.d_cla_equiv_pct[1]; }), color: t.field, thickness: 1, width: 0 },
      error_y: { type: "data", symmetric: false, array: teams.map(function (r) { return r.d_cda_equiv_pct[2] - r.d_cda_equiv_pct[0]; }), arrayminus: teams.map(function (r) { return r.d_cda_equiv_pct[0] - r.d_cda_equiv_pct[1]; }), color: t.field, thickness: 1, width: 0 },
      customdata: teams.map(function (r) { return [r.n_events, r.mean_gap_pct]; }),
      hovertemplate: "%{hovertext}<br>downforce-equivalent %{x:.1f}%<br>drag-equivalent %{y:.1f}%<br>%{customdata[0]} events, mean qualifying gap %{customdata[1]:.2f}%<extra></extra>" };
    plot("ch-aero", lines.concat([pts]), layout(t, {
      xaxis: { title: { text: "downforce-equivalent against the field, % (→ more)" }, range: [-lim, lim] },
      yaxis: { title: { text: "drag-equivalent against the field, % (↑ more drag, less speed)" }, range: [-lim / 2, lim / 2] },
      annotations: [{ xref: "paper", yref: "paper", x: 1, y: 0, xanchor: "right", yanchor: "bottom", showarrow: false, font: { size: 11, color: t.muted },
        text: "1% C<sub>L</sub>A = " + sgn(sens.cla_plus_1pct_s, 3) + " s, 1% C<sub>D</sub>A = " + sgn(sens.cda_plus_1pct_s, 3) + " s" }] }));
    var amr = teams.filter(function (r) { return r.team === TARGET; })[0];
    fill("aero_text", amr ? "Before the emulator there was a linear surrogate: the simulator run with each input nudged by 1%, giving the cost of 1% more downforce or drag at each track. It draws the lines of equal lap time on this aero map. High-speed cornering grip is turned into a downforce-equivalent using each event's aero share of grip, and straight-line peak speed into a drag-equivalent (v ∝ C<sub>D</sub>A<sup>−1/3</sup>). In " + state.season +
      " Aston Martin sits at " + sgn(amr.d_cla_equiv_pct[0], 1) + "% downforce-equivalent and " + sgn(amr.d_cda_equiv_pct[0], 1) +
      "% drag-equivalent against the field median. The drag axis mixes drag with power, so read it alongside the power analysis in the evidence. Averaged over " + sens.n_events + " events" + (function () {
        // Each event's sensitivities come from the car calibrated there: Aston Martin's, or the pole
        // car's where no Aston Martin lap passed
        var drv = XI.drivers[state.season] || [], cs = (S.circuit_sensitivities || []).filter(function (r) { return String(r.season) === String(state.season); });
        var nA = cs.filter(function (r) { return drv.indexOf(r.car) >= 0; }).length;
        return nA < cs.length ? " (Aston Martin's calibrated car at " + nA + ", and the pole car at the other " + (cs.length - nA) + ", where no Aston Martin lap passed the data checks)" : "";
      })() + ", 1% more downforce is worth " + sgn(sens.cla_plus_1pct_s, 3) +
      " s a lap and 1% more drag costs " + sgn(sens.cda_plus_1pct_s, 3) + " s. The linear version only holds for small changes, which is why the emulator above was built." : "");
  }

  function renderSens(t) {
    t = t || theme();
    var rows = (S.circuit_sensitivities || []).slice().sort(function (a, b) { return a.cda_pct_per_cla_pct - b.cda_pct_per_cla_pct; });
    var x = rows.map(function (r) { return short(r.event) + " " + String(r.season).slice(2); });
    plot("ch-sens", [
      { x: x, y: rows.map(function (r) { return r.cla_m2_plus_1pct_s; }), name: "+1% downforce", type: "bar", marker: { color: t.ink2 }, hovertemplate: "%{x}<br>+1% C<sub>L</sub>A: %{y:+.3f} s<extra></extra>" },
      { x: x, y: rows.map(function (r) { return r.cda_m2_plus_1pct_s; }), name: "+1% drag", type: "bar", marker: { color: t.field }, hovertemplate: "%{x}<br>+1% C<sub>D</sub>A: %{y:+.3f} s<extra></extra>" },
    ], layout(t, { barmode: "group", bargap: 0.25, bargroupgap: 0.08, showlegend: true, yaxis: { title: { text: "lap-time change, s" } }, xaxis: { tickangle: -50 } }));
  }

  // Lap simulator, calibration and discrepancy (focus track); renderCalAcc covers every event
  function lapDataMissing() {
    return !current.entry ? "Pick a track in Track detail." : (current.failed || []).indexOf("lap") >= 0 ? "Could not load this track's lap data." : "Loading…";
  }
  function focusName(e) { return (current.entry ? trk(current.entry) : short(e.event)) + " " + e.season; }
  function renderSim(t) {
    t = t || theme();
    var e = current.event;
    var key = e && e.sandbox ? e.sandbox.car : null;
    var ls = key && e.lapsim ? e.lapsim[key] : null;
    if (!ls) {
      $("sim-sub").textContent = !e ? "" : focusName(e) + ": no calibration for this event (geometry check failed)";
      ["ch-sim", "ch-disc"].forEach(function (id) { empty(id, e ? "No calibrated lap for this track." : lapDataMissing()); });
      ["tbl-params", "sim-dl", "disc-dl"].forEach(function (id) { $(id).innerHTML = ""; });
      fill("sim_note", ""); fill("disc_sub", ""); fill("cal_text", e ? "No calibrated lap for this track, so there is no fit to describe here." : "");
      $("sandbox").hidden = true; SB.base = null;
      return;
    }
    var where = focusName(e), d = e.map.distance_m.slice(0, ls.trace.observed_kmh.length), sens = ls.sensitivities || {};
    var N = (e.sandbox.distance_m || []).length, ne = ls.n_effective;
    $("sim-sub").textContent = where + ", " + ls.driver + ", RMS speed error " + f(ls.rmse_kmh, 1) + " km/h, lap-time error " + sgn(ls.lap_time_error_s, 3) + " s";
    plot("ch-sim", [
      { x: d, y: ls.trace.observed_kmh, name: "measured", type: "scatter", mode: "lines", line: { color: t.amr, width: 1.6 } },
      { x: d, y: ls.trace.sim_kmh, name: "simulated", type: "scatter", mode: "lines", line: { color: t.ink2, width: 1.2, dash: "dot" } },
    ], layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } } }));
    $("sim-dl").innerHTML = dl([["+1% downforce", sgn(sens.cla_m2_plus_1pct_s, 3) + " s a lap"], ["+1% drag", sgn(sens.cda_m2_plus_1pct_s, 3) + " s"], ["+10 kg", sgn(sens.mass_plus_10kg_s, 3) + " s"]]);
    fill("sim_note", esc(where) + ", " + esc(fullName(ls.driver)) + "'s lap, from the calibrated simulator. A JavaScript copy of the simulator runs in this page, and a test checks it against the Python version.");
    // The set-up sandbox starts from the car the simulator was calibrated to here: Aston Martin's,
    // or the pole car's where no Aston Martin lap passed
    var amrCar = ls.team === TARGET;
    fill("sb_hint", "Runs the same simulator in your browser on this circuit, starting from the calibrated car: " + (amrCar ? "Aston Martin's (" + esc(fullName(ls.driver)) + ")"
      : esc(fullName(ls.driver)) + "'s " + esc(ls.team) + ", the pole lap, because no Aston Martin lap passed the data checks here") + ".");
    fill("cal_text", "I fit those numbers to the pole lap and to Aston Martin's best lap at each event, with weak priors, and take the uncertainty from a Laplace approximation. On the Aston Martin lap a Metropolis sampler checks it" +
      (ls.mcmc_check ? ": the table compares the two widths and shows how far the sampler's mean sits from the fitted value." : "; this track has no Aston Martin calibration, so the table below has no such check.") + " The errors along a lap come in long runs (lag-1 correlation " + f(ls.lag1_autocorr, 2) + " at " + esc(where) + "), so " +
      N.toLocaleString("en-GB") + " speed points carry about as much information as " + f(ne, 0) + " independent ones. Treating them as independent would make the intervals up to about " + f(Math.sqrt(N / ne), 0) + " times too narrow: that's the factor for the data alone, before the priors hold some parameters back.");

    var m = ls.trace.disc_mean_kmh, sd = ls.trace.disc_sd_kmh;
    fill("disc_sub", "Gaussian-process mean ± " + DISC_K + " sd, km/h, " + esc(where));
    $("disc-dl").innerHTML = dl([["Correlation length, " + esc(where), f(ls.discrepancy_length_scale_m, 0) + " m"], ["Error left after calibration", f(ls.rmse_kmh, 1) + " km/h RMS"]]);
    plot("ch-disc", [
      { x: d, y: m.map(function (v, i) { return v + DISC_K * sd[i]; }), type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: d, y: m.map(function (v, i) { return v - DISC_K * sd[i]; }), type: "scatter", mode: "lines", fill: "tonexty", fillcolor: hexA(t.field, 0.3), line: { width: 0 }, hoverinfo: "skip" },
      { x: d, y: m, type: "scatter", mode: "lines", line: { color: t.ink2, width: 1.6 }, hovertemplate: "%{x:.0f} m: %{y:+.1f} km/h<extra></extra>" },
    ], layout(t, { hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h, measured minus simulated" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));

    var names = { mu: ["Grip coefficient μ", 1, ""], cla_m2: ["Downforce C<sub>L</sub>A", 1, " m²"], cda_m2: ["Drag C<sub>D</sub>A", 1, " m²"], power_w: ["Wheel power", 1e-3, " kW"],
      long_grip_scale: ["Braking and traction grip ratio", 1, ""], low_drag_cda_m2: ["Drag with DRS open", 1, " m²"] };
    var mc = ls.mcmc_check, prior = MTH.calibration_prior_sd_log || {};
    var rows = ls.param_names.map(function (n, i) {
      var p = ls.params[n], nm = names[n] || [n, 1, ""];
      var dig = n === "power_w" ? 0 : 2;
      var postSd = (Math.log(p.hi) - Math.log(p.lo)) / (2 * MTH.interval_z);
      return "<tr><td>" + nm[0] + '</td><td class="num">' + f(p.median * nm[1], dig) + nm[2] + '</td><td class="num">' + f(p.lo * nm[1], dig) + " to " + f(p.hi * nm[1], dig) + '</td><td class="num">' + f(postSd / prior[n], 2) + "</td>" +
        (mc ? '<td class="num">' + f(mc.laplace_sd_log[i], 2) + " / " + f(mc.mcmc_sd_log[i], 2) + '</td><td class="num">' + sgn((mc.mcmc_minus_map_log || [])[i], 2) + "</td>" : "") + "</tr>";
    });
    $("tbl-params").innerHTML = "<caption>Calibrated parameters, " + esc(fullName(ls.driver)) + " at " + esc(where) + ", effective sample size " + f(ne, 0) + " of " + N.toLocaleString("en-GB") + " points</caption>" +
      '<thead><tr><th>Parameter</th><th class="num">Median</th><th class="num">' + LVL + ' interval</th><th class="num">Posterior / prior width</th>' + (mc ? '<th class="num">log-sd Laplace / MCMC</th><th class="num">MCMC mean minus fitted, log</th>' : "") + "</tr></thead><tbody>" + rows.join("") +
      '</tbody><tfoot><tr><td colspan="' + (mc ? 6 : 4) + '">Widths near 1 mean the lap barely constrains that parameter beyond the prior. Residuals are strongly autocorrelated (effective sample size ' + f(ne, 0) + "), so these are effective, prior-informed values. The sensitivities downstream use the medians.</td></tr></tfoot>";
    sandboxInit(e);
  }

  function renderCalAcc(t) {
    t = t || theme();
    var rows = (S.calibration_accuracy || []).filter(function (r) { return r.is_pole; });
    var by = byKey(rows, "season");
    // Reference laps belong to whichever team was fastest, so they are grey: the latest season in the stronger shade
    plot("ch-calacc", Object.keys(by).sort().map(function (season) {
      var r = by[season], c = season === Y ? t.ink2 : t.field;
      return { x: r.map(function (x) { return short(x.event); }), y: r.map(function (x) { return x.lap_time_error_s; }), name: season, type: "scatter", mode: "markers",
        marker: { size: 9, symbol: season === Y ? "circle" : "diamond", color: c, line: { color: t.surface, width: 2 } },
        error_y: { type: "data", array: r.map(function (x) { return MTH.interval_z * x.posterior_lap_time_sd_s; }), color: c, thickness: 1, width: 0 },
        customdata: r.map(function (x) { return [x.driver, x.rmse_kmh]; }), hovertemplate: season + " %{x}<br>%{customdata[0]}: %{y:+.3f} s, RMS speed error %{customdata[1]:.1f} km/h<extra></extra>" };
    }), layout(t, { showlegend: true, yaxis: { title: { text: "simulated minus actual lap, s" } }, xaxis: { tickangle: -50 },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
    function med(season, k) { return median((by[season] || []).map(function (x) { return Math.abs(x[k]); })); }
    var ePrev = med(Y0, "lap_time_error_s"), eLast = med(Y, "lap_time_error_s"), rPrev = med(Y0, "rmse_kmh"), rLast = med(Y, "rmse_kmh");
    $("cal-dl").innerHTML = dl([["Median RMS speed error, " + Y0 + " reference laps", f(rPrev, 1) + " km/h"], ["Median RMS speed error, " + Y + " reference laps", f(rLast, 1) + " km/h"]]);
    fill("calacc_text", "Reference laps (the fastest lap with clean data) at every event with clean geometry. The median size of the lap-time error is " + f(ePrev, 2) + " s in " + Y0 + " and " + f(eLast, 2) + " s in " + Y + "." +
      (rLast > rPrev ? " The " + Y + " fits are weaker, consistent with power that falls with time along a straight (energy deployment), which a constant-power point-mass model can't represent. The discrepancy model below shows where the fit misses." : ""));
  }

  // Set-up sandbox
  var SB = { base: null, t0: null };
  function sandboxParams(e) {
    var p = Object.assign({}, e.sandbox.params);
    return { p: p, d: Float64Array.from(e.sandbox.distance_m), k: Float64Array.from(e.sandbox.curvature), mask: e.sandbox.low_drag_mask ? e.sandbox.low_drag_mask.map(Boolean) : null, L: e.sandbox.lap_length_m };
  }
  function sandboxInit(e) {
    if (!e.sandbox || !window.LapSim) { $("sandbox").hidden = true; return; }
    $("sandbox").hidden = false;
    SB.base = sandboxParams(e);
    SB.t0 = LapSim.simulateLap(SB.base.d, SB.base.k, SB.base.p, SB.base.mask, SB.base.L).lapTime;
    sandboxRun();
  }
  function sandboxRun() {
    if (!SB.base) return;
    var cla = +$("s-cla").value, cda = +$("s-cda").value, pw = +$("s-pow").value, ms = +$("s-mass").value;
    $("o-cla").textContent = sgn(cla, 1).replace("–", "0") + "%"; $("o-cda").textContent = sgn(cda, 1).replace("–", "0") + "%";
    $("o-pow").textContent = sgn(pw, 0).replace("–", "0") + " kW"; $("o-mass").textContent = sgn(ms, 0).replace("–", "0") + " kg";
    var p = Object.assign({}, SB.base.p);
    p.cla_m2 *= 1 + cla / 100; p.cda_m2 *= 1 + cda / 100; if (p.low_drag_cda_m2 != null) p.low_drag_cda_m2 *= 1 + cda / 100;
    p.power_w += pw * 1000; p.mass_kg += ms;
    var t1 = LapSim.simulateLap(SB.base.d, SB.base.k, p, SB.base.mask, SB.base.L).lapTime;
    $("sb-time").textContent = f(t1, 3) + " s";
    var dt = t1 - SB.t0;
    $("sb-delta").textContent = Math.abs(dt) < 0.0005 ? "baseline (simulated)" : sgn(dt, 3) + " s against the baseline";
  }
  ["s-cla", "s-cda", "s-pow", "s-mass"].forEach(function (id) { var el = $(id); if (el) el.addEventListener("input", sandboxRun); });
  if ($("sb-reset")) $("sb-reset").addEventListener("click", function () { ["s-cla", "s-cda", "s-pow", "s-mass"].forEach(function (id) { $(id).value = 0; }); sandboxRun(); });

  // Surrogate: a Gaussian-process emulator of the simulator (focus track)
  var SURR_NAMES = { mu: "grip μ", cla_m2: "downforce C<sub>L</sub>A", cda_m2: "drag C<sub>D</sub>A", power_w: "power" };
  function pname(k) { return SURR_NAMES[k] || k; }
  function renderSurrogate(t) {
    t = t || theme();
    var e = current.event, g = e && e.surrogate;
    if (!g || !g.test_sim_s) {
      var why = !e ? lapDataMissing() : "No emulator for this track.";
      ["ch-surr", "ch-sobol"].forEach(function (id) { empty(id, why); });
      fill("surr_text", e ? "No emulator was fitted at this track." : ""); $("surr-dl").innerHTML = ""; $("surr-sub").textContent = ""; $("sobol-sub").textContent = "";
      return;
    }
    var where = focusName(e), params = g.params || Object.keys(g.sobol_first || {});
    fill("surr_text", "The 1% sensitivities describe small changes, one at a time. For bigger changes made together, I fitted a Gaussian-process emulator to " + g.n_train + " simulator runs at " + esc(where) + ", with " +
      list(params.map(pname)) + " each varied by up to ±" + pct(g.half_range) + " at once. On " + g.n_test + " runs it hadn't seen, its typical error is " + f(g.rmse_s, 3) + " s, against " + f(g.linear_rmse_s, 3) + " s for the linear surrogate built from the 1% sensitivities. It stands in for the simulator, not for the car. " +
      "The Sobol indices below split the lap-time variance over that box between the inputs; they follow from giving every input the same range, not from what a development step could achieve.");
    $("surr-dl").innerHTML = dl([["Held-out error, emulator", f(g.rmse_s, 3) + " s RMS"], ["Held-out error, linear", f(g.linear_rmse_s, 3) + " s RMS"], ["Held-out runs inside the 90% band", pct(g.coverage90)]]);
    $("surr-sub").textContent = where + ", " + g.n_test + " held-out runs, s";
    var x = g.test_sim_s, y = g.test_gp_s, sd = g.test_gp_sd_s || [], lin = g.test_linear_s || [];
    var all = x.concat(y, lin).filter(isFinite), lo = Math.min.apply(null, all), hi = Math.max.apply(null, all), pad = 0.04 * (hi - lo);
    plot("ch-surr", [
      { x: [lo - pad, hi + pad], y: [lo - pad, hi + pad], type: "scatter", mode: "lines", line: { color: t.muted, width: 1 }, hoverinfo: "skip", showlegend: false },
      { x: x, y: lin, name: "linear surrogate", type: "scatter", mode: "markers", marker: { size: 7, symbol: "circle-open", color: t.field, line: { width: 1.5, color: t.field } },
        hovertemplate: "simulator %{x:+.3f} s<br>linear %{y:+.3f} s<extra></extra>" },
      { x: x, y: y, name: "emulator, 90% band", type: "scatter", mode: "markers", marker: { size: 7, color: t.ink2, line: { color: t.surface, width: 1 } },
        error_y: { type: "data", array: sd.map(function (v) { return MTH.interval_z * v; }), color: t.ink2, thickness: 1, width: 0 },
        hovertemplate: "simulator %{x:+.3f} s<br>emulator %{y:+.3f} s<extra></extra>" },
    ], layout(t, { showlegend: true, xaxis: { title: { text: "lap-time change from the simulator, s" }, range: [lo - pad, hi + pad] },
      yaxis: { title: { text: "predicted change, s" }, range: [lo - pad, hi + pad] } }));
    var sob = g.sobol_first || {}, ks = params.slice().sort(function (a, b) { return sob[a] - sob[b]; });
    $("sobol-sub").textContent = where + ", over the ±" + pct(g.half_range) + " box";
    plot("ch-sobol", [{ y: ks.map(pname), x: ks.map(function (k) { return sob[k]; }), type: "bar", orientation: "h", marker: { color: t.ink2 },
      text: ks.map(function (k) { return pct(sob[k]); }), textposition: "outside", textfont: { size: 11, color: t.ink2 }, cliponaxis: false, hovertemplate: "%{y}: %{x:.3f}<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 140, r: 48, t: 8, b: 44 }, xaxis: { title: { text: "first-order Sobol index: share of lap-time variance" }, range: [0, 1] }, yaxis: { type: "category" } }));
  }
  // Every track of the season: emulator against linear, and the note under the module
  function renderSurrogateEvents(t) {
    t = t || theme();
    var y = state.season, ss = (S.surrogate_summary || {})[y], rows = (ss && ss.events) || [];
    var cv = (ss || {}).coverage90_mean_ci90 || [];
    fill("surr_note", ss ? "Across the " + ss.n_events + " tracks of " + y + " the emulator's median held-out error is " + f(ss.rmse_s, 3) + " s, against " + f(ss.linear_rmse_s, 3) + " s for the linear surrogate, and it is the more accurate of the two at " +
      (ss.n_gp_rmse_below_linear === ss.n_events ? "every one of them" : ss.n_gp_rmse_below_linear + " of them") + ". Its 90% bands hold " + pct(ss.coverage90_mean) + " of held-out runs on average (" + LVL + " interval " + pct(cv[0]) + " to " + pct(cv[1]) + ")" +
      (cv[1] < 0.9 ? ", so they are a little too narrow" : cv[0] > 0.9 ? ", so they are a little too wide" : ", in line with what they claim") +
      ". It isn't there to save time, since the simulator itself is quick. What it adds is a smooth response with its own uncertainty, and variance-based sensitivity indices that a one-at-a-time nudge can't give." : "");
    if (!rows.length) { fill("surr_ev_sub", ""); return empty("ch-surr-ev", "No emulator results for " + y + "."); }
    fill("surr_ev_sub", y + ", RMS error on held-out runs, s (log scale)");
    var x = rows.map(function (r) { return short(r.event); });
    plot("ch-surr-ev", [
      { x: x, y: rows.map(function (r) { return r.linear_rmse_s; }), name: "linear surrogate", type: "scatter", mode: "markers", marker: { size: 8, symbol: "circle-open", color: t.field, line: { width: 1.5, color: t.field } },
        hovertemplate: "%{x}<br>linear %{y:.3f} s<extra></extra>" },
      { x: x, y: rows.map(function (r) { return r.rmse_s; }), name: "emulator", type: "scatter", mode: "markers", marker: { size: 8, color: t.ink2, line: { color: t.surface, width: 1 } },
        hovertemplate: "%{x}<br>emulator %{y:.3f} s<extra></extra>" },
    ], layout(t, { showlegend: true, yaxis: { title: { text: "s" }, type: "log", dtick: 1, exponentformat: "none" }, xaxis: { tickangle: -45, type: "category" } }));
  }

  // Reduced-order model: POD of the speed traces (focus track)
  function renderPOD(t) {
    t = t || theme();
    var e = current.event, p = e && e.pod;
    if (!p || !p.explained || !p.modes) {
      ["ch-pod", "ch-pod-mode", "ch-pod-coef"].forEach(function (id) { empty(id, e ? "No reduced-order model for this track." : lapDataMissing()); });
      fill("rom_text", e ? "No reduced-order model was fitted at this track." : ""); $("rom-dl").innerHTML = ""; fill("rom_note", "");
      ["pod-sub", "pod-mode-sub"].forEach(function (id) { $(id).textContent = ""; });
      return;
    }
    var where = focusName(e), ex = p.explained, n = p.drivers.length, k = (p.coefficients[0] || []).length;
    var c1 = p.coefficients.map(function (c) { return c[0]; }), c2 = p.coefficients.map(function (c) { return c[1]; });
    var r = corr(c1, p.lap_time_s), sgnFlip = r > 0 ? -1 : 1;  // orient the first shape so that a higher coefficient means a faster lap
    var rr = r * sgnFlip;
    fill("rom_text", "Proper orthogonal decomposition (the same maths as principal component analysis) takes the " + n + " speed traces from " + esc(where) + ", removes the average lap and finds the few shapes that explain how the cars differ. Each car then becomes " +
      count(k) + " coefficients instead of a whole speed trace.");
    $("rom-dl").innerHTML = dl([["First shape", pct(ex[0]) + " of the differences"], ["First " + count(k) + " shapes", pct(sum(ex.slice(0, k)))]]);
    fill("rom_note", "Checked by rebuilding each lap from shapes fitted without it: " + f(p.loo_rmse_kmh, 1) + " km/h RMS error, against " + f(p.reconstruction_rmse_kmh, 1) + " km/h with the lap included. " +
      (Math.abs(rr) >= 0.5 ? "Along the first shape, cars further to the right set faster laps (correlation with lap time " + f(rr, 2) + ")." : "The first shape is only loosely tied to lap time (correlation " + f(rr, 2) + ")."));
    $("pod-sub").textContent = where + ", % of the variance between laps";
    plot("ch-pod", [{ x: ex.map(function (v, i) { return i + 1; }), y: ex.map(function (v) { return 100 * v; }), type: "bar",
      marker: { color: ex.map(function (v, i) { return i < k ? t.ink2 : t.field; }) }, text: ex.map(function (v) { return pct(v); }), textposition: "outside", textfont: { size: 11, color: t.ink2 }, cliponaxis: false,
      hovertemplate: "shape %{x}: %{y:.1f}% of the differences<extra></extra>" }],
      layout(t, { bargap: 0.35, xaxis: { title: { text: "shape (dark = kept in the model)" }, dtick: 1 }, yaxis: { title: { text: "% of the differences" }, rangemode: "tozero" } }));
    // One standard deviation along the first shape, in km/h along the lap
    var s1 = Math.sqrt(mean(c1.map(function (v) { var dv = v - mean(c1); return dv * dv; }))), m1 = p.modes[0], dist = e.map.distance_m.slice(0, m1.length);
    $("pod-mode-sub").textContent = "km/h for a car one standard deviation along it, + = faster than the average lap";
    plot("ch-pod-mode", [{ x: dist, y: m1.map(function (v) { return sgnFlip * s1 * v; }), type: "scatter", mode: "lines", line: { color: t.ink2, width: 1.5 },
      fill: "tozeroy", fillcolor: hexA(t.field, 0.25), hovertemplate: "%{x:.0f} m: %{y:+.2f} km/h<extra></extra>" }],
      layout(t, { hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } },
        shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
    var isA = p.teams.map(function (tm) { return tm === TARGET; });
    plot("ch-pod-coef", [
      { x: c1.filter(function (v, i) { return !isA[i]; }).map(function (v) { return sgnFlip * v; }), y: c2.filter(function (v, i) { return !isA[i]; }), type: "scatter", mode: "markers", name: "other cars",
        marker: { size: 8, color: t.field, line: { color: t.surface, width: 1.5 } }, text: p.drivers.filter(function (v, i) { return !isA[i]; }),
        customdata: p.lap_time_s.filter(function (v, i) { return !isA[i]; }).map(lapTime), hovertemplate: "%{text}, %{customdata}<extra></extra>" },
      { x: c1.filter(function (v, i) { return isA[i]; }).map(function (v) { return sgnFlip * v; }), y: c2.filter(function (v, i) { return isA[i]; }), type: "scatter", mode: "markers+text", name: TARGET,
        marker: { size: 11, color: t.amr, line: { color: t.surface, width: 1.5 } }, text: p.drivers.filter(function (v, i) { return isA[i]; }), textposition: "top center", textfont: { size: 11, color: t.ink2 },
        customdata: p.lap_time_s.filter(function (v, i) { return isA[i]; }).map(lapTime), hovertemplate: "%{text}, %{customdata}<extra></extra>" },
    ], layout(t, { showlegend: false, xaxis: { title: { text: "first shape (→ faster)" } }, yaxis: { title: { text: "second shape" } } }));
  }

  // Energy: the speed chart follows the focus track; the clipping bars and text show the latest season
  function renderEnergy(t) {
    t = t || theme();
    var e = current.event;
    if (e && e.energy_speed) {
      var d = e.map.distance_m, keys = Object.keys(e.energy_speed);
      var amrKey = keys.filter(function (k) { return k !== e.pole.driver; })[0];
      $("energy-sub").textContent = focusName(e) + ", reference lap (" + e.pole.driver + ")" + (amrKey ? " and the fastest passing Aston Martin lap (" + amrKey + ")" : " only: no Aston Martin lap passed the data checks");
      var cols = {}; cols[e.pole.driver] = t.ref; if (e.comparison) cols[e.comparison.target] = t.amr;
      plot("ch-energy", keys.map(function (k) { return { x: d, y: e.energy_speed[k], name: k, type: "scatter", mode: "lines", line: { color: cols[k] || t.field, width: 1.5 }, hovertemplate: k + " %{x:.0f} m: %{y:.0f} km/h<extra></extra>" }; }),
        layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } } }));
    } else { $("energy-sub").textContent = ""; empty("ch-energy", e ? "No speed traces for this track." : lapDataMissing()); }
    var en = (S.energy || []).filter(function (r) { return String(r.season) === Y; }).sort(function (a, b) { return a.clip_time_loss_s - b.clip_time_loss_s; });
    var enPrev = (S.energy || []).filter(function (r) { return String(r.season) === Y0; });
    plot("ch-clip", [{ y: en.map(function (r) { return r.team; }), x: en.map(function (r) { return r.clip_time_loss_s; }), type: "bar", orientation: "h",
      marker: { color: en.map(function (r) { return r.team === TARGET ? t.amr : t.field; }) },
      customdata: en.map(function (r) { return [r.clip_speed_drop_kmh, r.clip_decel_distance_m]; }),
      hovertemplate: "%{y}<br>%{x:.3f} s a lap, speed drop %{customdata[0]:.1f} km/h, %{customdata[1]:.0f} m slowing<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "s a lap, " + Y } } }));
    // The other teams only, so Aston Martin isn't compared with an average that includes itself
    var fieldLoss = mean(en.filter(function (r) { return r.team !== TARGET; }).map(function (r) { return r.clip_time_loss_s; }));
    var lossPrev = mean(enPrev.filter(function (r) { return r.team !== TARGET; }).map(function (r) { return r.clip_time_loss_s; }));
    var rt = (REL_LAST.clip_time_loss_s || {}), largest = en.length && en[en.length - 1].team === TARGET, small = rt.mean < SP_LAST.time_total_s / 2;
    fill("energy_text", "In " + Y + " cars reach peak speed part-way along a straight and then slow down at full throttle. Speed-dependent power alone, including the regulated MGU-K taper, can't do that: it means power falls with time as deployment ends or the car harvests. Acceleration here has gravity removed using GPS altitude, and only decelerations lasting at least " +
      f(MTH.clip_min_decel_m, 0) + " m count. The other teams lose on average " + f(fieldLoss, 3) + " s a lap against holding peak speed, against " + (lossPrev < 0.0005 ? "less than 0.001 s" : f(lossPrev, 3) + " s") + " in " + Y0 + ". Aston Martin's loss on this measure (" + sgn(rt.mean, 3) + " s a lap against the other teams, " + interval([rt.lo, rt.hi], 3) + ")" +
      (rt.lo > 0 ? " is larger than the field's" + (largest ? " and the largest of any team" : "") + (small ? ", but small next to the " + f(SP_LAST.time_total_s, 2) + " s a lap its main straights cost, so this narrow measure of clipping doesn't explain the straight-line deficit on its own." : ".")
        : rt.hi < 0 ? " is smaller than the field's, so clipping on this measure doesn't explain its straight-line deficit."
        : " can't be told apart from the field's, so this narrow measure of clipping doesn't explain its straight-line deficit on its own."));
  }

  // Corner speeds against the field (season filter)
  function renderModels(t) {
    t = t || theme();
    var def = (S.team_corner_deficit || {})[state.season] || [];
    var teams = Array.from(new Set(def.map(function (r) { return r.team; })));
    var meanBy = {}; teams.forEach(function (tm) { meanBy[tm] = mean(def.filter(function (r) { return r.team === tm; }).map(function (r) { return r.deficit_kmh; })); });
    teams.sort(function (a, b) { return meanBy[a] - meanBy[b]; });
    var classes = ["low", "medium", "high"], marks = { low: "circle", medium: "diamond", high: "square" };
    plot("ch-deficit", classes.map(function (cl) {
      var r = teams.map(function (tm) { return def.filter(function (x) { return x.team === tm && x.speed_class === cl; })[0] || {}; });
      return { y: teams, x: r.map(function (x) { return x.deficit_kmh; }), name: cl + "-speed", type: "scatter", mode: "markers",
        marker: { symbol: marks[cl], size: 9, color: teams.map(function (tm) { return tm === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 1.5 } },
        error_x: { type: "data", symmetric: false, array: r.map(function (x) { return x.ci_hi - x.deficit_kmh; }), arrayminus: r.map(function (x) { return x.deficit_kmh - x.ci_lo; }), color: t.rule, thickness: 1, width: 0 },
        hovertemplate: "%{y}, " + cl + "-speed<br>%{x:+.1f} km/h<extra></extra>" };
    }), layout(t, { showlegend: true, margin: { l: 110, r: 16, t: 40, b: 44 }, xaxis: { title: { text: "km/h against expectation" } },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  // Hybrid corner-speed model, variance split, wind test and deficit accounting (no filters)
  function renderHybrid(t) {
    t = t || theme();
    var cm = S.corner_model || {}, ma = (S.shapley || {}).mean_abs || {}, pp = cm.physics_params || {};
    var names = { steady: "Steady-state formula, v² = aR / (1 − bρR)" + (pp.b != null && Math.abs(pp.b) < 1e-9 ? ", fitted aero term b = 0" : ""), physics: "Lap simulator on the track's geometry, nominal car from training events", ml: "Gradient boosting alone", hybrid: "Hybrid: simulator plus boosted residual" };
    var label = { steady: "Steady-state formula", physics: "Physics alone", ml: "Boosting alone", hybrid: "Hybrid" };
    var mm = {}; (cm.metrics || []).forEach(function (r) { mm[r.model] = r; });
    $("tbl-cm").innerHTML = "<caption>Out of sample by whole circuit: " + cm.n_circuits + " circuits, " + cm.n_events + " events, " + (cm.n_corners || "–") + " corners, " + (cm.n_rows || 0).toLocaleString("en-GB") + " car-corner speeds</caption>" +
      '<thead><tr><th>Model</th><th class="num">RMSE</th><th class="num">R²</th><th class="num">Within-corner R²</th></tr></thead><tbody>' +
      (cm.metrics || []).map(function (r) { return "<tr><td>" + names[r.model] + '</td><td class="num">' + f(r.rmse_kmh, 1) + ' km/h</td><td class="num">' + f(r.r2, 3) + '</td><td class="num">' + (r.model === "steady" || r.model === "physics" ? "n/a" : f(r.within_corner_r2, 2)) + "</td></tr>"; }).join("") +
      '</tbody><tfoot><tr><td colspan="4">Within-corner R² is n/a for the physics-only models: they predict the same speed for every car at a corner.</td></tr></tfoot>';
    var ph = mm.physics || {}, ml = mm.ml || {}, hy = mm.hybrid || {};
    fill("corner_text", "To predict each corner's minimum speed at a circuit it has never seen, the simulator makes the first guess and gradient boosting learns the error. I test it by holding out whole circuits, every event there in both seasons together, so no track leaks from training into testing. The physics guess runs the simulator on the held-out track's GPS geometry, with a nominal car calibrated only on the training events. On unseen circuits it " +
      (ph.r2 > ml.r2 ? "beats a black-box model" + (ph.r2 - ml.r2 >= 0.05 ? " clearly" : "") : "does no better than a black-box model") + " (R² " + f(ph.r2, 2) + " against " + f(ml.r2, 2) + "), and adding machine learning on top " +
      (Math.abs(hy.r2 - ph.r2) < 0.02 ? "changes little (" + f(hy.r2, 2) + ")." : (hy.r2 > ph.r2 ? "raises it to " : "lowers it to ") + f(hy.r2, 2) + "."));
    var rest = Object.keys(ma).filter(function (k) { return k !== "physics_prior"; }), restSum = sum(rest.map(function (k) { return ma[k]; }));
    $("hyb-dl").innerHTML = dl([["Conformal coverage", pct(cm.conformal_coverage, 1) + " at ±" + f(cm.conformal_halfwidth_kmh, 0) + " km/h"],
      ma.physics_prior != null ? ["Physics guess, mean absolute Shapley value", f(ma.physics_prior, 0) + " km/h"] : null,
      rest.length ? ["Other inputs, their mean absolute values added up", f(restSum, 0) + " km/h"] : null]);
    // Only the models that use car-specific inputs can tell cars apart at the same corner
    var carModels = (cm.metrics || []).filter(function (r) { return r.model === "ml" || r.model === "hybrid"; }), ce = cm.coverage_by_event || {};
    var wc = Math.max.apply(null, carModels.map(function (r) { return r.within_corner_r2; }).filter(isFinite));
    fill("hyb_note", (ma.physics_prior != null ? "On Aston Martin's " + ((S.shapley || {}).n_rows || 0).toLocaleString("en-GB") + " car-corner speeds, exact Shapley values measured from a median car-corner baseline give the physics guess " +
      pct(ma.physics_prior / (ma.physics_prior + restSum)) + " of the summed mean absolute contributions (" + f(ma.physics_prior, 0) + " of " + f(ma.physics_prior + restSum, 0) + " km/h). " : "") +
      "Almost all of the variance is between corners, so R² mostly measures geometry. " + (carModels.length && wc <= 0.05 ? "None of the models explains differences between cars at the same corner: the " + (carModels.length > 1 ? count(carModels.length) + " that can tell cars apart have within-corner R² of " + list(carModels.map(function (r) { return f(r.within_corner_r2, 2); })) : "one that can tell cars apart has a within-corner R² of " + f(wc, 2)) + ". So the car comparisons in this report are made directly, not through this model. " : "") +
      "Split-conformal " + pct(cm.conformal_target) + " intervals cover " + pct(cm.conformal_coverage, 1) + " of held-out corners overall, but coverage varies by event (median " + pct(ce.median, 1) + ", worst " + pct(ce.min) + ", " + pct(ce.share_below_80pct) + " of events below 80%).");
    fill("r2_sub", "held out by whole circuit, " + cm.n_circuits + " circuits");
    var order = (cm.metrics || []).slice().sort(function (a, b) { return a.r2 - b.r2; });
    plot("ch-r2", [{ y: order.map(function (r) { return label[r.model] || r.model; }), x: order.map(function (r) { return r.r2; }), type: "bar", orientation: "h",
      marker: { color: order.map(function (r) { return r.model === "hybrid" ? t.ink2 : t.field; }) }, text: order.map(function (r) { return f(r.r2, 2); }), textposition: "outside",
      textfont: { size: 12, color: t.ink2 }, cliponaxis: false, hovertemplate: "%{y}: R² %{x:.3f}<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 150, r: 48, t: 8, b: 44 }, xaxis: { title: { text: "R²" }, range: [0, 1] }, yaxis: { type: "category" } }));
  }

  function renderModelsFixed(t) {
    t = t || theme();
    var vs = S.variance_split || {}, yrs = Object.keys(vs).sort();
    plot("ch-var", [{ y: yrs, x: yrs.map(function (y) { return vs[y].median_event_share * 100; }), type: "scatter", mode: "markers", marker: { size: 12, color: t.amr, line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: yrs.map(function (y) { return (vs[y].event_share_iqr[1] - vs[y].median_event_share) * 100; }), arrayminus: yrs.map(function (y) { return (vs[y].median_event_share - vs[y].event_share_iqr[0]) * 100; }), color: t.amr, thickness: 1.5, width: 0 },
      hovertemplate: "%{y}: %{x:.0f}% between teams (median event)<extra></extra>" }],
      layout(t, { margin: { l: 50, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "% of the spread between teams, median event and middle half" }, range: [0, 100] }, yaxis: { type: "category" } }));
    if (yrs.length === 2) {
      var a = vs[yrs[0]], b = vs[yrs[1]];
      fill("var_text", "Within each event, qualifying gaps are split into a between-team part (mostly the car, but also how drivers are sorted into teams) and a within-team part (driver, lap execution, session and track evolution). Laps slower than " + f(MTH.representative_pct, 0) + "% of the best are left out as not representative (" +
        (S.laps_outside_107pct || 0) + " laps). In the median event the between-team share was " + pct(a.median_event_share) + " in " + yrs[0] + " (middle half of events " + pct(a.event_share_iqr[0]) + " to " + pct(a.event_share_iqr[1]) +
        ") and " + pct(b.median_event_share) + " in " + yrs[1] + " (" + pct(b.event_share_iqr[0]) + " to " + pct(b.event_share_iqr[1]) + "). Pooled over events it is " + pct(a.car_share) + " (" + LVL + " interval " + pct(a.car_share_ci90[0]) + " to " + pct(a.car_share_ci90[1]) + ") in " + yrs[0] + " and " +
        pct(b.car_share) + " (" + pct(b.car_share_ci90[0]) + " to " + pct(b.car_share_ci90[1]) + ") in " + yrs[1] + "." +
        (b.car_share_ci90[0] > 0.75 ? " Under the " + yrs[1] + " rules the qualifying order is set almost entirely by the teams, car and driver line-up together, rather than by differences between team-mates." : ""));
    }

    // The wind test sits on the dark checks band
    var tw = theme($("ch-wind")), wt = S.wind_rotation_test || {};
    var ang = Object.keys(wt.mean_relative_sse || {}).map(Number).sort(function (x, y) { return x - y; });
    plot("ch-wind", [{ x: ang, y: ang.map(function (a0) { return wt.mean_relative_sse[a0]; }), type: "scatter", mode: "lines+markers",
      line: { color: tw.muted, width: 2 }, marker: { size: 8, color: ang.map(function (a0) { return a0 === 0 ? tw.ink : tw.field; }), line: { color: tw.surface, width: 1.5 } },
      hovertemplate: "wind rotated %{x}°: %{y:.3f} of the ground-speed residual<extra></extra>" }],
      layout(tw, { margin: { l: 56, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "rotation applied to the wind direction, °" }, dtick: 60 },
        yaxis: { title: { text: "residual / no-wind residual" } },
        shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: tw.muted, width: 1, dash: "dot" } }] }));
    var best = Math.min.apply(null, ang.map(function (a0) { return wt.mean_relative_sse[a0]; })), gain = (1 - best) * 100;
    var share = wt.share_events_assumed_orientation_best || 0, chance = ang.length ? 1 / ang.length : NaN, likeChance = share <= 2 * chance;
    fill("wind_text", "Wind components need the compass orientation of the timing X/Y frame, which the archive doesn't document. If both the orientation and the wind data were good, adding wind to the drag term should explain full-throttle acceleration better than ground speed alone, and best at 0° rotation. Across " +
      (wt.n_events || 0) + " windy sessions " + (gain > 0 ? "no rotation improves the fit by more than " + f(gain, 1) + "%" : "no rotation improves the fit at all") + ", and the assumed orientation was best in " + pct(share) + " of them, " +
      (likeChance ? "close to what chance gives (1 in " + ang.length + ")" : "more often than chance (1 in " + ang.length + ")") + ". " +
      (likeChance ? "Session-level wind readings aren't informative enough to use, so dynamic pressure uses ground speed and no wind effect is claimed." : "Even so, wind is left out of this version: dynamic pressure uses ground speed."));

    var dsum = S.deficit_summary || {}, dLast = dsum[Y] || {}, dPrev = dsum[Y0] || {}, cLast = dLast.ratio_ci90 || [], cPrev = dPrev.ratio_ci90 || [];
    fill("accounting_text", "Giving the pole car's calibrated simulator Aston Martin's measured grip and straight-line figures accounts for " + pct(dLast.ratio_of_means) + " of the mean " + Y + " gap over the " + dLast.n_events +
      " events where it can be run. The interval includes the uncertainty in the grip ratios (" + LVL + " interval " + pct(cLast[0]) + " to " + pct(cLast[1]) + "), so it shows " +
      (cLast[0] <= 1 && cLast[1] >= 1 ? "that the measured deficits are the right size to explain the gap, not how the gap splits." : cLast[1] < 1 ? "that the measured deficits explain only part of the gap." : "that the measured deficits more than explain the gap.") + " Across those events it " +
      (dLast.r2_event_level > 0.3 ? "tracks the changes from event to event (R² " + f(dLast.r2_event_level, 2) + ", Spearman " + f(dLast.spearman, 2) + ")" :
        "ranks them " + (dLast.spearman > 0.6 ? "roughly" : "poorly") + " (Spearman " + f(dLast.spearman, 2) + ") but doesn't predict individual events (R² " + f(dLast.r2_event_level, 2) + ")") +
      ". In " + Y0 + ", when the gap averaged " + f(dPrev.mean_actual_s, 2) + " s against " + f(dLast.mean_actual_s, 2) + " s, the same accounting gives " + pct(dPrev.ratio_of_means) + " (" + pct(cPrev[0]) + " to " + pct(cPrev[1]) + ") and R² " + f(dPrev.r2_event_level, 1) +
      (dPrev.r2_event_level < 0.3 && dPrev.mean_actual_s < dLast.mean_actual_s ? ": it doesn't resolve small gaps." : ".") + " It's an accounting in physical terms, not a forecast: the grip ratios come from the same laps.");
  }

  // Statistics, checks and limits (no filters)
  function statsTable() {
    var vf = (S.straight_vs_field || {})[Y] || {}, cp = CP_LAST, V = (S.variance_split || {})[Y] || {}, cm = S.corner_model || {}, e = upgradeEffect(UPG), bc = S.bootstrap_coverage;
    var n = [].concat.apply([], YS.map(function (y) { return Object.keys(RATES[y] || {}).map(function (k) { return RATES[y][k].n_events; }); })).filter(isFinite);
    fill("stats_lede", "With " + Math.min.apply(null, n) + " to " + Math.max.apply(null, n) + " events per team and season, the statistics have to be right for small samples before any model is worth much.");
    var rows = [
      ["Paired bootstrap, with the worst rival picked inside each draw", "Is Aston Martin really slower on the straights than every other team? Every team is resampled on the same events.", vf.ratio != null ? f(vf.ratio, 2) + " in " + Y + ", " + interval(vf.ratio_ci90, 2) : "–"],
    ];
    if (bc && bc.n_events && bc.n_events.length > 1) {
      var k = bc.n_events.length - 1, short_ = bc.plain_pct[0] < 100 * bc.level;
      rows.push(["Expanded percentile bootstrap", (short_ ? "Plain bootstrap intervals are too narrow with few events. " : "") + "This version widens them, which brings their coverage closer to the nominal level. Checked by simulation for the mean of normally distributed values, " + bc.reps.toLocaleString("en-GB") + " samples of each size.",
        f(bc.plain_pct[0], 0) + "% plain and " + f(bc.expanded_pct[0], 0) + "% expanded at " + bc.n_events[0] + " events; " + f(bc.plain_pct[k], 0) + "% and " + f(bc.expanded_pct[k], 0) + "% at " + bc.n_events[k] + ". Aim: " + pct(bc.level)]);
    }
    if (cp.map_event) rows.push(["Bayesian changepoints", "Did the pace change during the season, and when? Repeated across " + (cp.prior_sensitivity || []).length + " prior settings.", Y + ": " + esc(short(cp.map_event)) + " " + f(cp.map_probability, 2) + ", no change " + f(cp.p_no_change, 2)]);
    if (e) rows.push(["Difference-in-differences with placebos", "Did an upgrade work? Its effect is compared with fake upgrades on other dates and at other teams.", sgn(e.effect_pct, 2) + "%, p = " + f(e.lead_p, 2) + (function () { var nPl = e.lead_test === "time" ? e.n_time_placebos : e.n_team_placebos; return e.lead_p <= 1 / (1 + nPl) + 1e-9 ? ", the lowest this test can give" : ""; })() +
      ", and " + f(e.lead_p_holm, 2) + " after the Holm adjustment (" + esc(short(e.event)) + ", " + Y + ")"]);
    if (V.car_share != null) rows.push(["Random-effects variance split", "How much of the qualifying order comes from the teams, and how much from team-mates?", pct(V.car_share) + " between teams in " + Y]);
    if (cm.conformal_coverage != null) rows.push(["Split-conformal intervals", "How wide does a corner-speed interval need to be to cover " + pct(cm.conformal_target) + " of corners at circuits the model never saw?", "±" + f(cm.conformal_halfwidth_kmh, 0) + " km/h, " + pct(cm.conformal_coverage, 1) + " covered"]);
    $("tbl-stats").innerHTML = '<thead><tr><th scope="col">Method</th><th scope="col">What it answers</th><th scope="col">Result</th></tr></thead><tbody>' +
      rows.map(function (r) { return '<tr><th scope="row">' + r[0] + "</th><td>" + r[1] + '</td><td class="res">' + r[2] + "</td></tr>"; }).join("") + "</tbody>";
  }

  // Median size of the calibrated simulator's lap-time error on a season's reference laps, s
  function calError(season) {
    return median((S.calibration_accuracy || []).filter(function (r) { return r.is_pole && String(r.season) === season; }).map(function (r) { return Math.abs(r.lap_time_error_s); }));
  }

  function checksText() {
    var e = upgradeEffect(UPG), bc = S.bootstrap_coverage, ss = (S.surrogate_summary || {})[Y] || {}, cm = S.corner_model || {}, ce = calError(Y);
    // How often the intervals hold the truth, and how well the models fit
    var items = [];
    if (bc && bc.n_events) items.push([f(bc.expanded_pct[0], 0), "%", "In simulation, how often a widened " + LVL + " interval for the mean of " + count(bc.n_events[0]) + " normally distributed values holds the true mean. Plain bootstrap intervals: " + f(bc.plain_pct[0], 0) + "%."]);
    if (ss.coverage90_mean != null) items.push([f(100 * ss.coverage90_mean, 0), "%", "Unseen simulator runs inside the emulator's " + LVL + " bands, mean over the " + Y + " events." + (ss.coverage90_mean < MTH.interval_level ? " Short of the nominal " + LVL + ", so the bands are a little too narrow." : "")]);
    if (cm.conformal_coverage != null) items.push([f(100 * cm.conformal_coverage, 1), "%", "Corners inside the corner-speed model's intervals at circuits it never saw, aiming for " + pct(cm.conformal_target) + "."]);
    if (isFinite(ce)) items.push([f(ce, 2), "s", "Median size of the simulator's lap-time error after calibration, on the " + Y + " reference laps."]);
    $("check-figs").innerHTML = items.map(function (x) { return '<div><p class="v">' + x[0] + (x[1] ? (x[1] === "%" ? "" : " ") + "<small>" + x[1] + "</small>" : "") + '</p><p class="ctx">' + x[2] + "</p></div>"; }).join("");
    var rv = [
      ["A single power-deficit figure.", "An earlier version gave one. It hadn't taken out road gradient, and it compared cars on different stretches of track."],
      ["\"Slow corners are the biggest loss.\"", "That was raw seconds. Cars spend the most time in slow corners, so those usually carry the most."],
      ["Wind effects.", "The session wind data couldn't be trusted, so wind is left out."],
    ];
    if (e && verdict(e) !== "clear after correction") rv.push(["\"The " + esc(short(e.event)) + " upgrade worked.\"", verdict(e) === "suggestive, not after correction" ? "It's now \"may have helped, not proven\"." : "It's now \"no effect I can see\"."]);
    $("review").innerHTML = rv.map(function (r) { return '<li><span class="r-t">' + r[0] + '</span><span class="r-d">' + r[1] + "</span></li>"; }).join("");
    var eff = (S.upgrades || {}).effects || [];
    fill("limits_did", "Whether an upgrade worked, with " + (eff.length ? count(eff[0].n_pre) : "a few") + " events either side of it.");
  }

  // Approach, data handling and method (no filters)
  // One figure from this run of the pipeline under each step
  function approachText() {
    var dq = S.data_quality || {}, ss = (S.surrogate_summary || {})[Y] || {}, ce = calError(Y);
    fill("step_collect", dq.laps_total + " qualifying laps, each driver's fastest at each event, from " + S.n_events + " Grands Prix in " + list(YS));
    fill("step_check", dq.laps_passed + " of the " + dq.laps_total + " laps at the " + S.n_events + " events in the analysis pass every check");
    fill("step_align", "Official sector times matched to " + f(dq.sector_time_error_rms_s, 3) + " s RMS on the laps that pass");
    fill("step_physics", isFinite(ce) ? "Median size of the lap-time error after calibration " + f(ce, 2) + " s, " + Y + " reference laps" : "");
    fill("step_model", ss.rmse_s != null ? "Emulator error on unseen runs " + f(ss.rmse_s, 3) + " s, against " + f(ss.linear_rmse_s, 2) + " s for the linear version" : "");
  }

  // Each problem in the archive: what goes wrong, how it's caught or corrected, and how often
  function dataIssues() {
    var dq = S.data_quality || {}, fails = dq.laps_failed_by_check || {}, ref = S.reference_not_fastest || [], wet = S.wet_events_excluded || [];
    var geo = dq.events_geometry_failed || [];
    var rows = [
      ["Half the GPS is filled in", "Between real GPS fixes the archive fills in positions on the car-data clock along a smooth curve in time. Real fixes sit on whole decimetres, so the two can be told apart. The clock matching, the alignment and the curvature use only the real fixes, and the wheel-speed odometer fills in between them.",
        dq.gps_fixes_per_lap_median != null ? f(dq.gps_fixes_per_lap_median, 0) + " real fixes in a median lap of " + f(dq.samples_per_lap_median, 0) + " samples" : ""],
      ["Two clocks out of step", "Matched on speed, the GPS stream runs ahead of the car data. That could be a clock offset or a lag in the speed channel; either way, each lap's offset is found by matching GPS-derived speed to the wheel-speed sensor, then corrected.",
        "Median offset " + f(dq.gps_lag_s_median, 2) + " s"],
      ["A lap clock that starts in the wrong place", "The archive's lap clock is often offset from the timing line. Each lap is re-timed so the car is at the line at zero and at the official lap time. The official sector times come from separate timing loops and make a cross-check: with each sector line placed where most laps put it, a lap whose clock disagrees with them by too much is rejected.",
        "On the laps that pass, a median " + f(dq.clock_offset_m_median, 0) + " m and up to " + f(dq.max_clock_offset_m, 0) + " m off at the line (" + esc(dq.max_clock_offset_lap) + "), and sector times that agree to " +
        f(dq.sector_time_error_rms_s, 3) + " s RMS over " + dq.n_laps_sector_checked + " laps"],
      ["Telemetry that freezes or stalls", "Speed, throttle and brake can hold their values and then jump, while GPS shows the car braking. Laps with a long frozen stretch are rejected, and so are laps where wheel speed jumps in a way no car could while GPS disagrees with it.",
        (fails.frozen_run_m || 0) + " laps with frozen telemetry and " + (fails.car_data_stall_kmh || 0) + " with a car-data stall"],
    ];
    if (ref.length) rows.push(["When the fastest lap is broken", "If the fastest lap of qualifying fails a check, the reference becomes the fastest lap that passes.",
      list(ref.map(function (r) { return r.season + " " + esc(short(r.event)) + ": " + esc(r.reference) + "'s lap instead of " + esc(r.fastest) + "'s, " + f(r.gap_s, 2) + " s slower"; }))]);
    if (wet.length) rows.push(["A wet session", "Wet qualifying says little about the dry car, so it's left out of everything built on qualifying. Its dry race still counts.", list(wet.map(esc))]);
    rows.push(["Track shape", "The curvature from GPS has to add up to the circuit's own number of turns, or the event is left out of the shape-based fits.",
      geo.length ? count(geo.length) + " events fail: " + list(geo.map(esc)) : "Every event passes"]);
    $("issues").innerHTML = rows.map(function (r) {
      return '<li><h3>' + r[0] + '</h3><p class="body">' + r[1] + "</p>" + (r[2] ? '<p class="res">' + r[2] + "</p>" : "") + "</li>";
    }).join("");
  }

  // Laps rejected by each data check, largest at the top
  function renderDataChecks(t) {
    t = t || theme($("ch-checks"));
    var dq = S.data_quality || {}, fails = dq.laps_failed_by_check || {}, lab = XI.check_labels || {};
    var ks = Object.keys(fails).sort(function (a, b) { return fails[a] - fails[b]; });
    if (!ks.length) { empty("ch-checks", "This build has no check counts."); return; }
    var dropped = (S.skipped_events || []).filter(function (s) { return /Only \d+ laps passed/.test(s.reason); }).length;
    fill("checks_sub", "out of the " + dq.laps_total + " laps at the " + S.n_events + " events in the analysis. " + (dq.laps_total - dq.laps_passed) + " were rejected in all, and a lap can fail more than one check" +
      (dropped ? ". Events where too few laps passed are listed on the right and not counted here" : ""));
    plot("ch-checks", [{ y: ks.map(function (k) { return lab[k] || k; }), x: ks.map(function (k) { return fails[k]; }), type: "bar", orientation: "h", marker: { color: t.ink2 },
      text: ks.map(function (k) { return String(fails[k]); }), textposition: "outside", textfont: { size: 11, color: t.ink2 }, cliponaxis: false, hovertemplate: "%{y}: %{x} laps<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 8, r: 32, t: 8, b: 44 }, xaxis: { title: { text: "laps rejected" }, rangemode: "tozero" }, yaxis: { type: "category" } }));
  }

  function renderMethod() {
    var dq = S.data_quality || {}, eff = (S.upgrades || {}).effects || [];
    $("skipped").innerHTML = (S.skipped_events || []).map(function (s) {
      var missing = (s.reason.match(/(?:Qualifying|Race)\/([\w.]+\.json)/) || [])[1], passed = (s.reason.match(/Only (\d+) laps passed/) || [])[1];
      var why = passed != null ? (+passed === 0 ? "no lap passed the automated data checks" : "only " + passed + " laps passed the automated data checks, too few to compare")
        : missing ? "the archive had no " + missing + " for this event when the data was fetched" : s.reason;
      return "<li>" + s.season + " " + esc(s.event) + ": " + esc(why) + "</li>";
    }).join("") + (dq.events_geometry_failed || []).map(function (e) { return "<li>" + esc(e) + ": kept for timing analyses, left out of curvature-based fits (turning number check)</li>"; }).join("");
    fill("method_html",
      "<h3>Pipeline</h3><p>The fastest valid qualifying lap of every driver at every event is resampled onto a shared distance grid by projecting GPS fixes onto the reference lap's line. Time comes from the measured timing channel and closes exactly on the official lap time. Matched on speed, the archive's GPS stream runs about " + f(dq.gps_lag_s_median, 2) +
      " s ahead of the car-data stream (a clock offset or a lag in the speed channel), so each lap's offset is estimated by matching GPS-derived speed to the wheel-speed sensor, and corrected.</p>" +
      "<p>Track curvature is the median over all drivers of a time-domain smoothing spline through the raw GPS fixes. The smoothing level is chosen per event by the same speed cross-check, and each event's curvature must integrate to the circuit's own turn count (zero for the figure-of-eight Suzuka).</p>" +
      "<h3>Track views</h3><p>The track-by-track and track-detail views compare each Aston Martin driver's fastest qualifying lap that passed the data checks with the event's reference lap: the fastest lap that passes every check" + (function () {
        var r = S.reference_not_fastest || [];
        return r.length ? " (the fastest lap of qualifying at every event but " + list(r.map(function (x) { return x.season + " " + esc(short(x.event)) + ", where " + esc(x.fastest) + "'s lap has no usable telemetry and " + esc(x.reference) + "'s is used"; })) + ")" : " (the fastest lap of qualifying at every event)";
      })() + ". Section and corner times add up to the gap between the two laps. Each other team is represented by its fastest passing lap. Loss rates over several tracks are sums of seconds over sums of the reference lap's seconds, as in the season analysis, but without intervals: a handful of tracks is too few for them. Corner minimum speeds count only where the speed channel agrees with GPS.</p>" +
      "<h3>What the numbers can and can't say</h3><p>Grip, downforce and drag figures are effective values for a point-mass car. Load transfer and tyre load sensitivity are folded in, so absolute μ and C<sub>L</sub>A can't be separated from public data, and they are reported only as comparisons at matched dynamic pressure. Mass is the regulation minimum plus an assumed " +
      f(MTH.fuel_kg, 0) + " kg of fuel. The " + Y + " minimum leaves the tyres out and their mass isn't published, so an estimate for them is added (the sources are listed in the repository). The power analysis measures deployed wheel power, which includes energy strategy. Correlation with declared upgrades is evidence, not proof: " + (eff.length ? count(eff[0].n_pre) : "a few") + " events either side is a short window, and track layouts differ.</p>");
  }

  // Masthead and author
  // The masthead marks the section on screen. On a narrow screen the links are a strip that
  // scrolls sideways, so it also brings the marked link into view.
  function navSpy() {
    var nav = document.querySelector(".nav"), links = Array.prototype.slice.call(nav.querySelectorAll("a"));
    var secs = links.map(function (a) { return $(a.getAttribute("href").slice(1)); });
    var on = null, queued = false, still = window.matchMedia("(prefers-reduced-motion: reduce)");
    function edge() { nav.classList.toggle("more", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2); }
    function update() {
      queued = false;
      var y = (parseFloat(document.documentElement.style.scrollPaddingTop) || 0) + 24, k = -1;
      secs.forEach(function (s, i) { if (s && s.getBoundingClientRect().top <= y) k = i; });
      if (k === on) return;
      on = k;
      links.forEach(function (a, i) { if (i === k) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
      if (k >= 0 && nav.scrollWidth > nav.clientWidth) {
        nav.scrollTo({ left: links[k].offsetLeft - nav.offsetLeft - 24, behavior: still.matches ? "auto" : "smooth" });
      }
    }
    function queue() { if (!queued) { queued = true; requestAnimationFrame(update); } }
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", function () { edge(); queue(); });
    nav.addEventListener("scroll", edge, { passive: true });
    edge(); update();
  }

  // The byline jumps to the author details at the foot of the page. They are marked once
  // they are on screen (the rule over the name draws in), and take the focus for keyboards.
  function authorLinks() {
    var box = $("author"), waiting = location.hash === "#author";
    if (!box) return;
    function arrive() {
      waiting = false;
      box.classList.remove("arrived");
      void box.offsetWidth;  // restart the animation on a second visit
      box.classList.add("arrived");
      box.focus({ preventScroll: true });
    }
    function onScreen() { var r = box.getBoundingClientRect(); return r.top < 0.75 * window.innerHeight && r.bottom > 0; }
    new IntersectionObserver(function (es) { if (waiting && es[0].isIntersecting) arrive(); }, { threshold: 0.25 }).observe(box);
    document.querySelectorAll('a[href="#author"]').forEach(function (a) {
      a.addEventListener("click", function () { if (onScreen()) arrive(); else waiting = true; });
    });
    // Mail and phone links need an app to open them, so each address also has a copy button
    box.querySelectorAll(".copy").forEach(function (btn) {
      var addr = btn.parentNode.querySelector(".addr"), timer;
      function say(t) { btn.textContent = t; clearTimeout(timer); timer = setTimeout(function () { btn.textContent = "Copy"; }, 2000); }
      function select() { var r = document.createRange(), s = window.getSelection(); r.selectNodeContents(addr); s.removeAllRanges(); s.addRange(r); say("Selected"); }
      btn.addEventListener("click", function () {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(btn.getAttribute("data-copy")).then(function () { say("Copied"); }, select);
        else select();
      });
    });
  }

  // Boot
  function syncHeaderOffset() {
    var h = document.querySelector(".masthead");
    if (h) document.documentElement.style.scrollPaddingTop = (h.getBoundingClientRect().height + 8) + "px";
  }

  function start() {
    initState();
    syncHeaderOffset();
    window.addEventListener("resize", syncHeaderOffset);
    navSpy(); authorLinks();
    introText(); numbersBand(); findingsList(); evidenceText(); approachText(); dataIssues();
    buildFilters();
    status();
    [renderHero, renderProfile, renderHalves, renderJoint, renderSens, renderCalAcc, renderModelsFixed, renderHybrid, renderDataChecks].forEach(function (fn) { register("fixed", fn); });
    [renderRates, renderUpgradeParts, renderGap, renderCP, renderAero, renderModels, renderSurrogateEvents].forEach(function (fn) { register("season", fn); });
    [renderTracks, renderRace].forEach(function (fn) { register("tracks", fn); });
    current.entry = entry(state.focus[state.season]);  // the detail shows "Loading…" until its files arrive
    [renderDetail, renderSim, renderEnergy, renderPOD, renderSurrogate].forEach(function (fn) { register("detail", fn); });
    renderDiD(); renderMethod(); statsTable(); checksText();
    fillTrackSelect();
    $("sel-track").addEventListener("change", function () { setFocus(this.value); });
    $("tbl-tracks").addEventListener("click", onTableActivate);
    $("tbl-tracks").addEventListener("keydown", onTableActivate);
    setFocus(state.focus[state.season]);
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", function () { rerender(); });
    new MutationObserver(function () { rerender(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
  if (!window.Plotly) { document.addEventListener("DOMContentLoaded", start); } else { start(); }
})();
