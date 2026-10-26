/* Report front end. Numbers come from window.SEASON (season analyses), window.EXPLORER_INDEX
   (per-track sums for the track views) and per-track files loaded on demand from
   data/explorer/ and data/events/, all written by `aerotwin report`. One filter bar (season,
   Aston Martin drivers, tracks) drives the page; each section says which filters it follows. */
(function () {
  "use strict";
  var S = window.SEASON, M = window.MANIFEST || [];
  var XI = window.EXPLORER_INDEX || { events: [], drivers: {}, names: {} };
  var TARGET = "Aston Martin";
  var SECS = ["straights", "high", "medium", "low"];
  var SEC_LABEL = { straights: "straights", high: "high-speed corners", medium: "medium-speed corners", low: "low-speed corners" };
  var SEC_SHORT = { straights: "Straights", high: "High-speed", medium: "Medium", low: "Low-speed" };
  var groups = { season: [], tracks: [], detail: [], fixed: [] };
  var state = { season: null, drivers: {}, tracks: {}, focus: {}, mapDriver: null, straight: 0 };
  var current = { event: null, detail: null, entry: null };

  // ------------------------------------------------------------------ helpers
  function $(id) { return document.getElementById(id); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  // Typographic minus; a value that rounds to zero loses its sign
  function f(x, d) { return x == null || !isFinite(x) ? "–" : Number(x).toFixed(d == null ? 1 : d).replace(/^-(?=.*[1-9])/, "−").replace(/^-/, ""); }
  function sgn(x, d) { return x == null || !isFinite(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d == null ? 1 : d); }
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

  function theme() {
    return { ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), rule: css("--rule"), surface: css("--surface"),
      amr: css("--amr"), ref: css("--ref"), third: css("--third"), field: css("--field"), loss: css("--loss"), bg: css("--bg"),
      mono: css("--font-mono"), body: css("--font-body") };
  }
  function axis(t, extra) {
    return Object.assign({ gridcolor: t.rule, zerolinecolor: t.muted, linecolor: t.rule, tickfont: { color: t.muted, family: t.mono, size: 11 },
      titlefont: { color: t.ink2, size: 12 }, automargin: true, zeroline: false }, extra || {});
  }
  function layout(t, extra) {
    var base = { paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { family: t.body, color: t.ink2, size: 12 },
      margin: { l: 56, r: 16, t: 10, b: 44 }, hoverlabel: { bgcolor: t.surface, bordercolor: t.rule, font: { color: t.ink, family: t.body, size: 12 } },
      legend: { orientation: "h", x: 0, y: 1.12, font: { size: 11, color: t.ink2 } }, showlegend: false };
    var out = Object.assign(base, extra || {});
    if (out.showlegend && !(extra || {}).margin) out.margin = { l: 56, r: 16, t: 48, b: 44 };
    if (out.showlegend && !(extra || {}).legend) out.legend = { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", traceorder: "normal", font: { size: 11, color: t.ink2 } };
    out.xaxis = axis(t, (extra || {}).xaxis); out.yaxis = axis(t, (extra || {}).yaxis);
    ["xaxis2", "yaxis2", "xaxis3"].forEach(function (k) { if (extra && extra[k]) out[k] = axis(t, extra[k]); });
    return out;
  }
  function plot(id, traces, lay) {
    var el = $(id); if (!el || !window.Plotly) return;
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

  // ------------------------------------------------------------------ filter state
  var ALL_DRIVERS = Array.from(new Set([].concat.apply([], Object.keys(XI.drivers || {}).map(function (y) { return XI.drivers[y]; })))).sort();
  function drvColor(t, d) { var i = ALL_DRIVERS.indexOf(d); return [t.amr, t.third][i] || t.ink2; }
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
    state.season = ys.indexOf("2026") >= 0 ? "2026" : ys[ys.length - 1];
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
    var scopes = {
      finding: "Loss-rate chart: " + y + ", " + team + ". The rest is the 2026 finding, with 2025 for comparison.",
      tracks: "Showing " + $("f-status").textContent,
      detail: "Showing " + (current.entry ? trk(current.entry) + " " + y : "the track picked below") + " · " + (d.length ? d.map(lastName).join(", ") : "no driver"),
      sim: "Follows the track picked in Track detail",
      energy: "Left: the track picked in Track detail · right: 2026, team level",
      race: "Showing " + $("f-status").textContent,
      upgrades: "Showing " + y + ", " + team,
      aero: "Showing " + y + ", " + team,
      models: "Corner-speed chart: " + y + ", " + team + ". Model tests use both seasons.",
    };
    document.querySelectorAll("[data-scope]").forEach(function (el) { el.textContent = scopes[el.getAttribute("data-scope")] || ""; });
  }

  // ------------------------------------------------------------------ headline text
  var PROF = (S.straight_profile || {});
  var SP26 = (PROF["2026"] || {})[TARGET] || {};
  var SP25 = (PROF["2025"] || {})[TARGET] || {};
  var REL26 = ((S.target_relative || {})["2026"]) || {};
  var CP26 = (S.changepoints || {})["2026"] || {};
  var PT26 = ((S.powertrain || {})["2026"] || {})[TARGET] || {};
  function upgradeComponent(season) { return (S.upgrade_components || []).filter(function (u) { return u.season === season; })[0]; }
  var UPG = upgradeComponent(2026);

  function ci(a, d, unit) { return a && a.length === 2 ? f(a[0], d) + " to " + f(a[1], d) + (unit || "") : "–"; }

  var RATES = S.section_rates || {};
  function rate(season, team) { return (RATES[season] || {})[team] || {}; }
  function secRate(r, name) { var i = (r.sections || []).indexOf(name); return i < 0 ? {} : { v: r.rate_pct[i], lo: r.ci_lo[i], hi: r.ci_hi[i] }; }
  function others(season, offPace) {
    var o = RATES[season] || {};
    // offPace: teams at least 1% off pole over a lap; nearer the front the corner deficit is too
    // small for a stable straights-to-corners ratio
    return Object.keys(o).filter(function (k) { return k !== TARGET && o[k].n_events >= 5 && (!offPace || o[k].lap_rate_pct >= 1); }).map(function (k) { return { team: k, r: o[k] }; });
  }

  function heroText() {
    fill("n_events", String(S.n_events));
    var a26 = rate("2026", TARGET), a25 = rate("2025", TARGET), st26 = secRate(a26, "straights");
    var stOthers = others("2026").map(function (x) { return secRate(x.r, "straights").v; });
    var ratioOthers = others("2026", true).map(function (x) { return x.r.straight_to_corner_ratio; });
    var cad = rate("2026", "Cadillac"), cadSt = secRate(cad, "straights");
    var vf = (S.straight_vs_field || {})["2026"] || {};
    fill("hero_lede",
      "Measured as a share of the time spent in each part of the lap, " + (Math.max.apply(null, ratioOthers) < 1 ? "every other team more than 1% off pole loses its time faster in the corners than on the straights" : "most teams more than 1% off pole lose their time faster in the corners than on the straights") +
      (a25.straight_to_corner_ratio < 1 ? ", and so did Aston Martin in 2025" : "") + ". In 2026 it loses " +
      f(st26.v, 1) + "% of its straight-line time (90% CI " + f(st26.lo, 1) + "–" + f(st26.hi, 1) + "%), close to its " + f(a26.corner_rate_pct, 1) + "% in the corners. Every other team with five or more events (its own pole laps count as zero loss) has a straight-line rate between " +
      f(Math.min.apply(null, stOthers), 1) + "% and " + f(Math.max.apply(null, stOthers), 1) + "%. Cadillac, about as slow over a lap (" + f(cad.lap_rate_pct, 2) + "% vs " + f(a26.lap_rate_pct, 2) +
      "%), loses " + f(cadSt.v, 1) + "% on the straights. On " + SP26.n_straights_losing_late + " of " + SP26.n_straights + " main straights Aston Martin's speed gap also grows in the second half, by " + f(-SP26.second_half_kmh, 1) + " km/h on average, at full throttle.");
    var tiles = [
      { k: "Straight-line loss rate, 2026", v: f(st26.v, 1) + "%", ci: "90% CI " + f(st26.lo, 1) + "–" + f(st26.hi, 1) + "% · " + f(vf.ratio, 1) + "× the next team on the same " + vf.n_events + " tracks (" + esc(vf.next_team || "–") + "), CI " + ci(vf.ratio_ci90, 1), amr: true },
      { k: "Straights vs corners, 2026", v: f(a26.straight_to_corner_ratio, 2), ci: "ratio of loss rates, CI " + ci(a26.straight_to_corner_ci90, 2) + " · teams over 1% off pole " + f(Math.min.apply(null, ratioOthers), 2) + "–" + f(Math.max.apply(null, ratioOthers), 2) },
      { k: "Same ratio, 2025 car", v: f(a25.straight_to_corner_ratio, 2), ci: "CI " + ci(a25.straight_to_corner_ci90, 2) + " · " + (function () {
        var r = others("2025", true).map(function (x) { return x.r.straight_to_corner_ratio; }), lo = Math.min.apply(null, r), hi = Math.max.apply(null, r), v = a25.straight_to_corner_ratio;
        return (v < lo ? "below" : v > hi ? "above" : "in line with") + " the teams over 1% off pole, " + f(lo, 2) + "–" + f(hi, 2);
      })() },
      { k: "Lost late on the straights", v: f(SP26.second_half_kmh, 1) + " km/h", ci: "second half, full throttle, CI " + ci(SP26.second_half_ci90, 1) + " · " + SP26.n_straights + " straights, " + SP26.n_events + " events" },
    ];
    $("tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile"><span class="k">' + t.k + '</span><span class="v' + (t.amr ? " amr" : "") + '">' + t.v + '</span><span class="ci">' + t.ci + "</span></div>";
    }).join("");
    fill("hero_note", "Loss rate = time lost to the pole lap in a section ÷ time the pole lap spends there, summed over events. A car that is uniformly slower has equal rates everywhere, so rates (not seconds) show where a car is weak; in seconds, slow corners usually dominate because cars spend the most time there. Comparisons use the same piece of track, so geometry and gradient cancel, but laps can be set at different times of the session: track evolution mostly adds grip, which inflates corner rates more than straight-line ones. “Pole lap” means the fastest lap of qualifying" + (function () {
      var np = (XI.events || []).filter(function (e) { return !e.wet && e.fastest_lap && e.fastest_lap.segment && e.fastest_lap.segment !== "Q3"; });
      return np.length ? " (" + list(np.map(function (e) { return "at the " + e.season + " " + esc(e.event) + " that was a " + esc(e.fastest_lap.segment) + " lap"; })) + ", faster than the Q3 pole)" : "";
    })() + ". " + ((S.wet_events_excluded || []).length ? "Wet qualifying (" + list(S.wet_events_excluded.map(esc)) + ") is left out. " : "") +
      "Intervals are 90% bootstrap intervals over events, widened for small samples (expanded percentile bootstrap: with this few events, plain percentile intervals cover less than their nominal level, which the tests check by simulation).");

    fill("finding_text", "Splitting each main straight into ten equal pieces and comparing speeds piece by piece shows where the straight-line time goes. Aston Martin starts the straights " + f(-((SP26.bins || [])[0] || {}).gap_kmh, 1) +
      " km/h down, " + (function () {
        var c = SP26.first_half_ci90 || [NaN, NaN];
        return c[0] <= 0 && c[1] >= 0 ? "holds that through the first half (" + f(SP26.first_half_kmh, 1) + " km/h, CI " + ci(c, 1) + ") and loses "
          : (SP26.first_half_kmh < 0 ? "loses " : "gains ") + f(Math.abs(SP26.first_half_kmh), 1) + " km/h over the first half (CI " + ci(c, 1) + ") and ";
      })() + f(-SP26.second_half_kmh, 1) + " km/h more in the second half (CI " + ci(SP26.second_half_ci90, 1) +
      "), at full throttle: its drivers are not lifting early. The loss appears on " + SP26.n_straights_losing_late + " of " + SP26.n_straights + " main straights that start and end away from the timing line (" + SP26.n_events +
      " events); leaving out any one event keeps the average between " + f((SP26.second_half_loo_range || [])[1], 1) + " and " + f((SP26.second_half_loo_range || [])[0], 1) +
      " km/h. " + ((SP26.first_half_ci90 || [0, 0])[1] < 0 ? "Losing ground from the first metres means weaker acceleration than the field, not only a lower top speed. " : "Holding the gap while starting slower already means weaker acceleration than the field. ") + "The gap reaches " + f(-((SP26.bins || [])[(SP26.bins || []).length - 1] || {}).gap_kmh, 1) + " km/h at the braking point. Extra drag, deployment ending earlier and harvesting at full throttle can all open a gap along a straight; public timing data cannot tell them apart. " +
      (function () {
        var o = ((S.straight_profile || {})["2026"]) || {}, rows = Object.keys(o).filter(function (k) { return k !== TARGET && o[k].second_half_kmh != null; });
        if (!rows.length) return "";
        var late = rows.slice().sort(function (a, b) { return o[a].second_half_kmh - o[b].second_half_kmh; })[0];
        var starts = rows.map(function (k) { return Math.abs(((o[k].bins || [])[0] || {}).gap_kmh || 0); });
        return "A late loss on its own is not unusual: " + esc(late) + " loses " + f(-o[late].second_half_kmh, 1) + " km/h in the second half too, the next largest after Aston Martin. What sets Aston Martin apart is the size of both parts: no other team starts the straights more than " +
          f(Math.max.apply(null, starts), 1) + " km/h off the field. ";
      })() + "In 2025 the same second-half change was " + sgn(SP25.second_half_kmh, 1) + " km/h (CI " + ci(SP25.second_half_ci90, 1) + ").");
    var pt25 = ((S.powertrain || {})["2025"] || {})[TARGET] || {};
    fill("joint_text", "Fitting power and drag directly from acceleration on the first part of each straight, with gravity removed using the GPS altitude, does not separate them. The two terms are collinear over a single straight, so a fit needs at least 200 m of clean straight and a 60 km/h speed range; " +
      (PT26.n_events ? "Aston Martin passes that at " + PT26.n_events + " events in 2026, and the intervals still span " + ci(PT26.d_power_ci90, 0, " kW") + " and " + ci(PT26.d_cda_ci90, 2, " m²") + "."
        : "in 2026 Aston Martin's laps pass that at fewer than four events, so no fit is reported. In 2025 (" + (pt25.n_events || 0) + " events) the fitted power and drag move together (correlation " + f(pt25.correlation, 2) + ").") +
      " An earlier version of this page claimed a 36 kW power deficit; it came from not correcting for gradient and comparing cars on different stretches of track, and is withdrawn.");
    var st = (SP26.time_build_ci90 || []);
    fill("decomp_text", "Against the other teams' median, the main straights alone cost " + f(SP26.time_total_s, 2) + " s per lap (CI " + ci(SP26.time_total_ci90, 2) + "), of which " + f(SP26.time_build_s, 2) +
      " s (CI " + ci(st, 2) + ") is the speed lost along the straight rather than carried from the corner.");
  }

  function declaredParts(event, season) {
    var u = ((S.upgrades || {}).declared || []).filter(function (d) { return d.season === season && d.grand_prix === event; })[0];
    var n = u && (u.components.match(/(\d+) items/) || [])[1];
    return n ? n + "-part" : null;
  }
  function verdict(e) { return e.lead_p_holm <= 0.1 ? "clear after correction" : (e.lead_p <= 0.1 ? "suggestive, not after correction" : "not distinguishable"); }

  function upgradeText() {
    var y = state.season, cp = (S.changepoints || {})[y] || {}, effs = ((S.upgrades || {}).effects || []).filter(function (e) { return String(e.season) === y; });
    var cpS = cp.prior_sensitivity || [], p0s = cpS.map(function (r) { return r.p_no_change; });
    var pm = cpS.filter(function (r) { return r.map_event === cp.map_event; }).map(function (r) { return r.map_probability; });
    if (y === "2026" && UPG) {
      var gh = UPG.grip_high_rel;
      var uh = effs.filter(function (e) { return e.event === UPG.event; })[0] || {};
      fill("upgrade_text", "Aston Martin declared a " + (declaredParts(UPG.event, 2026) || "major") + " upgrade at the " + esc(UPG.event) +
        ". A changepoint model that is not told upgrade dates rates the " + esc(cp.map_event || "–") + " the most likely place for a single shift in its qualifying pace (posterior " + f(cp.map_probability, 2) +
        ", against " + f(cp.p_no_change, 2) + " for no change; across the prior settings tried, P(no change) ranges " + f(Math.min.apply(null, p0s), 2) + "–" + f(Math.max.apply(null, p0s), 2) +
        " and the " + esc(cp.map_event || "–") + " " + f(Math.min.apply(null, pm), 2) + "–" + f(Math.max.apply(null, pm), 2) + "). Given a change, the step is " +
        sgn(cp.effect_pct, 2) + "% of lap time (CI " + ci(cp.effect_ci90_pct, 2) + "); allowing for no change it averages " + sgn(cp.effect_avg_pct, 2) + "% (CI " + ci(cp.effect_avg_ci90_pct, 2) + "). " +
        (cp.two_change_events && cp.bf_two_vs_one > 3 ? "But the season fits a rise and a fall better than one step: a model with two changes (" + sgn((cp.two_change_steps_pct || [])[0], 1) + "% at the " + esc(cp.two_change_events[0]) +
          ", " + sgn((cp.two_change_steps_pct || [])[1], 1) + "% at the " + esc(cp.two_change_events[1]) + ") is " + f(cp.bf_two_vs_one, 1) + " times more likely, so much of the drop undoes a mid-season peak. " : "") +
        "Fast-corner grip relative to the other teams went from " + f(gh.before.mean * 100, 1) + "% to " + f(gh.after.mean * 100, 1) + "% (" + gh.before.n + " events before, only " + gh.after.n +
        " after with usable Aston Martin telemetry). The difference-in-differences test cannot settle it either: Aston Martin’s own 2026 estimates at other dates are spread about " + f(uh.noise_ratio, 0) +
        " times as widely as the rivals’ estimates at this date, so beating every rival’s placebo means little, and against its own " + (uh.n_time_placebos || "–") + " other dates no test can go below p = " + f(1 / (1 + (uh.n_time_placebos || 0)), 2) +
        " (the " + esc(UPG.event) + " gets " + f(uh.time_placebo_p, 2) + "). Suggestive, not established.");
      return;
    }
    // Any other season: the declared upgrades, the changepoint result and each test's verdict
    var decl = upgradeEvents(+y).map(function (u) { return (u.major_performance_upgrade === "major" ? "a major upgrade" : "a partial upgrade") + " at the " + esc(u.grand_prix); });
    var clear = cp.p_no_change >= 0.5;
    fill("upgrade_text", "In " + y + " Aston Martin declared " + (decl.length ? list(decl) : "no major upgrade") + ". " +
      (clear ? "A changepoint model that is not told upgrade dates finds no clear shift in its qualifying pace: P(no change all season) = " + f(cp.p_no_change, 2) + " (" + f(Math.min.apply(null, p0s), 2) + "–" + f(Math.max.apply(null, p0s), 2) +
        " across the prior settings tried), and the most likely single shift, at the " + esc(cp.map_event || "–") + ", has posterior " + f(cp.map_probability, 2) + ". "
        : "A changepoint model that is not told upgrade dates rates the " + esc(cp.map_event || "–") + " the most likely place for a single shift (posterior " + f(cp.map_probability, 2) + ", against " + f(cp.p_no_change, 2) + " for no change). ") +
      (effs.length ? "Difference-in-differences, each upgrade against " + (effs[0].lead_test === "time" ? "Aston Martin at its other dates" : "the rivals at the same date") + ": " + list(effs.map(function (e) {
        return esc(short(e.event)) + " " + sgn(e.effect_pct, 2) + "% of lap time (" + verdict(e) + ", Holm-adjusted p = " + f(e.lead_p_holm, 2) + ")";
      })) + ". " + (effs.some(function (e) { return e.lead_p_holm <= 0.1; }) ? "" : "None is distinguishable from the noise after correcting for testing several upgrades.") : ""));
  }

  // ------------------------------------------------------------------ finding charts (fixed: 2026 with 2025)
  function renderProfile(t) {
    t = t || theme();
    var traces = [];
    var p26 = PROF["2026"] || {};
    Object.keys(p26).filter(function (k) { return k !== TARGET; }).forEach(function (k, i) {
      var b = p26[k].bins;
      traces.push({ x: b.map(function (r) { return r.fraction * 100; }), y: b.map(function (r) { return r.gap_kmh; }), type: "scatter", mode: "lines",
        line: { color: t.field, width: 1 }, opacity: 0.6, name: k, showlegend: i === 0, legendgroup: "field", hovertemplate: k + ": %{y:+.1f} km/h<extra></extra>" });
    });
    traces[0] && (traces[0].name = "other teams, 2026");
    [["2025", SP25, t.third, "Aston Martin 2025"], ["2026", SP26, t.amr, "Aston Martin 2026"]].forEach(function (r) {
      var b = r[1].bins || [];
      var x = b.map(function (q) { return q.fraction * 100; });
      traces.push({ x: x.concat(x.slice().reverse()), y: b.map(function (q) { return q.ci_hi; }).concat(b.map(function (q) { return q.ci_lo; }).reverse()),
        type: "scatter", mode: "lines", fill: "toself", fillcolor: hexA(r[2], 0.15), line: { width: 0 }, hoverinfo: "skip", showlegend: false });
      traces.push({ x: x, y: b.map(function (q) { return q.gap_kmh; }), name: r[3], type: "scatter", mode: "lines+markers",
        line: { color: r[2], width: 2.2 }, marker: { size: 7, color: r[2], line: { color: t.surface, width: 1.5 } },
        hovertemplate: r[3] + "<br>%{x:.0f}% along: %{y:+.1f} km/h<extra></extra>" });
    });
    plot("ch-profile", traces, layout(t, { showlegend: true, xaxis: { title: { text: "position along the straight, % (corner exit → braking point)" }, range: [0, 100] },
      yaxis: { title: { text: "speed vs other teams, km/h" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } },
        { type: "rect", x0: 50, x1: 100, yref: "paper", y0: 0, y1: 1, fillcolor: t.ink2, opacity: 0.04, line: { width: 0 } }],
      annotations: [{ x: 75, yref: "paper", y: 0.02, yanchor: "bottom", text: "second half of the straight", showarrow: false, font: { size: 10, color: t.muted } }] }));
  }

  function renderHalves(t) {
    t = t || theme();
    var p26 = PROF["2026"] || {};
    var teams = Object.keys(p26).sort(function (a, b) { return p26[a].second_half_kmh - p26[b].second_half_kmh; });
    function tr(key, name, color, sym) {
      return { y: teams, x: teams.map(function (k) { return p26[k][key]; }), name: name, type: "scatter", mode: "markers",
        marker: { size: 9, symbol: sym, color: teams.map(function (k) { return k === TARGET ? color : t.field; }),
          line: { color: teams.map(function (k) { return k === TARGET ? color : t.field; }), width: 1.5 } },
        error_x: { type: "data", symmetric: false, array: teams.map(function (k) { return p26[k][key + "_ci90"] ? p26[k][key + "_ci90"][1] - p26[k][key] : 0; }),
          arrayminus: teams.map(function (k) { return p26[k][key + "_ci90"] ? p26[k][key] - p26[k][key + "_ci90"][0] : 0; }), color: t.rule, thickness: 1, width: 0 },
        hovertemplate: "%{y} · " + name + ": %{x:+.1f} km/h<extra></extra>" };
    }
    plot("ch-halves", [tr("first_half_kmh", "first half", t.ref, "circle-open"), tr("second_half_kmh", "second half", t.amr, "circle")],
      layout(t, { showlegend: true, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "change in speed gap within that half, km/h" } },
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
    fill("rates_sub", "% of the pole lap's time in each, summed over events · " + season + " · bars = 90% interval");
    var teams = Object.keys(o).filter(function (k) { return o[k].n_events >= 5; });
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
    var series = [["2026", t.amr, "Aston Martin 2026"], ["2025", t.third, "Aston Martin 2025"]].filter(function (r) { return ((((S.powertrain || {})[r[0]] || {})[TARGET]) || {}).draws; });
    plot("ch-joint", series.map(function (r) {
      var d = ((((S.powertrain || {})[r[0]] || {})[TARGET]) || {}).draws || [];
      return { x: d.map(function (q) { return q[0]; }), y: d.map(function (q) { return q[1]; }), name: r[2], type: "scatter", mode: "markers",
        marker: { size: 5, color: r[1], opacity: 0.35 }, hovertemplate: r[2] + "<br>ΔP %{x:.0f} kW · ΔCdA %{y:.2f} m²<extra></extra>" };
    }), layout(t, { showlegend: true, xaxis: { title: { text: "power vs field, kW (bootstrap draws)" } }, yaxis: { title: { text: "drag area vs field, m²" } } }));
  }

  // ------------------------------------------------------------------ track by track (all filters)
  var TM = window.TrackMath, sumRates = TM.sumRates, bestDriver = TM.bestDriver, amrPick = TM.amrPick, drvPick = TM.drvPick, teamPick = TM.teamPick, rep = TM.rep;
  function otherTeams(evs) {
    var s = {}; evs.forEach(function (e) { Object.keys(e.team_sections_s).forEach(function (k) { if (k !== TARGET) s[k] = 1; }); });
    return Object.keys(s).sort();
  }
  function noTelemetry(evs, d) { return evs.filter(function (e) { return rep(e, d) && !e.drivers[d]; }); }
  // A team that was the reference at every one of these tracks has zero loss by definition
  function referenceOnly(evs, team) { return evs.every(function (e) { return !e.team_sections_s[team] || e.reference.team === team; }); }
  function lostOrGained(v) { return v == null || !isFinite(v) ? "–" : v >= 0 ? "lost " + f(v, 1) + "%" : "gained " + f(-v, 1) + "%"; }
  // A median rank; halfway between two ranks reads as both ("10th–11th")
  function medRank(pos) { var m = median(pos); return m % 1 ? ord(Math.floor(m)) + "–" + ord(Math.ceil(m)) : ord(m); }
  // Why a lap has lap time only, as a short phrase ("frozen telemetry")
  function reasonShort(r) { var m = /^failed data checks(?:: (.*))?$/.exec(r || ""); return m ? (m[1] || "failed the data checks") : "no usable telemetry"; }

  function tracksText(evs, ds) {
    if (!evs.length || !ds.length) { fill("tracks_text", !evs.length ? "Pick at least one track in the bar at the top." : "Pick at least one driver in the bar at the top."); return; }
    var y = state.season, parts = [], many = evs.length > 1;
    var where = many ? "Over the " + evs.length + " selected " + y + " tracks" : "At " + trk(evs[0]) + " in " + y;
    var gaps = ds.map(function (d) { var g = evs.filter(function (e) { return rep(e, d); }); return { d: d, n: g.length, v: mean(g.map(function (e) { return e.timing[d].gap_pct; })) }; });
    var withLap = gaps.filter(function (g) { return g.n; });
    if (withLap.length) parts.push(where + ", " + list(withLap.map(function (g, i) {
      return lastName(g.d) + (i ? "’s " : "’s fastest lap was " + (many ? "on average " : "")) + f(g.v, 2) + "%" + (i ? "" : " off the fastest lap of qualifying") + (many && g.n < evs.length ? " (" + g.n + " track" + (g.n > 1 ? "s" : "") + " with a representative lap)" : "");
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
      if (slow.length) parts.push(lastName(d) + "’s fastest lap at " + list(slow.map(trk)) + " was more than 7% off the fastest lap (" + list(slow.map(function (e) { return "+" + f(e.timing[d].gap_pct, 1) + "%"; })) + "), not a representative lap under the 107% rule, so it is left out of the gap figures.");
    });
    var pos = evs.map(function (e) { return e.team_position; }).filter(function (v) { return v != null; });
    if (pos.length > 1) parts.push("As a team Aston Martin’s best lap ranked " + medRank(pos) + " of " + evs[0].n_teams + " in the median track (best " + ord(Math.min.apply(null, pos)) + ", worst " + ord(Math.max.apply(null, pos)) + ").");
    var pickA = amrPick(ds), amEvs = evs.filter(function (e) { return pickA(e); }), am = sumRates(amEvs, pickA);
    if (am) {
      var rival = otherTeams(amEvs).filter(function (k) { return !referenceOnly(amEvs, k); }).map(function (k) { return { k: k, r: sumRates(amEvs, teamPick(k)) }; }).filter(function (x) { return x.r; });
      var higher = rival.filter(function (x) { return x.r.straights > am.straights; });
      var top = rival.slice().sort(function (a2, b) { return b.r.straights - a2.r.straights; })[0];
      var on = am.n > 1 ? "On those " + am.n + " tracks" : "There";
      parts.push("Compared with the reference lap, " + (ds.length > 1 ? "the faster passing Aston Martin lap" + (am.n > 1 ? " at each track" : "") : lastName(ds[0]) + "’s lap" + (am.n > 1 ? "s" : "")) + " " + lostOrGained(am.straights) + " of the time spent on the straights and " +
        lostOrGained(am.corners) + " in the corners (" + am.n + " track" + (am.n > 1 ? "s" : "") + " with usable telemetry). " +
        (top ? on + ", " + (higher.length ? higher.length + " other team" + (higher.length > 1 ? "s" : "") + " had a higher straight-line loss rate; the highest was " : "no other team with a passing lap had a higher straight-line loss rate; the highest was ") +
          esc(top.k) + " at " + f(top.r.straights, 1) + "%." : ""));
    }
    ds.forEach(function (d) {
      var miss = noTelemetry(evs, d);
      if (miss.length) parts.push(lastName(d) + "’s lap" + (miss.length > 1 ? "s" : "") + " at " + list(miss.map(function (e) { return trk(e) + " (" + esc(reasonShort(e.timing[d].reason)) + ")"; })) + (miss.length > 1 ? " count" : " counts") + " for lap time only.");
    });
    var wet = wetNames(evs);
    if (wet.length) parts.push("Includes wet qualifying at " + list(wet) + ", which the season analyses leave out.");
    parts.push("These are point estimates for the tracks picked; the intervals for whole seasons are in the first section.");
    fill("tracks_text", parts.join(" "));
  }

  function trackTiles(evs, ds) {
    var el = $("trk-tiles");
    if (!evs.length || !ds.length) { el.innerHTML = ""; return; }
    function perDriver(fn, d0) { return ds.map(function (d) { return '<span class="dv"><i class="key" style="--c:var(--drv-' + Math.max(0, ALL_DRIVERS.indexOf(d)) + ')"></i>' + esc(lastName(d)) + " <b>" + fn(d) + "</b></span>"; }).join(""); }
    var pos = evs.map(function (e) { return e.team_position; }).filter(function (v) { return v != null; });
    var am = sumRates(evs, amrPick(ds));  // tracks without an Aston Martin lap drop out of the sums
    var race = ds.map(function (d) { return evs.filter(function (e) { return e.race && e.race.drivers[d]; }).map(function (e) { return e.race.drivers[d].gap_s; }); });
    var tiles = [
      { k: "Gap to the fastest lap", html: perDriver(function (d) { var g = evs.filter(function (e) { return rep(e, d); }); return g.length ? f(mean(g.map(function (e) { return e.timing[d].gap_pct; })), 2) + "%" : evs.some(function (e) { return e.timing[d]; }) ? "over 107%" : "no lap"; }), ci: "mean over tracks with a representative lap" },
      { k: "Team rank, median track", v: pos.length ? medRank(pos) : "–", ci: pos.length ? "of " + evs[0].n_teams + " · best " + ord(Math.min.apply(null, pos)) + ", worst " + ord(Math.max.apply(null, pos)) : "no lap times" },
      { k: "Straights vs corners", v: am && am.corners ? f(am.straights / am.corners, 2) : "–", ci: am ? "loss rates " + f(am.straights, 1) + "% vs " + f(am.corners, 1) + "% · " + am.n + " track" + (am.n > 1 ? "s" : "") : "no usable telemetry", amr: true },
      { k: "Race pace gap to the best team", html: race.some(function (r) { return r.length; }) ? perDriver(function (d) { var r = race[ds.indexOf(d)]; return r.length ? f(mean(r), 2) + " s" : "–"; }) : null, v: "–", ci: "per lap, mean over dry races" },
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
        colorscale: [[0, t.ref], [0.5, t.rule], [1, t.loss]], showscale: i === ds.length - 1, xgap: 2, ygap: 2,
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
        customdata: agg.map(function (a) { return [a.n, a.m]; }), hovertemplate: fullName(d) + " · %{y}<br>%{x:+.1f} km/h vs the other teams' median · %{customdata[0]} corners, %{customdata[1]} tracks<extra></extra>" });
    });
    if (!traces.some(function (tr) { return tr.x.some(function (v) { return v != null; }); })) return empty("ch-trk-corners", "No usable corner speeds for the selected drivers at these tracks.");
    plot("ch-trk-corners", traces, layout(t, { showlegend: ds.length > 1, margin: { l: 150, r: 16, t: ds.length > 1 ? 40 : 10, b: 44 },
      xaxis: { title: { text: "corner minimum speed vs the other teams, km/h" } }, yaxis: { type: "category", autorange: "reversed" },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderTrackStraights(t, evs, ds) {
    if (!evs.length || !ds.length) return empty("ch-trk-straights", "Pick at least one track and one driver.");
    var rows = [["entry_kmh", "start of the straight"], ["peak_kmh", "peak speed"], ["end_kmh", "braking point"], ["ftl", "held at full throttle"]], traces = [];
    ds.forEach(function (d) {
      var c = drvColor(t, d), S0 = { entry_kmh: 0, peak_kmh: 0, end_kmh: 0, ftl: 0, n: 0, m: 0 };
      evs.forEach(function (e) {
        var x = e.drivers[d]; if (!x || !x.straights.n) return;
        ["entry_kmh", "peak_kmh", "end_kmh"].forEach(function (k) { S0[k] += x.straights[k]; });
        S0.ftl += x.straights.field_full_throttle_loss_kmh - x.straights.full_throttle_loss_kmh; // negative: drops more speed than the field
        S0.n += x.straights.n; S0.m++;
      });
      traces.push({ y: rows.map(function (r) { return r[1]; }), x: rows.map(function (r) { return S0.n ? S0[r[0]] / S0.n : null; }), name: fullName(d), type: "scatter", mode: "markers",
        marker: { size: 11, symbol: drvSymbol(d), color: c, line: { color: t.surface, width: 1.5 } },
        hovertemplate: fullName(d) + " · %{y}<br>%{x:+.1f} km/h vs the other teams' median · " + S0.n + " straights, " + S0.m + " tracks<extra></extra>" });
    });
    if (!traces.some(function (tr) { return tr.x.some(function (v) { return v != null; }); })) return empty("ch-trk-straights", "No straights with usable telemetry for the selected drivers.");
    plot("ch-trk-straights", traces, layout(t, { showlegend: ds.length > 1, margin: { l: 150, r: 16, t: ds.length > 1 ? 40 : 10, b: 44 },
      xaxis: { title: { text: "km/h vs the other teams (negative = slower or more speed lost)" } }, yaxis: { type: "category", autorange: "reversed" },
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
          return r ? '<td class="num">' + (r.representative === false ? '<span class="hint" title="more than 7% off the fastest lap: not a representative lap">‡ </span>' : "") + (r.telemetry ? "" : '<span class="hint" title="' + esc(r.reason || "") + '">† </span>') + "+" + f(r.gap_s, 3) + " s · " + r.rank + "/" + r.n_drivers + "</td>" : '<td class="num"><span class="hint">no lap</span></td>';
        }).join("") +
        '<td class="num">' + (e.team_position ? e.team_position + "/" + e.n_teams : "–") + '</td><td class="num">' + (s ? sgn(s.straights, 3) + " s" : "–") + '</td><td class="num">' + (s ? sgn(s.high + s.medium + s.low, 3) + " s" : "–") + "</td>" +
        ds.map(function (d) { var r = e.race && e.race.drivers[d]; return '<td class="num">' + (r ? "+" + f(r.gap_s, 2) + " s" : '<span class="hint">' + (e.race ? "–" : "no fit") + "</span>") + "</td>"; }).join("") + "</tr>";
    }).join("");
    tb.innerHTML = "<caption>Gap and rank: each driver’s fastest lap against the fastest lap and every driver’s († = the lap failed the data checks, so lap time only; ‡ = more than 7% off, not a representative lap) · Team: rank of the team’s fastest lap · Straights, corners: seconds " + (ds.length > 1 ? "the faster passing Aston Martin lap" : esc(lastName(ds[0])) + "’s lap") + " lost to the reference lap there · Race: corrected pace, s per lap behind the best team. Click a row to open the track below.</caption>" + head + "<tbody>" + body + "</tbody>";
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

  // ------------------------------------------------------------------ race pace (all filters)
  function renderRace(t) {
    t = t || theme();
    var evs = selEvents(), ds = selDrivers();
    var by = byKey(S.race_pace || [], "season");
    var g25 = (by[2025] || []).filter(function (r) { return r.team === TARGET; })[0] || {}, g26 = (by[2026] || []).filter(function (r) { return r.team === TARGET; })[0] || {};
    var sel = ds.map(function (d) { var r = evs.filter(function (e) { return e.race && e.race.drivers[d]; }); return { d: d, n: r.length, v: mean(r.map(function (e) { return e.race.drivers[d].gap_s; })), single: r.filter(function (e) { return e.race.drivers[d].single_stint; }).map(function (e) { return trk(e); }) }; });
    var noRace = evs.filter(function (e) { return !e.race; }).map(function (e) { return trk(e); });
    fill("race_text", "Every green-flag lap of every dry race is fitted with driver pace, compound offsets, tyre degradation per lap of age and a fuel effect per lap, so the comparison is at equal fuel and fresh tyres. Intervals come from a delete-one-stint jackknife: each stint is left out in turn and the model refitted, so stint-level offsets such as traffic or tyre preparation enter the uncertainty; the tests check by simulation that the intervals cover about as often as they claim. A driver with only one stint cannot be left out, so intervals involving them are too narrow. Aston Martin’s corrected race pace averaged " +
      f(g25.mean, 2) + " s per lap off the best team in 2025 (" + g25.count + " races) and " + f(g26.mean, 2) + " s in 2026 (" + g26.count + " races). " +
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

  // ------------------------------------------------------------------ track detail (season, drivers, focus track)
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
  function amrLap(e, D, ds) { var d = bestDriver(e, ds); return d ? { d: d, s: e.drivers[d].sections_s, lap: e.timing[d].lap_time_s } : null; }
  // The team the analysed Aston Martin lap is compared with: the closest team whose compared lap
  // (its fastest passing lap) is faster. `direct`: it is also the team directly ahead of Aston
  // Martin on official lap times and the analysed lap is the team's fastest. `skipped`: teams
  // in between whose fastest lap has no usable telemetry.
  function rivalOf(e, D, ds) {
    var me = amrLap(e, D, ds); if (!me) return null;
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
    var co = diff - st, head = lastName(rv.me.d) + "’s lap was " + f(diff, 3) + " s slower";
    if (st > 0 && co >= 0) return head + ", " + f(st, 3) + " s of it on the straights";
    if (st > 0) return head + ": " + f(st, 3) + " s slower on the straights and " + f(-co, 3) + " s faster in the corners";
    return head + ": " + f(co, 3) + " s slower in the corners and " + f(-st, 3) + " s faster on the straights";
  }

  function detailText(e, D, ds) {
    var y = state.season, fl = e.fastest_lap, parts = [];
    parts.push("<b>" + esc(e.event) + " " + y + "</b>, " + esc(e.circuit) + ", qualifying on " + day(e.date) + " (UTC). The fastest lap was " + esc(fl.driver) + "’s (" + esc(fl.team) + ") " + lapTime(fl.lap_time_s) +
      (fl.is_pole ? ", on pole." : ", set in " + esc(fl.segment || "an earlier session") + "."));
    var tm = ds.filter(function (d) { return e.timing[d]; }).sort(function (a, b) { return e.timing[a].lap_time_s - e.timing[b].lap_time_s; });
    if (tm.length) parts.push(list(tm.map(function (d) { var r = e.timing[d]; return lastName(d) + "’s best was " + lapTime(r.lap_time_s) + " (+" + f(r.gap_s, 3) + " s, " + ord(r.rank) + " fastest of " + r.n_drivers + (r.representative === false ? "; more than 7% off, so not a representative lap" : "") + ")"; })) + ".");
    ds.filter(function (d) { return !e.timing[d]; }).forEach(function (d) { parts.push(lastName(d) + " set no lap time."); });
    if (e.team_position) parts.push("Ranked by each team’s fastest lap of the session, Aston Martin was " + ord(e.team_position) + " of " + e.n_teams + ".");
    var rv = rivalOf(e, D, ds);
    if (rv && rv.team) {
      var lead = rv.direct ? "Against " + esc(rv.team) + ", the team directly ahead, " :
        rv.skipped.length ? list(rv.skipped.map(esc)) + (rv.skipped.length > 1 ? " were" : " was") + " closer but " + (rv.skipped.length > 1 ? "have" : "has") + " no lap with usable telemetry. Against " + esc(rv.team) + ", the closest team ahead with one, " :
        "Against " + esc(rv.team) + ", the closest team ahead of that lap, ";
      parts.push(lead + gapPhrase(rv) + "." + (rv.tel !== rv.driver ? " (" + esc(rv.team) + "’s fastest lap, by " + esc(rv.driver) + ", has no usable telemetry, so its comparison uses " + esc(rv.tel) + "’s.)" : ""));
    } else if (rv && e.team_position === 1) parts.push("No team was ahead.");
    var miss = ds.filter(function (d) { return e.timing[d] && !e.timing[d].telemetry; });
    if (miss.length) {
      var analysed = ds.some(function (d) { return e.drivers[d]; }), other = Object.keys(e.drivers).filter(function (d) { return ds.indexOf(d) < 0; });
      parts.push(list(miss.map(function (d) { return lastName(d) + "’s lap " + esc(whyNot(e.timing[d].reason)); })) + ", so " +
        (analysed ? "only the other lap is analysed below." : other.length ? "there is no section or corner analysis for the selected driver" + (miss.length > 1 ? "s" : "") + "; add " + list(other.map(lastName)) + " in the Drivers filter to see the lap" + (other.length > 1 ? "s" : "") + " that " + (other.length > 1 ? "were" : "was") + " analysed." : "this track has lap times but no section or corner analysis."));
    }
    fill("detail_text", parts.join(" "));
  }

  function detailTiles(t, e, D, ds) {
    var tiles = [], rv = rivalOf(e, D, ds), me = amrLap(e, D, ds);
    var all = Object.keys(e.timing).map(function (d) { return e.timing[d].gap_s; });
    tiles.push({ k: "Team rank by fastest lap", v: e.team_position ? ord(e.team_position) : "–", ci: "of " + e.n_teams + (all.length ? " · fastest Aston Martin +" + f(Math.min.apply(null, all), 3) + " s" : ""), amr: true });
    if (rv && rv.team) {
      var diff = 0; SECS.forEach(function (k) { diff += rv.me.s[k] - rv.s[k]; });
      tiles.push({ k: "Gap to " + rv.team, v: sgn(diff, 3) + " s", ci: sgn(rv.me.s.straights - rv.s.straights, 3) + " s on the straights · " + lastName(rv.me.d) + "’s lap" });
    }
    if (me) {
      var rates = SECS.filter(function (k) { return e.ref_time_s[k] > 0; }).map(function (k) { return { k: k, v: 100 * me.s[k] / e.ref_time_s[k] }; }).sort(function (a, b) { return b.v - a.v; });
      if (rates.length) tiles.push({ k: "Highest loss rate", v: f(rates[0].v, 1) + "%", ci: SEC_LABEL[rates[0].k] + " · " + sgn(me.s[rates[0].k], 3) + " s · " + lastName(me.d) });
    }
    if (e.race) tiles.push({ k: "Race pace gap", v: e.race.team_gap_s != null ? "+" + f(e.race.team_gap_s, 2) + " s" : "–", ci: "per lap · " + (e.race.team_rank ? ord(e.race.team_rank) + " of " + e.race.n_teams + " · " : "") + "CI " + (e.race.team_ci ? f(e.race.team_ci[0], 2) + "–" + f(e.race.team_ci[1], 2) : "–") });
    $("det-tiles").innerHTML = tiles.map(function (x) { return '<div class="tile"><span class="k">' + esc(x.k) + '</span><span class="v' + (x.amr ? " amr" : "") + '">' + x.v + '</span><span class="ci">' + x.ci + "</span></div>"; }).join("");
  }

  function renderOrder(t, e, D) {
    var o = D.order;
    plot("ch-order", [{ y: o.map(function (r) { return r.team; }), x: o.map(function (r) { return r.gap_s; }), type: "bar", orientation: "h",
      marker: { color: o.map(function (r) { return r.team === TARGET ? t.amr : t.field; }) },
      text: o.map(function (r) { return r.gap_s ? "+" + f(r.gap_s, 3) : lapTime(r.lap_time_s); }), textposition: "outside", textfont: { size: 10, color: t.ink2, family: t.mono }, cliponaxis: false,
      customdata: o.map(function (r) { return [r.driver, lapTime(r.lap_time_s)]; }), hovertemplate: "%{y} · %{customdata[0]}<br>%{customdata[1]} · +%{x:.3f} s<extra></extra>" }],
      layout(t, { bargap: 0.3, margin: { l: 120, r: 50, t: 10, b: 44 }, xaxis: { title: { text: "s behind the fastest lap" }, rangemode: "tozero" }, yaxis: { autorange: "reversed", type: "category" } }));
  }

  function renderRival(t, e, D, ds) {
    var rv = rivalOf(e, D, ds);
    if (!rv || !rv.team) { $("rival-sub").textContent = ""; return empty("ch-rival", rv ? "No team with usable telemetry was ahead." : noLapText(e, ds)); }
    $("rival-sub").textContent = lastName(rv.me.d) + " vs " + rv.team + " (" + rv.tel + ") · s, + = Aston Martin slower";
    var vals = SECS.map(function (k) { return rv.me.s[k] - rv.s[k]; }), tot = vals.reduce(function (a, b) { return a + b; }, 0);
    var y = SECS.map(function (k) { return SEC_LABEL[k]; }).concat(["whole lap"]), x = vals.concat([tot]);
    plot("ch-rival", [{ y: y, x: x, type: "bar", orientation: "h", marker: { color: x.map(function (v, i) { return i === x.length - 1 ? t.ink2 : v >= 0 ? t.loss : t.ref; }) },
      text: x.map(function (v) { return sgn(v, 3) + " s"; }), textposition: "outside", textfont: { size: 11, color: t.ink2, family: t.mono }, cliponaxis: false,
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
    $("speed-sub").textContent = "reference lap " + rd + " (" + e.reference.team + ") " + lapTime(e.reference.lap_time_s) + (have.length ? " vs " + have.map(function (x) { return x + " " + lapTime(D.drivers[x].lap_time_s); }).join(", ") : "");
    // Corner labels along the top; on a phone-width chart they would run into each other
    var ann = $("ch-speed").clientWidth < 600 ? [] : D.corners.map(function (c) { return { x: c.distance_m, yref: "paper", y: 1, yanchor: "bottom", text: c.label, showarrow: false, font: { size: 9, color: t.muted, family: t.mono } }; });
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
    $("map-sub").textContent = fullName(dv) + " vs " + e.reference.driver + " · ms lost (red) or gained (blue) per 100 m";
    var cx = D.corners.map(function (c) { return interp(D.distance_m, mp.x, c.distance_m); }), cy = D.corners.map(function (c) { return interp(D.distance_m, mp.y, c.distance_m); });
    plot("ch-map", [
      { x: mp.x, y: mp.y, type: "scatter", mode: "markers", marker: { size: 6, color: loss, cmin: -cap, cmid: 0, cmax: cap,
        colorscale: [[0, t.ref], [0.5, t.rule], [1, t.loss]], colorbar: { title: { text: "ms/100 m", font: { size: 10, color: t.muted } }, thickness: 8, len: 0.6, tickfont: { size: 10, color: t.muted }, outlinewidth: 0 } },
        customdata: D.distance_m.map(function (s, i) { return [s, loss[i]]; }), hovertemplate: "%{customdata[0]:.0f} m: %{customdata[1]:+.0f} ms per 100 m<extra></extra>" },
      { x: cx, y: cy, text: D.corners.map(function (c) { return c.label; }), type: "scatter", mode: "text", textfont: { size: 10, color: t.ink2, family: t.mono }, hoverinfo: "skip" },
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
    $("straight-sub").textContent = f(s.start_m, 0) + "–" + f(s.end_m, 0) + " m from the line · grey band = range of the other teams";
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
    if (e.reference.driver !== e.fastest_lap.driver) n.push("The reference lap is " + esc(e.reference.driver) + "’s " + lapTime(e.reference.lap_time_s) + ": the fastest lap (" + esc(e.fastest_lap.driver) + "’s) has no telemetry that passes the data checks. Lap-time gaps use the fastest lap; section and corner times use the reference lap.");
    if (e.wet) n.push("Wet qualifying: kept here, left out of the season analyses.");
    (D.flagged_corners || []).filter(function (c) { return ds.indexOf(c.driver) >= 0; }).forEach(function (c) {
      n.push(esc(c.driver) + " at " + esc(c.corner + (c.name ? " " + c.name : "")) + ": the speed channel reads " + f(c.wheel_kmh, 0) + " km/h and GPS " + f(c.gps_kmh, 0) + " km/h (" + sgn(c.wheel_kmh - c.gps_kmh, 0) +
        " km/h), against " + sgn(c.field_offset_kmh, 0) + " km/h for the median car at that corner, so the reading is " + f(Math.abs(c.residual_kmh), 0) + " km/h out of line with the other cars’ and that minimum speed is not used.");
    });
    if (!e.race && e.race_note) n.push("Race pace: " + esc(e.race_note) + ".");
    $("det-notes").innerHTML = n.map(function (x) { return "<li>" + x + "</li>"; }).join("");
  }

  function renderDetail(t) {
    t = t || theme();
    var e = current.entry, D = current.detail, ds = selDrivers();
    var ids = ["ch-order", "ch-rival", "ch-speed", "ch-delta", "ch-map", "ch-det-rates", "ch-corners", "ch-straight", "ch-ftl", "ch-det-race"];
    if (!e || !D || D.key !== e.key) {
      var why = !e ? "Pick at least one track in the bar at the top." : (current.failed || []).indexOf("track") >= 0 ? "Could not load this track’s data file." : "Loading…";
      fill("detail_text", esc(why)); $("det-tiles").innerHTML = ""; $("det-notes").innerHTML = ""; $("tbl-corners").innerHTML = "";
      ["rival-sub", "speed-sub", "map-sub", "straight-sub", "trk-hint"].forEach(function (id) { $(id).textContent = ""; });
      ["seg-map", "seg-straight"].forEach(function (id) { $(id).innerHTML = ""; $(id).onclick = null; });
      $("det-race-fig").hidden = true;
      ids.forEach(function (id) { empty(id, why); });
      return;
    }
    $("trk-hint").textContent = e.wet ? "wet session" : "";
    detailText(e, D, ds); detailTiles(t, e, D, ds);
    renderOrder(t, e, D); renderRival(t, e, D, ds); renderSpeed(t, e, D, ds); renderMap(t, e, D, ds);
    renderDetailRates(t, e, D, ds); renderCorners(t, e, D, ds); renderStraight(t, e, D, ds); renderDetailRace(t, e, D, ds);
    detailNotes(e, D, ds);
  }

  // ------------------------------------------------------------------ upgrades (season)
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
    plot("ch-grip26", [{ x: gs.map(function (r) { return short(r.event); }), y: gs.map(function (r) { return loo[r.round].ratio; }), type: "scatter", mode: "lines+markers",
      error_y: { type: "data", array: gs.map(function (r) { return 1.645 * loo[r.round].se; }), color: t.amr, thickness: 1, width: 0 },
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.3f} of the other teams' median<extra></extra>", connectgaps: true }],
      layout(t, { yaxis: { title: { text: "ratio to other teams' median" }, tickformat: ".2f" }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, gs, season).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, season) }));
    plot("ch-straight26", [{ x: series.map(function (r) { return short(r.event); }), y: series.map(function (r) { return r.straight_speed_delta_kmh; }), type: "scatter", mode: "lines+markers",
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.1f} km/h<extra></extra>", connectgaps: true }],
      layout(t, { yaxis: { title: { text: "km/h vs field median" } }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, series, season).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, season) }));
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
        '<span class="pill ' + (e.lead_p_holm <= 0.1 ? "yes" : "no") + '">' + verdict(e) + "</span>" + (e.overlapping && e.overlapping.length ? ' <span class="hint">overlaps ' + e.overlapping.map(short).join(", ") + "</span>" : "") +
        (detectable ? "" : ' <span class="hint">below detectable size</span>') + "</td></tr>";
    });
    var floors = [].concat.apply([], eff.map(function (e) { return [1 / (1 + e.n_team_placebos), 1 / (1 + e.n_time_placebos)]; })).filter(isFinite);
    $("tbl-did").innerHTML = "<caption>Declared upgrades, both seasons: difference-in-differences, 4 events either side. A placebo p cannot go below 1 / (1 + number of placebos): " +
      f(Math.min.apply(null, floors), 2) + "–" + f(Math.max.apply(null, floors), 2) + " here.</caption>" +
      '<thead><tr><th>Upgrade</th><th class="num">Effect on gap</th><th class="num">Detectable</th><th class="num">Events pre / post</th><th class="num">p vs rivals</th><th class="num">p vs own dates</th><th>Reference used</th><th class="num">Holm-adjusted</th><th>Verdict</th></tr></thead><tbody>' +
      rows.join("") + '</tbody><tfoot><tr><td colspan="9" class="hint">Each upgrade is compared with rivals given the same date (team placebos) and with Aston Martin at its other dates (time placebos). When Aston Martin’s own estimates are much noisier than its rivals’ (noise ratio above 1.5), only the second is a fair reference. Detectable = the effect the reference test finds with 80% power at the 10% level. With ' +
      eff.length + " upgrades tested, the smallest Holm-adjusted p any of them could reach is " + f(up.holm_floor_lead, 2) + ", so none can be called significant after correction whatever its size.</td></tr></tfoot>";
  }

  // ------------------------------------------------------------------ aero map (season)
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
        // dt = s_cla * x + s_cda * y  ->  y = (dt - s_cla x) / s_cda
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
      hovertemplate: "%{hovertext}<br>downforce-equiv %{x:.1f}%<br>drag-equiv %{y:.1f}%<br>%{customdata[0]} events · mean quali gap %{customdata[1]:.2f}%<extra></extra>" };
    plot("ch-aero", lines.concat([pts]), layout(t, {
      xaxis: { title: { text: "downforce-equivalent vs field, % (→ more)" }, range: [-lim, lim] },
      yaxis: { title: { text: "drag-equivalent vs field, % (↑ more drag / less speed)" }, range: [-lim / 2, lim / 2] },
      annotations: [{ xref: "paper", yref: "paper", x: 1, y: 0, xanchor: "right", yanchor: "bottom", showarrow: false, font: { size: 11, color: t.muted },
        text: "1% C<sub>L</sub>A = " + f(sens.cla_plus_1pct_s, 3) + " s · 1% C<sub>D</sub>A = +" + f(sens.cda_plus_1pct_s, 3) + " s" }] }));
    var amr = teams.filter(function (r) { return r.team === TARGET; })[0];
    fill("aero_text", amr ? "High-speed cornering grip is turned into a downforce-equivalent using each event’s aero share of grip, and straight-line peak speed into a drag-equivalent (v ∝ C<sub>D</sub>A<sup>−1/3</sup>). In " + state.season +
      " Aston Martin sits at " + sgn(amr.d_cla_equiv_pct[0], 1) + "% downforce-equivalent and " + sgn(amr.d_cda_equiv_pct[0], 1) +
      "% drag-equivalent against the field median. The drag axis mixes drag with power, so read it alongside the power analysis above. Dotted lines join set-ups with equal lap time, from the calibrated lap simulator." : "");
  }

  function renderSens(t) {
    t = t || theme();
    var rows = (S.circuit_sensitivities || []).slice().sort(function (a, b) { return a.cda_pct_per_cla_pct - b.cda_pct_per_cla_pct; });
    var x = rows.map(function (r) { return short(r.event) + " " + String(r.season).slice(2); });
    plot("ch-sens", [
      { x: x, y: rows.map(function (r) { return r.cla_m2_plus_1pct_s; }), name: "+1% downforce", type: "bar", marker: { color: t.amr }, hovertemplate: "%{x}<br>+1% ClA: %{y:.3f} s<extra></extra>" },
      { x: x, y: rows.map(function (r) { return r.cda_m2_plus_1pct_s; }), name: "+1% drag", type: "bar", marker: { color: t.third }, hovertemplate: "%{x}<br>+1% CdA: %{y:.3f} s<extra></extra>" },
    ], layout(t, { barmode: "group", bargap: 0.25, bargroupgap: 0.08, showlegend: true, yaxis: { title: { text: "lap-time change, s" } }, xaxis: { tickangle: -50 } }));
  }

  // ------------------------------------------------------------------ lap sim and energy (focus track)
  function lapDataMissing() {
    return !current.entry ? "Pick a track in Track detail." : (current.failed || []).indexOf("lap") >= 0 ? "Could not load this track’s lap data." : "Loading…";
  }
  function renderSim(t) {
    t = t || theme();
    var e = current.event;
    var key = e && e.sandbox ? e.sandbox.car : null;
    var ls = key && e.lapsim ? e.lapsim[key] : null;
    if (!ls) {
      $("sim-sub").textContent = !e ? "" : short(e.event) + " " + e.season + ": no calibration for this event (geometry check failed)";
      ["ch-sim", "ch-disc"].forEach(function (id) { empty(id, e ? "No calibrated lap for this track." : lapDataMissing()); });
      $("tbl-params").innerHTML = "";
      $("sandbox").hidden = true; SB.base = null;
      return;
    }
    var d = e.map.distance_m.slice(0, ls.trace.observed_kmh.length);
    $("sim-sub").textContent = short(e.event) + " " + e.season + " · " + ls.driver + " · RMSE " + f(ls.rmse_kmh, 1) + " km/h · lap-time error " + sgn(ls.lap_time_error_s, 3) + " s";
    plot("ch-sim", [
      { x: d, y: ls.trace.observed_kmh, name: "measured", type: "scatter", mode: "lines", line: { color: t.amr, width: 1.6 } },
      { x: d, y: ls.trace.sim_kmh, name: "simulated", type: "scatter", mode: "lines", line: { color: t.ink2, width: 1.2, dash: "dot" } },
    ], layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } } }));
    var m = ls.trace.disc_mean_kmh, sd = ls.trace.disc_sd_kmh;
    plot("ch-disc", [
      { x: d, y: m.map(function (v, i) { return v + 2 * sd[i]; }), type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: d, y: m.map(function (v, i) { return v - 2 * sd[i]; }), type: "scatter", mode: "lines", fill: "tonexty", fillcolor: hexA(t.field, 0.3), line: { width: 0 }, hoverinfo: "skip" },
      { x: d, y: m, type: "scatter", mode: "lines", line: { color: t.third, width: 1.6 }, hovertemplate: "%{x:.0f} m: %{y:+.1f} km/h<extra></extra>" },
    ], layout(t, { hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
    var names = { mu: ["Grip coefficient μ", 1, ""], cla_m2: ["Downforce C<sub>L</sub>A", 1, " m²"], cda_m2: ["Drag C<sub>D</sub>A", 1, " m²"], power_w: ["Wheel power", 1e-3, " kW"],
      long_grip_scale: ["Braking/traction grip ratio", 1, ""], low_drag_cda_m2: ["Drag with DRS open", 1, " m²"] };
    var mc = ls.mcmc_check;
    var PRIOR_SD = { mu: 0.35, cla_m2: 0.45, cda_m2: 0.45, power_w: 0.30, long_grip_scale: 0.25, low_drag_cda_m2: 0.45 };
    var rows = ls.param_names.map(function (n, i) {
      var p = ls.params[n], nm = names[n] || [n, 1, ""];
      var dig = n === "power_w" ? 0 : 2;
      var postSd = (Math.log(p.hi) - Math.log(p.lo)) / (2 * 1.645);
      return "<tr><td>" + nm[0] + '</td><td class="num">' + f(p.median * nm[1], dig) + nm[2] + '</td><td class="num">' + f(p.lo * nm[1], dig) + " – " + f(p.hi * nm[1], dig) + '</td><td class="num">' + f(postSd / PRIOR_SD[n], 2) + "</td>" +
        (mc ? '<td class="num">' + f(mc.laplace_sd_log[i], 2) + " / " + f(mc.mcmc_sd_log[i], 2) + "</td>" : "") + "</tr>";
    });
    $("tbl-params").innerHTML = "<caption>Calibrated parameters, " + esc(ls.driver) + " · effective sample size " + f(ls.n_effective, 0) + " of " + ls.trace.observed_kmh.length * 2 + " points</caption>" +
      '<thead><tr><th>Parameter</th><th class="num">Median</th><th class="num">90% interval</th><th class="num">Posterior / prior width</th>' + (mc ? '<th class="num">log-sd Laplace / MCMC</th>' : "") + "</tr></thead><tbody>" + rows.join("") +
      '</tbody><tfoot><tr><td colspan="5" class="hint">Widths near 1 mean the lap barely constrains that parameter beyond the prior. Residuals are strongly autocorrelated (effective sample size ' + f(ls.n_effective, 0) + "), so these are effective, prior-informed values; downstream sensitivities use the medians.</td></tr></tfoot>";
    sandboxInit(e);
  }

  function renderCalAcc(t) {
    t = t || theme();
    var rows = (S.calibration_accuracy || []).filter(function (r) { return r.is_pole; });
    var by = byKey(rows, "season");
    plot("ch-calacc", Object.keys(by).sort().map(function (season) {
      var r = by[season];
      return { x: r.map(function (x) { return short(x.event); }), y: r.map(function (x) { return x.lap_time_error_s; }), name: season, type: "scatter", mode: "markers",
        marker: { size: 9, color: season === "2026" ? t.amr : t.third, line: { color: t.surface, width: 2 } },
        error_y: { type: "data", array: r.map(function (x) { return 1.645 * x.posterior_lap_time_sd_s; }), color: season === "2026" ? t.amr : t.third, thickness: 1, width: 0 },
        customdata: r.map(function (x) { return [x.driver, x.rmse_kmh]; }), hovertemplate: season + " %{x}<br>%{customdata[0]}: %{y:+.3f} s · RMSE %{customdata[1]:.1f} km/h<extra></extra>" };
    }), layout(t, { showlegend: true, yaxis: { title: { text: "simulated − actual lap, s" } }, xaxis: { tickangle: -50 },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
    var e25 = (by["2025"] || []).map(function (x) { return Math.abs(x.lap_time_error_s); }), e26 = (by["2026"] || []).map(function (x) { return Math.abs(x.lap_time_error_s); });
    fill("calacc_text", "Pole laps, every event with clean geometry. Median absolute lap-time error " + f(median(e25), 2) + " s in 2025 and " + f(median(e26), 2) +
      " s in 2026. The 2026 fits are weaker, consistent with power falling with time along a straight (energy deployment), which a constant-power point-mass model cannot represent; the discrepancy chart shows where the fit misses.");
  }

  // sandbox
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
    $("sb-delta").textContent = Math.abs(dt) < 0.0005 ? "baseline (simulated)" : sgn(dt, 3) + " s vs baseline";
  }
  ["s-cla", "s-cda", "s-pow", "s-mass"].forEach(function (id) { var el = $(id); if (el) el.addEventListener("input", sandboxRun); });
  if ($("sb-reset")) $("sb-reset").addEventListener("click", function () { ["s-cla", "s-cda", "s-pow", "s-mass"].forEach(function (id) { $(id).value = 0; }); sandboxRun(); });

  function renderEnergy(t) {
    t = t || theme();
    var e = current.event;
    if (e && e.energy_speed) {
      var d = e.map.distance_m, keys = Object.keys(e.energy_speed);
      var amrKey = keys.filter(function (k) { return k !== e.pole.driver; })[0];
      $("energy-sub").textContent = short(e.event) + " " + e.season + " · reference lap (" + e.pole.driver + ")" + (amrKey ? " and the fastest passing Aston Martin lap (" + amrKey + ")" : " only: no Aston Martin lap passed the data checks");
      var cols = {}; cols[e.pole.driver] = t.ref; if (e.comparison) cols[e.comparison.target] = t.amr;
      plot("ch-energy", keys.map(function (k) { return { x: d, y: e.energy_speed[k], name: k, type: "scatter", mode: "lines", line: { color: cols[k] || t.field, width: 1.5 }, hovertemplate: k + " %{x:.0f} m: %{y:.0f} km/h<extra></extra>" }; }),
        layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } } }));
    } else { $("energy-sub").textContent = ""; empty("ch-energy", e ? "No speed traces for this track." : lapDataMissing()); }
    var en = (S.energy || []).filter(function (r) { return r.season === 2026; }).sort(function (a, b) { return a.clip_time_loss_s - b.clip_time_loss_s; });
    var en25 = (S.energy || []).filter(function (r) { return r.season === 2025; });
    plot("ch-clip", [{ y: en.map(function (r) { return r.team; }), x: en.map(function (r) { return r.clip_time_loss_s; }), type: "bar", orientation: "h",
      marker: { color: en.map(function (r) { return r.team === TARGET ? t.amr : t.field; }) },
      customdata: en.map(function (r) { return [r.clip_speed_drop_kmh, r.clip_decel_distance_m]; }),
      hovertemplate: "%{y}<br>%{x:.3f} s/lap · speed drop %{customdata[0]:.1f} km/h · %{customdata[1]:.0f} m decelerating<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "s per lap (2026)" } } }));
    var fieldLoss = mean(en.map(function (r) { return r.clip_time_loss_s; }));
    var loss25 = mean(en25.map(function (r) { return r.clip_time_loss_s; }));
    var rt = (REL26.clip_time_loss_s || {});
    fill("energy_text", "In 2026 cars reach peak speed part-way along a straight and then slow down at full throttle. Speed-dependent power alone, including the regulated MGU-K taper, cannot do that; it means power falls with time as deployment ends or the car harvests. Acceleration here has gravity removed using GPS altitude, and only decelerations lasting at least 30 m count. The field loses on average " +
      f(fieldLoss, 3) + " s per lap against holding peak speed, against " + f(loss25, 3) + " s in 2025. Aston Martin's loss on this measure (" + sgn(rt.mean, 3) + " s vs the other teams, CI " + f(rt.lo, 3) + " to " + f(rt.hi, 3) +
      ")" + (rt.lo > 0 ? " is larger than the field's and the largest of any team on this measure, but it is small next to its whole straight-line deficit, so this narrow measure of clipping does not by itself explain it."
        : rt.hi < 0 ? " is smaller than the field's, so clipping on this measure does not explain its straight-line deficit."
        : " is not distinguishable from the field, so this narrow measure of clipping does not by itself explain its straight-line deficit."));
  }

  // ------------------------------------------------------------------ models (deficit chart: season)
  function renderModels(t) {
    t = t || theme();
    var cm = S.corner_model || {};
    var names = { steady: "Steady-state formula (aero term not identified: v = √(aR))", physics: "Lap sim on track geometry, nominal car from training events", ml: "Gradient boosting only", hybrid: "Hybrid: lap sim + boosted residual" };
    $("tbl-cm").innerHTML = "<caption>Out of sample by whole circuit (" + cm.n_circuits + " circuits, " + cm.n_events + " events, " + (cm.n_corners || "–") + " corners, " + cm.n_rows + " car-corner speeds)</caption>" +
      '<thead><tr><th>Model</th><th class="num">RMSE</th><th class="num">R²</th><th class="num">Within-corner R²</th></tr></thead><tbody>' +
      (cm.metrics || []).map(function (r) { return "<tr><td>" + names[r.model] + '</td><td class="num">' + f(r.rmse_kmh, 1) + ' km/h</td><td class="num">' + f(r.r2, 3) + '</td><td class="num">' + (r.model === "steady" || r.model === "physics" ? "n/a" : f(r.within_corner_r2, 2)) + "</td></tr>"; }).join("") +
      '</tbody><tfoot><tr><td colspan="4" class="hint">Within-corner R² is n/a for the physics-only models: they predict the same speed for every car at a corner.</td></tr></tfoot>';
    var mm = {}; (cm.metrics || []).forEach(function (r) { mm[r.model] = r; });
    var ce = cm.coverage_by_event || {};
    fill("corner_text", "Predicts each corner’s minimum speed at a circuit the model has never seen (every event there, in both seasons, is held out together). The physics baseline runs the lap simulator on the held-out track’s GPS geometry with a nominal car calibrated only on the training events, with nothing fitted to the held-out circuit. On unseen circuits it beats a black-box model clearly (R² " +
      f((mm.physics || {}).r2, 2) + " vs " + f((mm.ml || {}).r2, 2) + "), and adding machine learning on top changes little (" + f((mm.hybrid || {}).r2, 2) + "). Almost all of the variance is between corners, so R² mostly measures geometry: none of the models explains differences between cars at the same corner (within-corner R² ≈ 0 or below). Split-conformal 90% intervals cover " +
      f(cm.conformal_coverage * 100, 1) + "% of held-out corners overall, but coverage varies by event (median " + f(ce.median * 100, 0) + "%, worst " + f(ce.min * 100, 0) + "%, " + f(ce.share_below_80pct * 100, 0) + "% of events below 80%).");
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
        hovertemplate: "%{y} · " + cl + "-speed<br>%{x:+.1f} km/h<extra></extra>" };
    }), layout(t, { showlegend: true, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "km/h vs expectation" } },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderModelsFixed(t) {
    t = t || theme();
    var vs = S.variance_split || {}, yrs = Object.keys(vs).sort();
    plot("ch-var", [{ y: yrs, x: yrs.map(function (y) { return vs[y].median_event_share * 100; }), type: "scatter", mode: "markers", marker: { size: 12, color: t.amr, line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: yrs.map(function (y) { return (vs[y].event_share_iqr[1] - vs[y].median_event_share) * 100; }), arrayminus: yrs.map(function (y) { return (vs[y].median_event_share - vs[y].event_share_iqr[0]) * 100; }), color: t.amr, thickness: 1.5, width: 0 },
      hovertemplate: "%{y}: %{x:.0f}% between teams (median event)<extra></extra>" }],
      layout(t, { margin: { l: 50, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "% of variance between teams (car)" }, range: [0, 100] }, yaxis: { type: "category" } }));
    if (yrs.length === 2) fill("var_text", "Within each event, qualifying gaps are split into a between-team part (mostly the car, but also how drivers are sorted into teams) and a within-team part (driver, lap execution, session and track evolution). Laps slower than 107% of the best are left out as non-representative (" +
      (S.laps_outside_107pct || 0) + " laps). In the median event the between-team share was " + f(vs[yrs[0]].median_event_share * 100, 0) + "% in " + yrs[0] + " (middle half of events " + f(vs[yrs[0]].event_share_iqr[0] * 100, 0) + "–" + f(vs[yrs[0]].event_share_iqr[1] * 100, 0) +
      "%) and " + f(vs[yrs[1]].median_event_share * 100, 0) + "% in " + yrs[1] + " (" + f(vs[yrs[1]].event_share_iqr[0] * 100, 0) + "–" + f(vs[yrs[1]].event_share_iqr[1] * 100, 0) + "%). Pooled over events the between-team share is " + f(vs[yrs[0]].car_share * 100, 0) + "% (CI " + f(vs[yrs[0]].car_share_ci90[0] * 100, 0) + "–" + f(vs[yrs[0]].car_share_ci90[1] * 100, 0) + "%) in " + yrs[0] + " and " +
      f(vs[yrs[1]].car_share * 100, 0) + "% (" + f(vs[yrs[1]].car_share_ci90[0] * 100, 0) + "–" + f(vs[yrs[1]].car_share_ci90[1] * 100, 0) + "%) in " + yrs[1] + ". Under the 2026 rules the qualifying order is set almost entirely by the teams, car and driver line-up together, rather than by differences between teammates.");

    var wt = S.wind_rotation_test || {};
    var ang = Object.keys(wt.mean_relative_sse || {}).map(Number).sort(function (x, y) { return x - y; });
    plot("ch-wind", [{ x: ang, y: ang.map(function (a0) { return wt.mean_relative_sse[a0]; }), type: "scatter", mode: "lines+markers",
      line: { color: t.ref, width: 2 }, marker: { size: 8, color: ang.map(function (a0) { return a0 === 0 ? t.third : t.ref; }), line: { color: t.surface, width: 1.5 } },
      hovertemplate: "wind rotated %{x}°: %{y:.3f} of the ground-speed residual<extra></extra>" }],
      layout(t, { margin: { l: 56, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "rotation applied to the wind direction, °" }, dtick: 60 },
        yaxis: { title: { text: "residual / no-wind residual" } },
        shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t.muted, width: 1, dash: "dot" } }] }));
    fill("wind_text", "Wind components need the compass orientation of the timing X/Y frame, which the archive does not document. If both the orientation and the wind data were good, adding wind to the drag term should explain full-throttle acceleration better than ground speed, and best at 0° rotation. Across " +
      (wt.n_events || 0) + " windy sessions no rotation improves the fit by more than a few percent, and the assumed orientation was best in " + f((wt.share_events_assumed_orientation_best || 0) * 100, 0) + "% of them, about what chance gives (1 in 12). Session-level wind readings are not informative enough to use, so dynamic pressure uses ground speed and no wind effect is claimed.");
    var dsum = S.deficit_summary || {}, d6 = dsum["2026"] || {}, d5 = dsum["2025"] || {};
    fill("accounting_text", "Giving the pole car’s calibrated simulator Aston Martin’s measured grip and straight-line figures accounts for " + f(d6.ratio_of_means * 100, 0) + "% of the mean 2026 gap over the " + d6.n_events +
      " events where it can be run. The interval includes the uncertainty in the grip ratios and is wide, " + f((d6.ratio_ci90 || [])[0] * 100, 0) + "–" + f((d6.ratio_ci90 || [])[1] * 100, 0) +
      "%, so it shows that the measured deficits are of the right size to explain the gap, not how the gap splits. Across those events it " +
      (d6.r2_event_level > 0.3 ? "tracks the event-to-event changes (R² " + f(d6.r2_event_level, 2) + ", Spearman " + f(d6.spearman, 2) + ")" :
        "ranks them " + (d6.spearman > 0.6 ? "roughly" : "poorly") + " (Spearman " + f(d6.spearman, 2) + ") but does not predict individual events (R² " + f(d6.r2_event_level, 2) + ")") +
      ". In 2025, when the gap averaged " + f(d5.mean_actual_s, 2) + " s against " + f(d6.mean_actual_s, 2) + " s, the same accounting gives " + f(d5.ratio_of_means * 100, 0) + "% (" + f((d5.ratio_ci90 || [])[0] * 100, 0) + "–" + f((d5.ratio_ci90 || [])[1] * 100, 0) + "%) and R² " + f(d5.r2_event_level, 1) +
      ": it does not resolve small gaps. It is an accounting in physical terms, not a forecast: the grip ratios come from the same laps.");
  }

  // ------------------------------------------------------------------ method
  function renderMethod() {
    var dq = S.data_quality || {};
    $("dq").innerHTML = [
      ["Laps passing data checks", dq.laps_passed + " of " + dq.laps_total],
      ["GPS vs car-data clock offset (median)", f(dq.gps_lag_s_median, 2) + " s, corrected per lap"],
      ["GPS fix RMS to reference line (median)", f(dq.projection_rms_m_median, 2) + " m"],
      ["Events with failed geometry check", (dq.events_geometry_failed || []).length + " (curvature fits skipped)"],
    ].map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("");
    $("skipped").innerHTML = (S.skipped_events || []).map(function (s) {
      var missing = (s.reason.match(/(?:Qualifying|Race)\/([\w.]+\.json)/) || [])[1];
      var why = /Only \d+ laps passed/.test(s.reason) ? "telemetry failed automated data checks (dropouts, GPS/odometer mismatch)"
        : missing ? "the archive has no " + missing + " for this event" : s.reason;
      return "<li>" + s.season + " " + esc(s.event) + ": " + esc(why) + "</li>";
    }).join("") + (dq.events_geometry_failed || []).map(function (e) { return "<li>" + esc(e) + ": kept for timing analyses, excluded from curvature-based fits (turning number check)</li>"; }).join("");
    fill("method_html",
      "<h3>Pipeline</h3><p>Fastest valid qualifying lap of every driver at every event, resampled onto a shared distance grid by projecting GPS fixes onto the pole lap’s line. Time comes from the measured timing channel and closes exactly on the official lap time. The archive’s GPS stream runs about " + f(dq.gps_lag_s_median, 2) +
      " s ahead of the car-data stream; left uncorrected that misplaces samples by " + f((dq.gps_lag_s_median || 0) * 300 / 3.6, 0) + " m at 300 km/h. Each lap’s offset is estimated by matching GPS-derived speed to the wheel-speed sensor.</p>" +
      "<p>Track curvature is the median over all drivers of a time-domain smoothing spline through the raw ~4 Hz GPS fixes. The smoothing level is chosen per event by the same speed cross-check, and each event's curvature must integrate to the circuit's own turn count (zero for figure-of-eight Suzuka).</p>" +
      "<h3>Track views</h3><p>The track-by-track and track-detail views compare each Aston Martin driver’s fastest qualifying lap that passed the data checks with the event’s reference lap: the fastest lap that passes every check" + (function () {
        var r = S.reference_not_fastest || [];
        return r.length ? " (the fastest lap of qualifying at every event but " + list(r.map(function (x) { return x.season + " " + esc(short(x.event)) + ", where " + esc(x.fastest) + "’s lap has no usable telemetry and " + esc(x.reference) + "’s is used"; })) + ")" : " (the fastest lap of qualifying at every event)";
      })() + ". Section and corner times add up to the gap between the two laps. Each other team is represented by its fastest passing lap. Loss rates over several tracks are sums of seconds over sums of the reference lap’s seconds, as in the season analysis, but without intervals: a handful of tracks is too few for them. Corner minimum speeds count only where the speed channel agrees with GPS.</p>" +
      "<h3>What the numbers can and cannot say</h3><p>Grip, downforce and drag figures are effective values for a point-mass car: load transfer and tyre load sensitivity are folded in, so absolute μ and C<sub>L</sub>A are not separable from public data and are reported only as comparisons at matched dynamic pressure. Mass is the regulation minimum plus an assumed 5 kg of fuel. The power analysis measures deployed wheel power, which includes energy strategy. Correlation with declared upgrades is evidence, not proof: four events either side is a short window, and track layouts differ.</p>");
  }

  // ------------------------------------------------------------------ boot
  function syncHeaderOffset() {
    var h = document.querySelector(".masthead");
    if (h) document.documentElement.style.scrollPaddingTop = (h.getBoundingClientRect().height + 8) + "px";
  }

  function start() {
    initState();
    syncHeaderOffset();
    window.addEventListener("resize", syncHeaderOffset);
    heroText();
    buildFilters();
    status();
    [renderProfile, renderHalves, renderJoint, renderSens, renderCalAcc, renderModelsFixed].forEach(function (fn) { register("fixed", fn); });
    [renderRates, renderUpgradeParts, renderGap, renderCP, renderAero, renderModels].forEach(function (fn) { register("season", fn); });
    [renderTracks, renderRace].forEach(function (fn) { register("tracks", fn); });
    current.entry = entry(state.focus[state.season]);  // the detail shows "Loading…" until its files arrive
    [renderDetail, renderSim, renderEnergy].forEach(function (fn) { register("detail", fn); });
    renderDiD(); renderMethod();
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
