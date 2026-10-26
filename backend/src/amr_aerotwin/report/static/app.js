/* Report front end. All numbers come from window.SEASON (season analyses) and the
   per-event files in data/events/, written by `aerotwin report`. */
(function () {
  "use strict";
  var S = window.SEASON, M = window.MANIFEST || [];
  var TARGET = "Aston Martin";
  var renderers = [];
  var current = { event: null, aeroSeason: "2026", gapSeason: "2026", deficitSeason: "2026" };

  // ------------------------------------------------------------------ helpers
  function $(id) { return document.getElementById(id); }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function f(x, d) { return x == null || !isFinite(x) ? "–" : Number(x).toFixed(d == null ? 1 : d); }
  function sgn(x, d) { return x == null || !isFinite(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d == null ? 1 : d); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function short(ev) { return ev.replace(" Grand Prix", ""); }
  function fill(key, html) { document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (el) { el.innerHTML = html; }); }
  function byKey(arr, k) { var o = {}; arr.forEach(function (r) { (o[r[k]] = o[r[k]] || []).push(r); }); return o; }
  function mean(a) { a = a.filter(function (v) { return v != null && isFinite(v); }); return a.length ? a.reduce(function (s, v) { return s + v; }, 0) / a.length : NaN; }

  function theme() {
    return { ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), rule: css("--rule"), surface: css("--surface"),
      amr: css("--amr"), ref: css("--ref"), third: css("--third"), field: css("--field"), bg: css("--bg"),
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
    out.xaxis = axis(t, (extra || {}).xaxis); out.yaxis = axis(t, (extra || {}).yaxis);
    ["xaxis2", "yaxis2"].forEach(function (k) { if (extra && extra[k]) out[k] = axis(t, extra[k]); });
    return out;
  }
  function plot(id, traces, lay) {
    var el = $(id); if (!el || !window.Plotly) return;
    Plotly.react(el, traces, lay, { displayModeBar: false, responsive: true });
  }
  function register(fn) { renderers.push(fn); fn(); }
  function rerender() { var t0 = theme(); renderers.forEach(function (fn) { try { fn(t0); } catch (e) { console.error(e); } }); }

  function seg(containerId, options, value, onChange) {
    var c = $(containerId); if (!c) return;
    c.innerHTML = options.map(function (o) { return '<button type="button" role="tab" data-v="' + o + '" aria-selected="' + (o === value) + '">' + o + "</button>"; }).join("");
    c.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      c.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-selected", x === b ? "true" : "false"); });
      onChange(b.getAttribute("data-v"));
    });
  }

  // ------------------------------------------------------------------ headline text
  var PT26 = ((S.powertrain || {})["2026"] || {})[TARGET] || {};
  var PT25 = ((S.powertrain || {})["2025"] || {})[TARGET] || {};
  var DS26 = ((S.deficit_summary || {})["2026"]) || {};
  var UPG = (S.upgrade_components || []).filter(function (u) { return u.season === 2026; })[0];
  var CP26 = (S.changepoints || {})["2026"] || {};

  function bandClaim(bands) {
    var neg = bands.filter(function (b) { return b.d_ax_hi < 0; });
    if (!bands.length) return "the speed bands tested";
    var lo = bands[0].band_kmh, hi = bands[bands.length - 1].band_kmh + 20;
    return neg.length + " of " + bands.length + " speed bands between " + lo + " and " + hi + " km/h (90% interval below zero)";
  }

  function heroText() {
    var ci = PT26.power_deficit_ci90 || [];
    fill("n_events", String(S.n_events));
    fill("hero_lede",
      "Across " + PT26.n_events_200plus + " Grands Prix in 2026, the Aston Martin accelerates worse than the field in " + bandClaim(PT26.bands || []) + ", by about <strong>" +
      f(-PT26.power_deficit_kw_200plus, 0) + " kW</strong> of wheel power (90% interval " + f(-ci[1], 0) + "–" + f(-ci[0], 0) +
      " kW). The deficit is flat across speed, which is the signature of missing deployed power. Extra drag would grow with the cube of speed. In 2025, with the same chassis team and a Mercedes power unit, the same test shows " +
      f(-PT25.power_deficit_kw_200plus, 0) + " kW. Fed into the calibrated lap simulator, the 2026 power gap is worth about <strong>" + f(DS26.mean_power_s, 1) + " s per lap</strong>.");
    var before = UPG && UPG.before.grip_high_rel, after = UPG && UPG.after.grip_high_rel;
    var tiles = [
      { k: "Deployed-power deficit, 2026", v: "−" + f(-PT26.power_deficit_kw_200plus, 0) + " kW", ci: "90% CI " + f(-ci[1], 0) + " to " + f(-ci[0], 0) + " kW · " + PT26.n_events_200plus + " events", amr: true },
      { k: "Lap time of that deficit", v: f(DS26.mean_power_s, 1) + " s", ci: "per lap, calibrated lap sim · " + DS26.n_events + " events" },
      { k: "Fast-corner grip vs field", v: before ? f(before.mean * 100, 1) + " → " + f(after.mean * 100, 1) + "%" : "–", ci: "before vs after the Hungary B-spec" },
      { k: "Gap explained by physics", v: f(DS26.explained_share * 100, 0) + "%", ci: "of the 2026 gap to pole · r = " + f(DS26.correlation, 2) },
    ];
    $("tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile"><span class="k">' + t.k + '</span><span class="v' + (t.amr ? " amr" : "") + '">' + t.v + '</span><span class="ci">' + t.ci + "</span></div>";
    }).join("");
    fill("hero_note", "“Deployed power” is wheel power actually used, so it includes energy-management strategy as well as the power unit itself. Active-aero and ERS state are not published in 2026, so the analysis works from speed alone.");
    var ptAll = (S.powertrain || {})["2026"] || {};
    var drag = Object.keys(ptAll).filter(function (k) { return ptAll[k].slope > 1.5 && ptAll[k].power_deficit_kw_200plus < -5; });
    fill("finding_text", "Aston Martin’s deficit has a log-log slope of " + f(PT26.slope, 1) + " against speed: flat, so power-like. " +
      (drag.length ? drag.join(" and ") + " also lose on the straights, but their deficits rise steeply with speed (slopes above 1.5), which points to drag rather than power. " : "") +
      "Speeds are capped at 285 km/h in 2026, below the regulated MGU-K taper, so every car is compared under the same electrical limit.");
    fill("decomp_text", "For each event the pole car’s calibrated simulator is given Aston Martin’s measured grip at low and high dynamic pressure and its power deficit. The prediction reproduces " +
      f(DS26.explained_share * 100, 0) + "% of the actual gap on average (mean " + f(DS26.mean_actual_s, 2) + " s actual vs " + f(DS26.mean_predicted_s, 2) +
      " s predicted). Cornering grip accounts for " + f(DS26.mean_grip_s, 2) + " s and power for " + f(DS26.mean_power_s, 2) + " s. The remainder is what a point-mass model cannot see: driving, braking, tyre preparation, set-up.");
    if (UPG) {
      var pb = UPG.before.power_deficit || {}, pa = UPG.after.power_deficit || {};
      fill("upgrade_text", "The changepoint model is not told when upgrades arrived. It puts the most likely shift in Aston Martin’s 2026 pace at the <strong>" +
        esc(CP26.map_event || "–") + "</strong> (" + sgn(CP26.effect_pct, 2) + "% of lap time, 90% interval " + sgn((CP26.effect_ci90_pct || [])[0], 2) + " to " + sgn((CP26.effect_ci90_pct || [])[1], 2) +
        "%), the event where the team declared its 16-part B-spec to the FIA. Splitting the car into parts shows what changed: fast-corner grip rose from " +
        f(UPG.before.grip_high_rel.mean * 100, 1) + "% to " + f(UPG.after.grip_high_rel.mean * 100, 1) + "% of the field median, while the straight-line speed deficit stayed at " +
        f(UPG.before.straight_speed_delta_kmh.mean, 1) + " → " + f(UPG.after.straight_speed_delta_kmh.mean, 1) + " km/h and the power-equivalent deficit at " +
        f(pb.mean_kw, 0) + " → " + f(pa.mean_kw, 0) + " kW. The upgrade fixed the aero; the power gap is what remains. Only " + UPG.after.grip_high_rel.n +
        " post-upgrade events have clean geometry, so the “after” grip figure is a small sample.");
    }
  }

  // ------------------------------------------------------------------ finding charts
  function renderPower(t) {
    t = t || theme();
    var bands = function (season, team) { return ((((S.powertrain || {})[season] || {})[team]) || {}).bands || []; };
    var series = [
      { s: "2026", team: TARGET, name: "Aston Martin 2026", color: t.amr },
      { s: "2025", team: TARGET, name: "Aston Martin 2025", color: t.third },
      { s: "2026", team: "Audi", name: "Audi 2026", color: t.ref },
    ];
    var traces = series.map(function (sr, i) {
      var b = bands(sr.s, sr.team);
      var x = b.map(function (r) { return r.band_kmh + 10 + (i - 1) * 2.5; });
      return { x: x, y: b.map(function (r) { return r.d_power_kw; }), name: sr.name, type: "scatter", mode: "lines+markers",
        line: { color: sr.color, width: 2 }, marker: { size: 8, color: sr.color, line: { color: t.surface, width: 2 } },
        error_y: { type: "data", symmetric: false, array: b.map(function (r) { return r.d_power_hi - r.d_power_kw; }), arrayminus: b.map(function (r) { return r.d_power_kw - r.d_power_lo; }), color: sr.color, thickness: 1.2, width: 0 },
        hovertemplate: sr.name + "<br>%{x:.0f} km/h: %{y:.0f} kW<extra></extra>" };
    });
    plot("ch-power", traces, layout(t, { showlegend: true, xaxis: { title: { text: "speed band, km/h" }, ticksuffix: "" }, yaxis: { title: { text: "kW vs field (−= slower)" } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1 } }] }));
  }

  function renderSlope(t) {
    t = t || theme();
    var pt = (S.powertrain || {})["2026"] || {};
    var teams = Object.keys(pt).filter(function (k) { return isFinite(pt[k].slope) && isFinite(pt[k].power_deficit_kw_200plus); });
    teams.sort(function (a, b) { return pt[a].power_deficit_kw_200plus - pt[b].power_deficit_kw_200plus; });
    var slope = teams.map(function (k) { return Math.max(-4, Math.min(9, pt[k].slope)); });
    plot("ch-slope", [{
      x: teams.map(function (k) { return pt[k].power_deficit_kw_200plus; }), y: slope, text: teams, type: "scatter", mode: "markers+text",
      textposition: "top center", textfont: { size: 11, color: t.ink2 },
      marker: { size: 11, color: teams.map(function (k) { return k === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 2 } },
      customdata: teams.map(function (k) { return [pt[k].slope, (pt[k].power_deficit_ci90 || [])[0], (pt[k].power_deficit_ci90 || [])[1]]; }),
      hovertemplate: "%{text}<br>deficit %{x:.0f} kW (90% %{customdata[1]:.0f} to %{customdata[2]:.0f})<br>slope %{customdata[0]:.1f}<extra></extra>",
    }], layout(t, { xaxis: { title: { text: "mean power-equivalent deficit ≥ 200 km/h, kW" } }, yaxis: { title: { text: "log-log slope vs speed" }, range: [-4.5, 9.5] },
      shapes: [{ type: "rect", xref: "paper", x0: 0, x1: 1, y0: -1, y1: 1, fillcolor: t.amr, opacity: 0.07, line: { width: 0 } },
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: 3, y1: 3, line: { color: t.muted, width: 1, dash: "dot" } }],
      annotations: [{ xref: "paper", x: 1, y: 0, xanchor: "right", text: "power-like", showarrow: false, font: { size: 11, color: t.muted } },
        { xref: "paper", x: 1, y: 3, yanchor: "bottom", xanchor: "right", text: "pure drag (v³)", showarrow: false, font: { size: 11, color: t.muted } }] }));
  }

  function renderDecomp(t) {
    t = t || theme();
    var rows = (S.deficit_decomposition || []).filter(function (r) { return r.season === 2026; });
    var x = rows.map(function (r) { return short(r.event); });
    var resid = rows.map(function (r) { return r.actual_gap_s - r.predicted_gap_s; });
    plot("ch-decomp", [
      { x: x, y: rows.map(function (r) { return r.grip_s; }), name: "cornering grip", type: "bar", marker: { color: t.amr }, hovertemplate: "%{x}<br>grip %{y:.2f} s<extra></extra>" },
      { x: x, y: rows.map(function (r) { return r.power_s; }), name: "power", type: "bar", marker: { color: t.third }, hovertemplate: "%{x}<br>power %{y:.2f} s<extra></extra>" },
      { x: x, y: resid, name: "not explained", type: "bar", marker: { color: t.field }, hovertemplate: "%{x}<br>residual %{y:.2f} s<extra></extra>" },
      { x: x, y: rows.map(function (r) { return r.actual_gap_s; }), name: "actual gap", type: "scatter", mode: "markers", marker: { symbol: "line-ew-open", size: 26, color: t.ink, line: { width: 2.5, color: t.ink } }, hovertemplate: "%{x}<br>actual %{y:.2f} s<extra></extra>" },
    ], layout(t, { barmode: "relative", bargap: 0.35, showlegend: true, yaxis: { title: { text: "seconds to pole" } } }));
  }

  // ------------------------------------------------------------------ upgrades
  function upgradeEvents(season) {
    return ((S.upgrades || {}).declared || []).filter(function (u) { return u.season === season && (u.major_performance_upgrade === "major" || u.major_performance_upgrade === "partial"); });
  }
  function renderUpgradeParts(t) {
    t = t || theme();
    var series = (S.amr_component_series || {})["2026"] || [];
    plot("ch-grip26", [{ x: series.map(function (r) { return short(r.event); }), y: series.map(function (r) { return r.grip_high_rel; }), type: "scatter", mode: "lines+markers",
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.3f} of field median<extra></extra>", connectgaps: true }],
      layout(t, { yaxis: { title: { text: "ratio to field median" }, tickformat: ".2f" }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, series, 2026).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, 2026) }));
    plot("ch-straight26", [{ x: series.map(function (r) { return short(r.event); }), y: series.map(function (r) { return r.straight_speed_delta_kmh; }), type: "scatter", mode: "lines+markers",
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.1f} km/h<extra></extra>", connectgaps: true }],
      layout(t, { yaxis: { title: { text: "km/h vs field median" } }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, series, 2026).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, 2026) }));
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
    var season = Number(current.gapSeason);
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
  function hexA(hex, a) {
    var h = hex.replace("#", ""); if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + a + ")";
  }

  function renderCP(t) {
    t = t || theme();
    var cp = (S.changepoints || {})[current.gapSeason] || {};
    var ev = (cp.events || []).map(short);
    plot("ch-cp", [{ x: ev, y: cp.posterior_tau || [], type: "bar", marker: { color: (cp.events || []).map(function (e) { return e === cp.map_event ? t.amr : t.field; }) },
      hovertemplate: "%{x}<br>P(change here) = %{y:.2f}<extra></extra>" }],
      layout(t, { bargap: 0.3, yaxis: { title: { text: "posterior probability" }, range: [0, 1] }, xaxis: { tickangle: -40 },
        annotations: [{ xref: "paper", yref: "paper", x: 0, y: 1, xanchor: "left", yanchor: "top", showarrow: false, font: { size: 11, color: t.muted },
          text: "P(no change all season) = " + f(cp.p_no_change, 2) }] }));
  }

  function renderDiD() {
    var eff = (S.upgrades || {}).effects || [];
    var rows = eff.map(function (e) {
      var sig = e.team_placebo_p <= 0.1 && e.time_placebo_p <= 0.2;
      return "<tr><td>" + e.season + " " + esc(short(e.event)) + '</td><td class="num">' + sgn(e.effect_pct, 2) + '%</td><td class="num">' + f(e.team_placebo_p, 2) +
        '</td><td class="num">' + f(e.time_placebo_p, 2) + '</td><td><span class="pill ' + (sig ? "yes" : "no") + '">' + (sig ? "distinguishable from noise" : "not distinguishable") + "</span></td></tr>";
    });
    $("tbl-did").innerHTML = $("tbl-did").querySelector("caption").outerHTML +
      '<thead><tr><th>Upgrade</th><th class="num">Effect on gap</th><th class="num">Team placebo p</th><th class="num">Time placebo p</th><th>Verdict</th></tr></thead><tbody>' + rows.join("") + "</tbody>";
  }

  // ------------------------------------------------------------------ aero map
  function renderAero(t) {
    t = t || theme();
    var am = (S.aero_map || {})[current.aeroSeason] || {};
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
    var pts = { x: xs, y: ys, text: teams.map(function (r) { return r.team; }), type: "scatter", mode: "markers+text", textposition: "top right",
      textfont: { size: 11, color: t.ink2 },
      marker: { size: teams.map(function (r) { return r.team === TARGET ? 13 : 9; }), color: teams.map(function (r) { return r.team === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: teams.map(function (r) { return r.d_cla_equiv_pct[2] - r.d_cla_equiv_pct[0]; }), arrayminus: teams.map(function (r) { return r.d_cla_equiv_pct[0] - r.d_cla_equiv_pct[1]; }), color: t.field, thickness: 1, width: 0 },
      error_y: { type: "data", symmetric: false, array: teams.map(function (r) { return r.d_cda_equiv_pct[2] - r.d_cda_equiv_pct[0]; }), arrayminus: teams.map(function (r) { return r.d_cda_equiv_pct[0] - r.d_cda_equiv_pct[1]; }), color: t.field, thickness: 1, width: 0 },
      customdata: teams.map(function (r) { return [r.n_events, r.mean_gap_pct]; }),
      hovertemplate: "%{text}<br>downforce-equiv %{x:.1f}%<br>drag-equiv %{y:.1f}%<br>%{customdata[0]} events · mean quali gap %{customdata[1]:.2f}%<extra></extra>" };
    plot("ch-aero", lines.concat([pts]), layout(t, {
      xaxis: { title: { text: "downforce-equivalent vs field, % (→ more)" }, range: [-lim, lim] },
      yaxis: { title: { text: "drag-equivalent vs field, % (↑ more drag / less speed)" }, range: [-lim / 2, lim / 2] },
      annotations: [{ xref: "paper", yref: "paper", x: 1, y: 0, xanchor: "right", yanchor: "bottom", showarrow: false, font: { size: 11, color: t.muted },
        text: "1% C<sub>L</sub>A = " + f(sens.cla_plus_1pct_s, 3) + " s · 1% C<sub>D</sub>A = +" + f(sens.cda_plus_1pct_s, 3) + " s" }] }));
    var amr = teams.filter(function (r) { return r.team === TARGET; })[0];
    if (amr) fill("aero_text", "High-speed cornering grip is turned into a downforce-equivalent using each event’s aero share of grip, and straight-line peak speed into a drag-equivalent (v ∝ C<sub>D</sub>A<sup>−1/3</sup>). In " + current.aeroSeason +
      " Aston Martin sits at " + sgn(amr.d_cla_equiv_pct[0], 1) + "% downforce-equivalent and " + sgn(amr.d_cda_equiv_pct[0], 1) +
      "% drag-equivalent against the field median. The drag axis mixes drag with power, so read it alongside the power analysis above. Dotted lines join set-ups with equal lap time, from the calibrated lap simulator.");
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

  // ------------------------------------------------------------------ event-level
  function loadEvent(key, cb) {
    window.EVENTS = window.EVENTS || {};
    if (window.EVENTS[key]) return cb(window.EVENTS[key]);
    var s = document.createElement("script");
    s.src = "data/events/" + key + ".js";
    s.onload = function () { cb(window.EVENTS[key]); };
    s.onerror = function () { $("lap-hint").textContent = "Could not load this event’s data file."; };
    document.head.appendChild(s);
  }

  function interp(xs, ys, x) {
    var lo = 0, hi = xs.length - 1;
    if (x <= xs[0]) return ys[0]; if (x >= xs[hi]) return ys[hi];
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
    return ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / (xs[hi] - xs[lo]);
  }

  function renderLap(t) {
    t = t || theme();
    var e = current.event; if (!e || !e.comparison) return;
    var c = e.comparison, mp = e.map, d = mp.distance_m;
    var cell = c.delta_s.map(function (v, i) { return i ? (v - c.delta_s[i - 1]) * 1000 : v * 1000; });
    var abs = cell.map(Math.abs).sort(function (a, b) { return a - b; });
    var cap = Math.max(abs[Math.floor(abs.length * 0.95)] || 1, 1);
    $("map-sub").textContent = c.target + " vs " + c.reference + " · ms lost per 10 m (orange) or gained (green)";
    $("lap-hint").textContent = e.circuit && e.circuit.location ? e.circuit.location + " · pole " + e.pole.driver + " " + f(e.pole.lap_time_s, 3) + " s · gap " + sgn(c.total_delta_s, 3) + " s" : "";
    var cx = e.corners.distance_m.map(function (s) { return interp(d, mp.x, s); }), cy = e.corners.distance_m.map(function (s) { return interp(d, mp.y, s); });
    plot("ch-map", [
      { x: mp.x, y: mp.y, type: "scatter", mode: "markers", marker: { size: 6, color: cell, cmin: -cap, cmid: 0, cmax: cap,
        colorscale: [[0, t.amr], [0.5, t.field], [1, t.third]], colorbar: { title: { text: "ms/10 m", font: { size: 10, color: t.muted } }, thickness: 8, len: 0.6, tickfont: { size: 10, color: t.muted }, outlinewidth: 0 } },
        customdata: d.map(function (s, i) { return [s, cell[i]]; }), hovertemplate: "%{customdata[0]:.0f} m: %{customdata[1]:+.1f} ms<extra></extra>" },
      { x: cx, y: cy, text: e.corners.label, type: "scatter", mode: "text", textfont: { size: 10, color: t.ink2, family: t.mono }, hoverinfo: "skip" },
    ], layout(t, { margin: { l: 8, r: 8, t: 8, b: 8 }, xaxis: { visible: false, scaleanchor: "y" }, yaxis: { visible: false } }));

    var cls = c.class_summary || [];
    plot("ch-class", [{ x: cls.map(function (r) { return r.speed_class === "straights" ? "straights" : r.speed_class + "-speed corners"; }), y: cls.map(function (r) { return r.time_s; }), type: "bar",
      marker: { color: cls.map(function (r) { return r.time_s >= 0 ? t.third : t.amr; }) }, text: cls.map(function (r) { return sgn(r.time_s, 3) + " s"; }), textposition: "outside", textfont: { size: 11, color: t.ink2 },
      hovertemplate: "%{x}<br>%{y:.3f} s · %{customdata} corners<extra></extra>", customdata: cls.map(function (r) { return r.n_corners; }) }],
      layout(t, { bargap: 0.45, yaxis: { title: { text: "s lost to pole" } }, height: null }));

    var corners = (c.corners || []).slice().sort(function (a, b) { return b.total_s - a.total_s; });
    $("tbl-corners").innerHTML = '<thead><tr><th>Corner</th><th class="num">Lost, s</th><th class="num">Entry</th><th class="num">Apex</th><th class="num">Exit</th><th class="num">Min speed Δ</th></tr></thead><tbody>' +
      corners.map(function (r) { return "<tr><td>" + esc(r.corner) + " <span class=\"hint\">" + r.speed_class + '</span></td><td class="num">' + sgn(r.total_s, 3) + '</td><td class="num">' + sgn(r.entry_s, 3) + '</td><td class="num">' + sgn(r.apex_s, 3) + '</td><td class="num">' + sgn(r.exit_s, 3) + '</td><td class="num">' + sgn(r.min_speed_delta_kmh, 1) + " km/h</td></tr>"; }).join("") + "</tbody>";

    var ann = e.corners.distance_m.map(function (s, i) { return { x: s, yref: "paper", y: 1, yanchor: "bottom", text: e.corners.label[i], showarrow: false, font: { size: 9, color: t.muted, family: t.mono } }; });
    plot("ch-speed", [
      { x: d, y: c.reference_speed_kmh, name: c.reference + " (pole)", type: "scatter", mode: "lines", line: { color: t.ref, width: 1.6 }, hovertemplate: "%{x:.0f} m · " + c.reference + " %{y:.0f} km/h<extra></extra>" },
      { x: d, y: c.target_speed_kmh, name: c.target, type: "scatter", mode: "lines", line: { color: t.amr, width: 1.6 }, hovertemplate: "%{x:.0f} m · " + c.target + " %{y:.0f} km/h<extra></extra>" },
    ], layout(t, { showlegend: true, legend: { orientation: "h", x: 0, y: 1.14 }, hovermode: "x unified", margin: { l: 56, r: 16, t: 26, b: 10 },
      xaxis: { showticklabels: false }, yaxis: { title: { text: "km/h" } }, annotations: ann }));
    plot("ch-delta", [{ x: d, y: c.delta_s, type: "scatter", mode: "lines", fill: "tozeroy", fillcolor: hexA(t.third, 0.15), line: { color: t.third, width: 1.6 }, hovertemplate: "%{x:.0f} m · gap %{y:+.3f} s<extra></extra>" }],
      layout(t, { hovermode: "x unified", margin: { l: 56, r: 16, t: 4, b: 40 }, xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "gap, s" } } }));
  }

  function renderSim(t) {
    t = t || theme();
    var e = current.event; if (!e) return;
    var key = e.sandbox ? e.sandbox.car : null;
    var ls = key && e.lapsim ? e.lapsim[key] : null;
    if (!ls) { $("sim-sub").textContent = "no calibration for this event (geometry check failed)"; Plotly.purge($("ch-sim")); Plotly.purge($("ch-disc")); $("tbl-params").innerHTML = ""; return; }
    var d = e.map.distance_m.slice(0, ls.trace.observed_kmh.length);
    $("sim-sub").textContent = ls.driver + " · RMSE " + f(ls.rmse_kmh, 1) + " km/h · lap-time error " + sgn(ls.lap_time_error_s, 3) + " s";
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
    var rows = ls.param_names.map(function (n, i) {
      var p = ls.params[n], nm = names[n] || [n, 1, ""];
      var dig = n === "power_w" ? 0 : 2;
      return "<tr><td>" + nm[0] + '</td><td class="num">' + f(p.median * nm[1], dig) + nm[2] + '</td><td class="num">' + f(p.lo * nm[1], dig) + " – " + f(p.hi * nm[1], dig) + "</td>" +
        (mc ? '<td class="num">' + f(mc.laplace_sd_log[i], 2) + " / " + f(mc.mcmc_sd_log[i], 2) + "</td>" : "") + "</tr>";
    });
    $("tbl-params").innerHTML = "<caption>Calibrated parameters, " + esc(ls.driver) + " · effective sample size " + f(ls.n_effective, 0) + " of " + ls.trace.observed_kmh.length * 2 + " points</caption>" +
      '<thead><tr><th>Parameter</th><th class="num">Median</th><th class="num">90% interval</th>' + (mc ? '<th class="num">log-sd Laplace / MCMC</th>' : "") + "</tr></thead><tbody>" + rows.join("") + "</tbody>";
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
      " s in 2026. The 2026 fits are weaker because power there falls with time along a straight (energy deployment), which a constant-power point-mass model cannot represent; the discrepancy chart shows exactly where.");
  }
  function median(a) { a = a.slice().sort(function (x, y) { return x - y; }); return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : NaN; }

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
    var e = current.event; if (!e || !e.energy_speed) return;
    var d = e.map.distance_m, keys = Object.keys(e.energy_speed);
    $("energy-sub").textContent = short(e.event) + " " + e.season + " · full-throttle runs highlighted";
    var cols = { }; cols[e.pole.driver] = t.ref; if (e.comparison) cols[e.comparison.target] = t.amr;
    plot("ch-energy", keys.map(function (k) { return { x: d, y: e.energy_speed[k], name: k, type: "scatter", mode: "lines", line: { color: cols[k] || t.field, width: 1.5 }, hovertemplate: k + " %{x:.0f} m: %{y:.0f} km/h<extra></extra>" }; }),
      layout(t, { showlegend: true, hovermode: "x unified", xaxis: { title: { text: "distance, m" } }, yaxis: { title: { text: "km/h" } } }));
    var en = (S.energy || []).filter(function (r) { return r.season === 2026; }).sort(function (a, b) { return a.clip_time_loss_s - b.clip_time_loss_s; });
    var en25 = (S.energy || []).filter(function (r) { return r.season === 2025; });
    plot("ch-clip", [{ y: en.map(function (r) { return r.team; }), x: en.map(function (r) { return r.clip_time_loss_s; }), type: "bar", orientation: "h",
      marker: { color: en.map(function (r) { return r.team === TARGET ? t.amr : t.field; }) },
      customdata: en.map(function (r) { return [r.clip_speed_drop_kmh, r.clip_decel_distance_m]; }),
      hovertemplate: "%{y}<br>%{x:.3f} s/lap · speed drop %{customdata[0]:.1f} km/h · %{customdata[1]:.0f} m decelerating<extra></extra>" }],
      layout(t, { bargap: 0.35, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "s per lap (2026)" } } }));
    var amr = en.filter(function (r) { return r.team === TARGET; })[0] || {};
    var fieldLoss = mean(en.map(function (r) { return r.clip_time_loss_s; }));
    var loss25 = mean(en25.map(function (r) { return r.clip_time_loss_s; }));
    fill("energy_text", "In 2026 cars reach peak speed part-way along a straight and then slow down at full throttle. Speed-dependent power alone, including the regulated MGU-K taper, cannot do that; it means power is falling with time as deployment ends. The field loses on average " +
      f(fieldLoss, 3) + " s per lap against holding peak speed, compared with " + f(loss25, 3) + " s in 2025. Aston Martin loses " + f(amr.clip_time_loss_s, 3) +
      " s, close to the field. So energy clipping does not explain its straight-line deficit; the acceleration deficit appears earlier, below 285 km/h.");
  }

  // ------------------------------------------------------------------ race pace
  function renderRace(t) {
    t = t || theme();
    var rp = (S.race_pace_by_event || []).filter(function (r) { return r.team === TARGET; }).sort(function (a, b) { return a.season - b.season || a.round - b.round; });
    var st = {}; (S.supertimes || []).forEach(function (r) { if (r.team === TARGET) st[r.season + "-" + r.round] = r.gap_pct; });
    var x = rp.map(function (r) { return short(r.event) + " " + String(r.season).slice(2); });
    var bestQ = {}; (S.supertimes || []).forEach(function (r) { var k = r.season + "-" + r.round; bestQ[k] = Math.min(bestQ[k] == null ? 1e9 : bestQ[k], r.gap_pct); });
    plot("ch-race", [
      { x: x, y: rp.map(function (r) { return r.gap_s; }), name: "race pace gap", type: "scatter", mode: "markers", marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } },
        error_y: { type: "data", symmetric: false, array: rp.map(function (r) { return r.ci_hi - r.gap_s; }), arrayminus: rp.map(function (r) { return r.gap_s - r.ci_lo; }), color: t.amr, thickness: 1.2, width: 0 },
        hovertemplate: "%{x}<br>race pace +%{y:.2f} s/lap<extra></extra>" },
    ], layout(t, { yaxis: { title: { text: "s per lap behind best team" }, rangemode: "tozero" }, xaxis: { tickangle: -50 } }));
    var by = byKey(S.race_pace || [], "season");
    var g25 = (by[2025] || []).filter(function (r) { return r.team === TARGET; })[0] || {}, g26 = (by[2026] || []).filter(function (r) { return r.team === TARGET; })[0] || {};
    fill("race_text", "Every green-flag lap of every dry race is fitted with driver pace, compound offsets, tyre degradation per lap of age and a fuel effect per lap, so the comparison is at equal fuel and fresh tyres. Intervals combine a stint-level Bayesian bootstrap with the classical interval, whichever is wider, because with ~40 stints per race cluster methods alone are too narrow (checked by simulation in the tests). Aston Martin’s corrected race pace averaged " +
      f(g25.mean, 2) + " s per lap off the best team in 2025 (" + g25.count + " races) and " + f(g26.mean, 2) + " s in 2026 (" + g26.count + " races).");
  }

  // ------------------------------------------------------------------ models
  function renderModels(t) {
    t = t || theme();
    var cm = S.corner_model || {};
    var names = { steady: "Steady-state cornering formula", physics: "Lap sim on track geometry (no fitting)", ml: "Gradient boosting only", hybrid: "Hybrid: lap sim + boosted residual" };
    $("tbl-cm").innerHTML = "<caption>Out-of-sample by whole event (GroupKFold, " + cm.n_events + " events, " + cm.n_rows + " corners)</caption>" +
      '<thead><tr><th>Model</th><th class="num">RMSE</th><th class="num">MAE</th><th class="num">R²</th></tr></thead><tbody>' +
      (cm.metrics || []).map(function (r) { return "<tr><td>" + names[r.model] + '</td><td class="num">' + f(r.rmse_kmh, 1) + ' km/h</td><td class="num">' + f(r.mae_kmh, 1) + ' km/h</td><td class="num">' + f(r.r2, 3) + "</td></tr>"; }).join("") + "</tbody>";
    var mm = {}; (cm.metrics || []).forEach(function (r) { mm[r.model] = r; });
    fill("corner_text", "Predicts each corner’s minimum speed on a track the model has never seen, from geometry (radius, turn angle, approach length), air density, headwind, track temperature and tyre age. Target speeds never enter the features. The physics baseline runs the lap simulator on the held-out track with a nominal car taken from the other events’ calibrations, and on unseen tracks it beats a black-box model (R² " +
      f((mm.physics || {}).r2, 2) + " vs " + f((mm.ml || {}).r2, 2) + "). Learning its residual helps a little more. Split-conformal intervals, calibrated only on other events, cover " +
      f(cm.conformal_coverage * 100, 1) + "% of held-out corners at a 90% target (±" + f(cm.conformal_halfwidth_kmh, 0) + " km/h). The residual by team drives the chart on the right.");
    var def = (S.team_corner_deficit || {})[current.deficitSeason] || [];
    var teams = Array.from(new Set(def.map(function (r) { return r.team; })));
    var meanBy = {}; teams.forEach(function (tm) { meanBy[tm] = mean(def.filter(function (r) { return r.team === tm; }).map(function (r) { return r.deficit_kmh; })); });
    teams.sort(function (a, b) { return meanBy[a] - meanBy[b]; });
    var classes = ["low", "medium", "high"], marks = { low: "circle", medium: "diamond", high: "square" };
    plot("ch-deficit", classes.map(function (cl, i) {
      var r = teams.map(function (tm) { return def.filter(function (x) { return x.team === tm && x.speed_class === cl; })[0] || {}; });
      return { y: teams, x: r.map(function (x) { return x.deficit_kmh; }), name: cl + "-speed", type: "scatter", mode: "markers",
        marker: { symbol: marks[cl], size: 9, color: teams.map(function (tm) { return tm === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 1.5 } },
        error_x: { type: "data", symmetric: false, array: r.map(function (x) { return x.ci_hi - x.deficit_kmh; }), arrayminus: r.map(function (x) { return x.deficit_kmh - x.ci_lo; }), color: t.rule, thickness: 1, width: 0 },
        hovertemplate: "%{y} · " + cl + "-speed<br>%{x:+.1f} km/h<extra></extra>" };
    }), layout(t, { showlegend: true, margin: { l: 110, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "km/h vs expectation" } },
      shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));

    var vs = S.variance_split || {}, yrs = Object.keys(vs).sort();
    plot("ch-var", [{ y: yrs, x: yrs.map(function (y) { return vs[y].car_share * 100; }), type: "scatter", mode: "markers", marker: { size: 12, color: t.amr, line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: yrs.map(function (y) { return (vs[y].car_share_ci90[1] - vs[y].car_share) * 100; }), arrayminus: yrs.map(function (y) { return (vs[y].car_share - vs[y].car_share_ci90[0]) * 100; }), color: t.amr, thickness: 1.5, width: 0 },
      hovertemplate: "%{y}: %{x:.0f}% between teams<extra></extra>" }],
      layout(t, { margin: { l: 50, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "% of variance between teams (car)" }, range: [0, 100] }, yaxis: { type: "category" } }));
    if (yrs.length === 2) fill("var_text", "Within each event, qualifying gaps are split into a between-team part (the car) and a within-team part (driver and lap execution). In " + yrs[0] + " the car explained " +
      f(vs[yrs[0]].car_share * 100, 0) + "% of the variance; in " + yrs[1] + " it explained " + f(vs[yrs[1]].car_share * 100, 0) + "%. The new rules spread the field so far that the car now dominates.");

    var ws = (S.wind_sensitivity || []).slice().sort(function (a, b) { return ["low", "medium", "high"].indexOf(a.speed_class) - ["low", "medium", "high"].indexOf(b.speed_class); });
    plot("ch-wind", [{ y: ws.map(function (r) { return r.speed_class + "-speed"; }), x: ws.map(function (r) { return r.kmh_per_ms_headwind; }), type: "scatter", mode: "markers", marker: { size: 11, color: t.ref, line: { color: t.surface, width: 2 } },
      error_x: { type: "data", symmetric: false, array: ws.map(function (r) { return r.ci_hi - r.kmh_per_ms_headwind; }), arrayminus: ws.map(function (r) { return r.kmh_per_ms_headwind - r.ci_lo; }), color: t.ref, thickness: 1.5, width: 0 },
      hovertemplate: "%{y}: %{x:+.2f} km/h per m/s<extra></extra>" }],
      layout(t, { margin: { l: 100, r: 16, t: 10, b: 44 }, xaxis: { title: { text: "km/h per m/s headwind" } }, shapes: [{ type: "line", yref: "paper", y0: 0, y1: 1, x0: 0, x1: 0, line: { color: t.muted, width: 1 } }] }));
    var sigW = ws.filter(function (r) { return r.ci_lo > 0 || r.ci_hi < 0; });
    fill("wind_text", "The same corner, driven by different cars in different wind across two seasons, with corner and team-season fixed effects. " +
      (sigW.length ? "Only the " + sigW.map(function (r) { return r.speed_class; }).join(", ") + "-speed class shows an interval clear of zero." : "No corner class shows an effect distinguishable from zero.") +
      " The original prototype attributed 0.41 s at Silverstone to crosswind yaw; with proper identification, wind is not a measurable driver of lap time in this data.");
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
      var why = /Only \d+ laps passed/.test(s.reason) ? "telemetry failed automated data checks (dropouts, GPS/odometer mismatch)" : /404|Not cached|corners/.test(s.reason) ? "source files missing from the archive (Bahrain was cancelled; Madrid has no corner file)" : s.reason;
      return "<li>" + s.season + " " + esc(s.event) + ": " + esc(why) + "</li>";
    }).join("") + (dq.events_geometry_failed || []).map(function (e) { return "<li>" + esc(e) + ": kept for timing analyses, excluded from curvature-based fits (turning number check)</li>"; }).join("");
    fill("method_html",
      "<h3>Pipeline</h3><p>Fastest valid qualifying lap of every driver at every event, resampled onto a shared distance grid by projecting GPS fixes onto the pole lap’s line. Time comes from the measured timing channel and closes exactly on the official lap time. The archive’s GPS stream runs about " + f(dq.gps_lag_s_median, 2) +
      " s ahead of the car-data stream; left uncorrected that misplaces samples by 10 m at 300 km/h. Each lap’s offset is estimated by matching GPS-derived speed to the wheel-speed sensor.</p>" +
      "<p>Track curvature is the median over all drivers of a time-domain smoothing spline through the raw ~4 Hz GPS fixes. The smoothing level is chosen per event by the same speed cross-check, and every lap must integrate to one full turn.</p>" +
      "<h3>What the numbers can and cannot say</h3><p>Grip, downforce and drag figures are effective values for a point-mass car: load transfer and tyre load sensitivity are folded in, so absolute μ and C<sub>L</sub>A are not separable from public data and are reported only as comparisons at matched dynamic pressure. Mass is the regulation minimum plus an assumed 5 kg of fuel. The power analysis measures deployed wheel power, which includes energy strategy. Correlation with declared upgrades is evidence, not proof: four events either side is a short window, and track layouts differ.</p>");
  }

  // ------------------------------------------------------------------ boot
  function initEvents() {
    var sel = $("sel-event");
    var opts = M.filter(function (m) { return m.has_comparison; });
    sel.innerHTML = opts.map(function (m) { return '<option value="' + m.key + '">' + m.season + " · " + esc(short(m.event)) + (m.geometry_ok ? "" : " (timing only)") + "</option>"; }).join("");
    var pick = opts.filter(function (m) { return m.season === 2026 && m.event === "British Grand Prix"; })[0] || opts[opts.length - 1];
    if (pick) sel.value = pick.key;
    function go() { loadEvent(sel.value, function (e) { current.event = e; rerender(); }); }
    sel.addEventListener("change", go);
    go();
  }

  function start() {
    heroText();
    seg("seg-season", ["2025", "2026"], current.gapSeason, function (v) { current.gapSeason = v; renderGap(); renderCP(); });
    seg("seg-aero", ["2025", "2026"], current.aeroSeason, function (v) { current.aeroSeason = v; renderAero(); });
    seg("seg-deficit", ["2025", "2026"], current.deficitSeason, function (v) { current.deficitSeason = v; renderModels(); });
    [renderPower, renderSlope, renderDecomp, renderUpgradeParts, renderGap, renderCP, renderAero, renderSens, renderLap, renderSim, renderCalAcc, renderEnergy, renderRace, renderModels].forEach(register);
    renderDiD(); renderMethod();
    initEvents();
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", rerender);
    new MutationObserver(rerender).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
  if (!window.Plotly) { document.addEventListener("DOMContentLoaded", start); } else { start(); }
})();
