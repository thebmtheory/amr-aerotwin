/* Track-view arithmetic shared by the page (window.TrackMath) and the tests (node require).
   Per-track entries come from report/explorer.py; the season analysis defines the rules:
   loss rate = seconds lost to the reference lap ÷ seconds the reference lap spends there,
   summed over tracks; a team is its fastest lap that passed the data checks; a lap slower
   than 107% of the fastest is not pace. */
(function (root) {
  "use strict";
  var SECS = ["straights", "high", "medium", "low"];

  // A lap time that counts for pace (within 107% of the fastest lap)
  function rep(e, d) { var r = e.timing[d]; return r && r.representative !== false ? r : null; }

  // The faster of `drivers` whose lap passed the data checks at this track
  function bestDriver(e, drivers) {
    var best = null;
    drivers.forEach(function (d) { if (e.drivers[d] && e.timing[d] && (!best || e.timing[d].lap_time_s < e.timing[best].lap_time_s)) best = d; });
    return best;
  }

  // Loss rates over a set of tracks. `pick(e)` gives seconds lost per section at a track, or
  // null where that lap does not exist; such tracks drop out of numerator and denominator.
  function sumRates(evs, pick) {
    var L = {}, R = {}, n = 0;
    SECS.forEach(function (k) { L[k] = 0; R[k] = 0; });
    evs.forEach(function (e) {
      var s = pick(e); if (!s) return; n++;
      SECS.forEach(function (k) { L[k] += s[k]; R[k] += e.ref_time_s[k]; });
    });
    if (!n) return null;
    function pct(l, r) { return r > 0 ? 100 * l / r : null; }
    var cl = L.high + L.medium + L.low, cr = R.high + R.medium + R.low;
    var out = { n: n, corners: pct(cl, cr), straights: pct(L.straights, R.straights), lap: pct(cl + L.straights, cr + R.straights), loss: L, ref: R };
    SECS.forEach(function (k) { out[k] = pct(L[k], R[k]); });
    return out;
  }
  function amrPick(drivers) { return function (e) { var d = bestDriver(e, drivers); return d ? e.drivers[d].sections_s : null; }; }
  function drvPick(d) { return function (e) { return e.drivers[d] ? e.drivers[d].sections_s : null; }; }
  function teamPick(team) { return function (e) { return e.team_sections_s[team] || null; }; }

  // A team's compared lap at a track: the reference lap plus its section losses
  function comparedLap(e, sections) { return sections ? SECS.reduce(function (t, k) { return t + sections[k]; }, e.reference.lap_time_s) : null; }

  var api = { SECS: SECS, rep: rep, bestDriver: bestDriver, sumRates: sumRates, amrPick: amrPick, drvPick: drvPick, teamPick: teamPick, comparedLap: comparedLap };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TrackMath = api;
})(this);
