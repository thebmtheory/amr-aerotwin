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
  // Typographic minus; a value that rounds to zero loses its sign
  function f(x, d) { return x == null || !isFinite(x) ? "–" : Number(x).toFixed(d == null ? 1 : d).replace(/^-(?=.*[1-9])/, "−").replace(/^-/, ""); }
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
    if (out.showlegend && !(extra || {}).margin) out.margin = { l: 56, r: 16, t: 48, b: 44 };
    if (out.showlegend && !(extra || {}).legend) out.legend = { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 11, color: t.ink2 } };
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
    c.innerHTML = options.map(function (o) { return '<button type="button" data-v="' + o + '" aria-pressed="' + (o === value) + '">' + o + "</button>"; }).join("");
    c.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      c.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      onChange(b.getAttribute("data-v"));
    });
  }

  // ------------------------------------------------------------------ headline text
  var PROF = (S.straight_profile || {});
  var SP26 = (PROF["2026"] || {})[TARGET] || {};
  var SP25 = (PROF["2025"] || {})[TARGET] || {};
  var GB = S.gap_by_class || {};
  var REL26 = ((S.target_relative || {})["2026"]) || {};
  var DS26 = ((S.deficit_summary || {})["2026"]) || {};
  var UPG = (S.upgrade_components || []).filter(function (u) { return u.season === 2026; })[0];
  var CP26 = (S.changepoints || {})["2026"] || {};
  var PT26 = ((S.powertrain || {})["2026"] || {})[TARGET] || {};

  function ci(a, d, unit) { return a && a.length === 2 ? f(a[0], d) + " to " + f(a[1], d) + (unit || "") : "–"; }
  function cls(season, name) {
    var g = GB[season] || {}, i = (g.classes || []).indexOf(name);
    return i < 0 ? {} : { mean: g.mean_s[i], lo: g.ci_lo[i], hi: g.ci_hi[i], total: g.mean_total_s, n: g.n_events };
  }

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
      f(st26.v, 1) + "% of its straight-line time (90% CI " + f(st26.lo, 1) + "–" + f(st26.hi, 1) + "%), close to its " + f(a26.corner_rate_pct, 1) + "% in the corners. Every other team with five or more events has a straight-line rate between " +
      f(Math.min.apply(null, stOthers), 1) + "% and " + f(Math.max.apply(null, stOthers), 1) + "%. Cadillac, about as slow over a lap (" + f(cad.lap_rate_pct, 2) + "% vs " + f(a26.lap_rate_pct, 2) +
      "%), loses " + f(cadSt.v, 1) + "% on the straights. On " + SP26.n_straights_losing_late + " of " + SP26.n_straights + " main straights Aston Martin's speed gap also grows in the second half, by " + f(-SP26.second_half_kmh, 1) + " km/h on average, at full throttle.");
    var tiles = [
      { k: "Straight-line loss rate, 2026", v: f(st26.v, 1) + "%", ci: "90% CI " + f(st26.lo, 1) + "–" + f(st26.hi, 1) + "% · " + f(vf.ratio, 1) + "× the next team (" + esc(vf.next_team || "–") + "), CI " + ci(vf.ratio_ci90, 1), amr: true },
      { k: "Straights vs corners, 2026", v: f(a26.straight_to_corner_ratio, 2), ci: "ratio of loss rates, CI " + ci(a26.straight_to_corner_ci90, 2) + " · teams over 1% off pole " + f(Math.min.apply(null, ratioOthers), 2) + "–" + f(Math.max.apply(null, ratioOthers), 2) },
      { k: "Same ratio, 2025 car", v: f(a25.straight_to_corner_ratio, 2), ci: "CI " + ci(a25.straight_to_corner_ci90, 2) + " · " + (function () {
        var r = others("2025").map(function (x) { return x.r.straight_to_corner_ratio; }), lo = Math.min.apply(null, r), hi = Math.max.apply(null, r);
        return (a25.straight_to_corner_ratio >= lo && a25.straight_to_corner_ratio <= hi ? "in line with the other teams, " : "outside the other teams' range, ") + f(lo, 2) + "–" + f(hi, 2);
      })() },
      { k: "Lost late on the straights", v: f(SP26.second_half_kmh, 1) + " km/h", ci: "second half, full throttle, CI " + ci(SP26.second_half_ci90, 1) + " · " + SP26.n_straights + " straights, " + SP26.n_events + " events" },
    ];
    $("tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile"><span class="k">' + t.k + '</span><span class="v' + (t.amr ? " amr" : "") + '">' + t.v + '</span><span class="ci">' + t.ci + "</span></div>";
    }).join("");
    fill("hero_note", "Loss rate = time lost to the pole lap in a section ÷ time the pole lap spends there, summed over events. A car that is uniformly slower has equal rates everywhere, so rates (not seconds) show where a car is weak; in seconds, slow corners always dominate because cars spend the most time there. Comparisons use the same piece of track, so geometry and gradient cancel, but laps can be set at different times of the session: track evolution mostly adds grip, which inflates corner rates more than straight-line ones. “Pole lap” means the fastest lap of qualifying (at 2025 Hungary that was a Q2 lap, faster than the Q3 pole). Wet qualifying (2025 Las Vegas) is left out. Intervals are 90% bootstrap intervals over events, widened for small samples (expanded percentile bootstrap; plain percentile intervals cover only about 80% with five to ten events).");

    fill("finding_text", "Splitting each main straight into ten equal pieces and comparing speeds piece by piece shows where the straight-line time goes. Aston Martin starts the straights " + f(-((SP26.bins || [])[0] || {}).gap_kmh, 1) +
      " km/h down, " + (function () {
        var c = SP26.first_half_ci90 || [NaN, NaN];
        return c[0] <= 0 && c[1] >= 0 ? "holds that through the first half (" + f(SP26.first_half_kmh, 1) + " km/h, CI " + ci(c, 1) + ") and loses "
          : (SP26.first_half_kmh < 0 ? "loses " : "gains ") + f(Math.abs(SP26.first_half_kmh), 1) + " km/h over the first half (CI " + ci(c, 1) + ") and ";
      })() + f(-SP26.second_half_kmh, 1) + " km/h more in the second half (CI " + ci(SP26.second_half_ci90, 1) +
      "), at full throttle: its drivers are not lifting early. The loss appears on " + SP26.n_straights_losing_late + " of " + SP26.n_straights + " main straights that start and end away from the timing line (" + SP26.n_events +
      " events); leaving out any one event keeps the average between " + f((SP26.second_half_loo_range || [])[1], 1) + " and " + f((SP26.second_half_loo_range || [])[0], 1) +
      " km/h. " + ((SP26.first_half_ci90 || [0, 0])[1] < 0 ? "Losing ground from the first metres means weaker acceleration than the field, not only a lower top speed. " : "Holding the gap while starting slower already means weaker acceleration than the field. ") + "The shape does not identify the cause: a point-mass simulation reproduces it with extra drag alone, and energy deployment ending earlier or harvesting at full throttle fit as well. " +
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
    fill("decomp_text", "On the main straights alone this costs " + f(SP26.time_total_s, 2) + " s per lap (CI " + ci(SP26.time_total_ci90, 2) + "), of which " + f(SP26.time_build_s, 2) +
      " s (CI " + ci(st, 2) + ") is the speed lost along the straight rather than carried from the corner.");

    if (UPG) {
      var gh = UPG.grip_high_rel;
      var effs = (S.upgrades || {}).effects || [], uh = effs.filter(function (e) { return e.season === 2026 && e.event === UPG.event; })[0] || {};
      var cpS = CP26.prior_sensitivity || [], p0s = cpS.map(function (r) { return r.p_no_change; });
      fill("upgrade_text", "Aston Martin declared a " + (declaredParts(UPG.event, 2026) || "major") + " upgrade at the " + esc(UPG.event) +
        ". A changepoint model that is not told upgrade dates rates the " + esc(CP26.map_event || "–") + " the most likely place for a single shift in its qualifying pace (posterior " + f(CP26.map_probability, 2) +
        ", against " + f(CP26.p_no_change, 2) + " for no change; " + f(Math.min.apply(null, p0s), 2) + "–" + f(Math.max.apply(null, p0s), 2) + " across the prior settings tried). Given a change, the step is " +
        sgn(CP26.effect_pct, 2) + "% of lap time (CI " + ci(CP26.effect_ci90_pct, 2) + "); allowing for no change it averages " + sgn(CP26.effect_avg_pct, 2) + "% (CI " + ci(CP26.effect_avg_ci90_pct, 2) + "). " +
        (CP26.two_change_events && CP26.bf_two_vs_one > 3 ? "But the season fits a rise and a fall better than one step: a model with two changes (" + sgn((CP26.two_change_steps_pct || [])[0], 1) + "% at the " + esc(CP26.two_change_events[0]) +
          ", " + sgn((CP26.two_change_steps_pct || [])[1], 1) + "% at the " + esc(CP26.two_change_events[1]) + ") is " + f(CP26.bf_two_vs_one, 1) + " times more likely, so much of the drop undoes a mid-season peak. " : "") +
        "Fast-corner grip relative to the other teams went from " + f(gh.before.mean * 100, 1) + "% to " + f(gh.after.mean * 100, 1) + "% (" + gh.before.n + " events before, only " + gh.after.n +
        " after with clean geometry). The difference-in-differences test cannot settle it either: Aston Martin’s own 2026 estimates vary about " + f(uh.noise_ratio, 0) +
        " times more than any rival’s, so beating every rival’s placebo means little, and against its own " + (uh.n_time_placebos || "–") + " other dates no test can go below p = " + f(1 / (1 + (uh.n_time_placebos || 0)), 2) +
        " (the " + esc(UPG.event) + " gets " + f(uh.time_placebo_p, 2) + "). Suggestive, not established.");
    }
  }
  function declaredParts(event, season) {
    var u = ((S.upgrades || {}).declared || []).filter(function (d) { return d.season === season && d.grand_prix === event; })[0];
    var n = u && (u.components.match(/(\d+) items/) || [])[1];
    return n ? n + "-part" : null;
  }
  function minVal(o) { return Math.min.apply(null, Object.values(o || {}).concat([NaN]).filter(isFinite)); }
  function maxVal(o) { return Math.max.apply(null, Object.values(o || {}).filter(isFinite)); }

  // ------------------------------------------------------------------ finding charts
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
    function tr(key, name, color, sym, dy) {
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

  function renderRates(t) {
    t = t || theme();
    var season = current.rateSeason || "2026", o = RATES[season] || {};
    var teams = Object.keys(o).filter(function (k) { return o[k].n_events >= 5; });
    var xs = teams.map(function (k) { return o[k].corner_rate_pct; }), ys = teams.map(function (k) { return secRate(o[k], "straights").v; });
    var lim = Math.max.apply(null, xs.concat(ys).filter(isFinite)) * 1.15;
    var guide = [0.25, 0.5, 1].map(function (r) {
      return { x: [0, lim], y: [0, lim * r], type: "scatter", mode: "lines", line: { color: t.rule, width: 1, dash: r === 1 ? "solid" : "dot" }, hoverinfo: "skip", showlegend: false };
    });
    var notes = [0.25, 0.5, 1].map(function (r) { return { x: lim, y: lim * r, xanchor: "right", yanchor: "bottom", text: r === 1 ? "straights = corners" : "× " + r, showarrow: false, font: { size: 10, color: t.muted } }; });
    plot("ch-rates", guide.concat([{
      x: xs, y: ys, text: teams.map(function (k) { return k === TARGET || o[k].lap_rate_pct > 2.5 ? k : ""; }), hovertext: teams,
      type: "scatter", mode: "markers+text", textposition: "top left", textfont: { size: 11, color: t.ink2 },
      marker: { size: teams.map(function (k) { return k === TARGET ? 13 : 9; }), color: teams.map(function (k) { return k === TARGET ? t.amr : t.field; }), line: { color: t.surface, width: 2 } },
      error_y: { type: "data", symmetric: false, array: teams.map(function (k) { var r = secRate(o[k], "straights"); return r.hi - r.v; }), arrayminus: teams.map(function (k) { var r = secRate(o[k], "straights"); return r.v - r.lo; }), color: t.rule, thickness: 1, width: 0 },
      customdata: teams.map(function (k) { return [o[k].lap_rate_pct, o[k].straight_to_corner_ratio, o[k].n_events]; }),
      hovertemplate: "%{hovertext}<br>corners %{x:.2f}% · straights %{y:.2f}%<br>lap %{customdata[0]:.2f}% · ratio %{customdata[1]:.2f} · %{customdata[2]} events<extra></extra>",
    }]), layout(t, { margin: { l: 56, r: 16, t: 26, b: 44 }, xaxis: { title: { text: "loss rate in corners, % of pole's time there" }, range: [0, lim] },
      yaxis: { title: { text: "loss rate on straights, %" }, range: [-0.6, lim] }, annotations: notes }));
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

  // ------------------------------------------------------------------ upgrades
  function upgradeEvents(season) {
    return ((S.upgrades || {}).declared || []).filter(function (u) { return u.season === season && (u.major_performance_upgrade === "major" || u.major_performance_upgrade === "partial"); });
  }
  function renderUpgradeParts(t) {
    t = t || theme();
    var series = (S.amr_component_series || {})["2026"] || [];
    var loo = {}; ((UPG || {}).grip_high_rel || { per_event: [] }).per_event.forEach(function (r) { loo[r.round] = r; });
    var gs = series.filter(function (r) { return loo[r.round]; });
    plot("ch-grip26", [{ x: gs.map(function (r) { return short(r.event); }), y: gs.map(function (r) { return loo[r.round].ratio; }), type: "scatter", mode: "lines+markers",
      error_y: { type: "data", array: gs.map(function (r) { return 1.645 * loo[r.round].se; }), color: t.amr, thickness: 1, width: 0 },
      line: { color: t.amr, width: 2 }, marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } }, hovertemplate: "%{x}<br>%{y:.3f} of the other teams' median<extra></extra>", connectgaps: true }],
      layout(t, { yaxis: { title: { text: "ratio to other teams' median" }, tickformat: ".2f" }, xaxis: { tickangle: -40 }, shapes: upgradeShapes(t, gs, 2026).concat([{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 1, y1: 1, line: { color: t.muted, width: 1, dash: "dot" } }]), annotations: upgradeNotes(t, series, 2026) }));
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
    var up = S.upgrades || {}, eff = up.effects || [];
    var rows = eff.map(function (e) {
      var detectable = e.mde_pct != null && Math.abs(e.effect_pct) >= e.mde_pct;
      var verdict = e.lead_p_holm <= 0.1 ? "clear after correction" : (e.lead_p <= 0.1 ? "suggestive, not after correction" : "not distinguishable");
      var ref = e.lead_test === "time" ? "own other dates" : "rivals";
      return "<tr><td>" + e.season + " " + esc(short(e.event)) + '</td><td class="num">' + sgn(e.effect_pct, 2) + '%</td><td class="num">' + (e.mde_pct == null ? "not reachable" : f(e.mde_pct, 2) + "%") +
        '</td><td class="num">' + e.n_pre + " / " + e.n_post + '</td><td class="num">' + f(e.team_placebo_p, 2) + '</td><td class="num">' + f(e.time_placebo_p, 2) + "</td><td>" + ref +
        ' <span class="hint">(noise ×' + f(e.noise_ratio, 1) + ')</span></td><td class="num">' + f(e.lead_p_holm, 2) + "</td><td>" +
        '<span class="pill ' + (e.lead_p_holm <= 0.1 ? "yes" : "no") + '">' + verdict + "</span>" + (e.overlapping && e.overlapping.length ? ' <span class="hint">overlaps ' + e.overlapping.map(short).join(", ") + "</span>" : "") +
        (detectable ? "" : ' <span class="hint">below detectable size</span>') + "</td></tr>";
    });
    $("tbl-did").innerHTML = $("tbl-did").querySelector("caption").outerHTML +
      '<thead><tr><th>Upgrade</th><th class="num">Effect on gap</th><th class="num">Detectable</th><th class="num">Events pre / post</th><th class="num">p vs rivals</th><th class="num">p vs own dates</th><th>Reference used</th><th class="num">Holm-adjusted</th><th>Verdict</th></tr></thead><tbody>' +
      rows.join("") + '</tbody><tfoot><tr><td colspan="9" class="hint">Each upgrade is compared with rivals given the same date (team placebos) and with Aston Martin at its other dates (time placebos). When Aston Martin’s own estimates are much noisier than its rivals’ (noise ratio above 1.5), only the second is a fair reference. Detectable = the effect the reference test finds with 80% power at the 10% level. With ' +
      eff.length + " upgrades tested, the smallest Holm-adjusted p any of them could reach is " + f(up.holm_floor_lead, 2) + ", so none can be called significant after correction whatever its size.</td></tr></tfoot>";
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
    $("lap-hint").textContent = e.circuit && e.circuit.location ? e.circuit.location + (e.wet_session ? " · wet session, left out of the season analyses" : "") + " · " + (e.official_pole && e.official_pole.driver !== e.pole.driver ? "fastest lap " : "pole ") + e.pole.driver + " " + f(e.pole.lap_time_s, 3) + " s · gap " + sgn(c.total_delta_s, 3) + " s" : "";
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
    if (!ls) {
      $("sim-sub").textContent = "no calibration for this event (geometry check failed)";
      Plotly.purge($("ch-sim")); Plotly.purge($("ch-disc")); $("tbl-params").innerHTML = "";
      $("sandbox").hidden = true; SB.base = null;
      return;
    }
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
    $("energy-sub").textContent = short(e.event) + " " + e.season + " · pole and Aston Martin laps";
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
    var rt = (REL26.clip_time_loss_s || {});
    fill("energy_text", "In 2026 cars reach peak speed part-way along a straight and then slow down at full throttle. Speed-dependent power alone, including the regulated MGU-K taper, cannot do that; it means power falls with time as deployment ends or the car harvests. Acceleration here has gravity removed using GPS altitude, and only decelerations lasting at least 30 m count. The field loses on average " +
      f(fieldLoss, 3) + " s per lap against holding peak speed, against " + f(loss25, 3) + " s in 2025. Aston Martin's loss on this measure (" + sgn(rt.mean, 3) + " s vs the other teams, CI " + f(rt.lo, 3) + " to " + f(rt.hi, 3) +
      ") is not distinguishable from the field, so this narrow measure of clipping does not by itself explain its straight-line deficit.");
  }

  // ------------------------------------------------------------------ race pace
  function renderRace(t) {
    t = t || theme();
    var rp = (S.race_pace_by_event || []).filter(function (r) { return r.team === TARGET; }).sort(function (a, b) { return a.season - b.season || a.round - b.round; });
    var x = rp.map(function (r) { return short(r.event) + " " + String(r.season).slice(2); });
    // Qualifying gap in seconds to the best team = Aston Martin's lap minus the pole lap
    var qgap = {}; M.forEach(function (m) { if (m.amr_gap_s != null) qgap[m.season + "-" + m.round] = m.amr_gap_s; });
    plot("ch-race", [
      { x: x, y: rp.map(function (r) { var v = qgap[r.season + "-" + r.round]; return v == null ? null : v; }), name: "qualifying gap", type: "scatter", mode: "markers",
        marker: { size: 8, symbol: "diamond-open", color: t.ref, line: { width: 2, color: t.ref } }, hovertemplate: "%{x}<br>qualifying +%{y:.2f} s<extra></extra>" },
      { x: x, y: rp.map(function (r) { return r.gap_s; }), name: "corrected race pace", type: "scatter", mode: "markers", marker: { size: 9, color: t.amr, line: { color: t.surface, width: 2 } },
        error_y: { type: "data", symmetric: false, array: rp.map(function (r) { return r.ci_hi - r.gap_s; }), arrayminus: rp.map(function (r) { return r.gap_s - r.ci_lo; }), color: t.amr, thickness: 1.2, width: 0 },
        hovertemplate: "%{x}<br>race pace +%{y:.2f} s/lap<extra></extra>" },
    ], layout(t, { showlegend: true, yaxis: { title: { text: "s per lap behind the best team" }, rangemode: "tozero" }, xaxis: { tickangle: -50 } }));
    var by = byKey(S.race_pace || [], "season");
    var g25 = (by[2025] || []).filter(function (r) { return r.team === TARGET; })[0] || {}, g26 = (by[2026] || []).filter(function (r) { return r.team === TARGET; })[0] || {};
    fill("race_text", "Every green-flag lap of every dry race is fitted with driver pace, compound offsets, tyre degradation per lap of age and a fuel effect per lap, so the comparison is at equal fuel and fresh tyres. Intervals come from a delete-one-stint jackknife: each stint is left out in turn and the model refitted, so stint-level offsets such as traffic or tyre preparation enter the uncertainty (simulated coverage of a nominal 90% interval: 93% for the fuel effect, 90–97% for team gaps). A driver with only one stint cannot be left out, so intervals involving them are too narrow. Aston Martin’s corrected race pace averaged " +
      f(g25.mean, 2) + " s per lap off the best team in 2025 (" + g25.count + " races) and " + f(g26.mean, 2) + " s in 2026 (" + g26.count + " races).");
  }

  // ------------------------------------------------------------------ models
  function renderModels(t) {
    t = t || theme();
    var cm = S.corner_model || {};
    var names = { steady: "Steady-state formula (aero term not identified: v = √(aR))", physics: "Lap sim on track geometry, nominal car from training events", ml: "Gradient boosting only", hybrid: "Hybrid: lap sim + boosted residual" };
    $("tbl-cm").innerHTML = "<caption>Out of sample by whole circuit (" + cm.n_circuits + " circuits, " + cm.n_events + " events, " + cm.n_rows + " corners)</caption>" +
      '<thead><tr><th>Model</th><th class="num">RMSE</th><th class="num">R²</th><th class="num">Within-corner R²</th></tr></thead><tbody>' +
      (cm.metrics || []).map(function (r) { return "<tr><td>" + names[r.model] + '</td><td class="num">' + f(r.rmse_kmh, 1) + ' km/h</td><td class="num">' + f(r.r2, 3) + '</td><td class="num">' + (r.model === "steady" || r.model === "physics" ? "n/a" : f(r.within_corner_r2, 2)) + "</td></tr>"; }).join("") +
      '</tbody><tfoot><tr><td colspan="4" class="hint">Within-corner R² is n/a for the physics-only models: they predict the same speed for every car at a corner.</td></tr></tfoot>';
    var mm = {}; (cm.metrics || []).forEach(function (r) { mm[r.model] = r; });
    var ce = cm.coverage_by_event || {};
    fill("corner_text", "Predicts each corner’s minimum speed at a circuit the model has never seen (every event there, in both seasons, is held out together). The physics baseline runs the lap simulator on the held-out track’s GPS geometry with a nominal car calibrated only on the training events, with nothing fitted to the held-out circuit. On unseen circuits it beats a black-box model clearly (R² " +
      f((mm.physics || {}).r2, 2) + " vs " + f((mm.ml || {}).r2, 2) + "), and adding machine learning on top changes little (" + f((mm.hybrid || {}).r2, 2) + "). Almost all of the variance is between corners, so R² mostly measures geometry: none of the models explains differences between cars at the same corner (within-corner R² ≈ 0 or below). Split-conformal 90% intervals cover " +
      f(cm.conformal_coverage * 100, 1) + "% of held-out corners overall, but coverage varies by event (median " + f(ce.median * 100, 0) + "%, worst " + f(ce.min * 100, 0) + "%, " + f(ce.share_below_80pct * 100, 0) + "% of events below 80%).");
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
    var best = wt.best_rotation_by_event || [];
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

  function syncHeaderOffset() {
    var h = document.querySelector(".masthead");
    if (h) document.documentElement.style.scrollPaddingTop = (h.getBoundingClientRect().height + 8) + "px";
  }

  function start() {
    syncHeaderOffset();
    window.addEventListener("resize", syncHeaderOffset);
    heroText();
    seg("seg-rates", ["2025", "2026"], "2026", function (v) { current.rateSeason = v; renderRates(); });
    seg("seg-season", ["2025", "2026"], current.gapSeason, function (v) { current.gapSeason = v; renderGap(); renderCP(); });
    seg("seg-aero", ["2025", "2026"], current.aeroSeason, function (v) { current.aeroSeason = v; renderAero(); });
    seg("seg-deficit", ["2025", "2026"], current.deficitSeason, function (v) { current.deficitSeason = v; renderModels(); });
    [renderProfile, renderHalves, renderRates, renderJoint, renderUpgradeParts, renderGap, renderCP, renderAero, renderSens, renderLap, renderSim, renderCalAcc, renderEnergy, renderRace, renderModels].forEach(register);
    renderDiD(); renderMethod();
    initEvents();
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", rerender);
    new MutationObserver(rerender).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }
  if (!window.Plotly) { document.addEventListener("DOMContentLoaded", start); } else { start(); }
})();
