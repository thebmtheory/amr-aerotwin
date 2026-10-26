/* Quasi-steady-state point-mass lap simulator: a line-for-line port of physics/lapsim.py.
   Parity with the Python implementation is checked by backend/tests/test_report.py. */
(function (root) {
  "use strict";
  var G = 9.80665;
  var V_CAP = 110.0;

  function maxCorneringSpeed(kappa, p) {
    var out = new Float64Array(kappa.length);
    var aero = p.mu * p.rho_kg_m3 * p.cla_m2 / (2.0 * p.mass_kg);
    for (var i = 0; i < kappa.length; i++) {
      var denom = Math.abs(kappa[i]) - aero;
      var v2 = denom > 1e-12 ? p.mu * G / denom : V_CAP * V_CAP;
      out[i] = Math.min(Math.sqrt(v2), V_CAP);
    }
    return out;
  }

  function passes(kAbs, cda, vap, ds, p) {
    var n = kAbs.length, m = p.mass_kg, mu = p.mu, rho = p.rho_kg_m3, cla = p.cla_m2, kx = p.long_grip_scale;
    var fwd = new Float64Array(n), bwd = new Float64Array(n);
    var v = vap[0], i, q, aTot, aLat, ratio, aGrip, a, v2;
    fwd[0] = v;
    for (i = 0; i < n - 1; i++) {
      q = 0.5 * rho * v * v;
      aTot = mu * (G + q * cla / m);
      aLat = v * v * kAbs[i];
      ratio = aLat / aTot;
      aGrip = ratio < 1.0 ? kx * aTot * Math.sqrt(1.0 - ratio * ratio) : 0.0;
      var aPow = p.power_w / (m * Math.max(v, 1.0));
      a = Math.min(aGrip, aPow) - q * cda[i] / m - G * p.crr;
      v2 = v * v + 2.0 * a * ds;
      v = v2 > 1.0 ? Math.sqrt(v2) : 1.0;
      if (v > vap[i + 1]) v = vap[i + 1];
      fwd[i + 1] = v;
    }
    v = vap[n - 1];
    bwd[n - 1] = v;
    for (i = n - 1; i > 0; i--) {
      q = 0.5 * rho * v * v;
      aTot = mu * (G + q * cla / m);
      aLat = v * v * kAbs[i];
      ratio = aLat / aTot;
      aGrip = ratio < 1.0 ? kx * aTot * Math.sqrt(1.0 - ratio * ratio) : 0.0;
      var aB = aGrip + q * cda[i] / m + G * p.crr;
      v = Math.sqrt(v * v + 2.0 * aB * ds);
      if (v > vap[i - 1]) v = vap[i - 1];
      bwd[i - 1] = v;
    }
    return [fwd, bwd];
  }

  function simulateLap(distance, kappa, p, lowDragMask, lapLength) {
    var n = distance.length, ds = distance[1] - distance[0], i;
    var cda = new Float64Array(n);
    for (i = 0; i < n; i++) {
      cda[i] = lowDragMask && p.low_drag_cda_m2 != null && lowDragMask[i] ? p.low_drag_cda_m2 : p.cda_m2;
    }
    var vap = maxCorneringSpeed(kappa, p);
    var k2 = new Float64Array(2 * n), c2 = new Float64Array(2 * n), va2 = new Float64Array(2 * n);
    for (i = 0; i < 2 * n; i++) { k2[i] = Math.abs(kappa[i % n]); c2[i] = cda[i % n]; va2[i] = vap[i % n]; }
    var res = passes(k2, c2, va2, ds, p);
    var v = new Float64Array(n);
    for (i = 0; i < n; i++) v[i] = Math.min(res[0][n + i], res[1][i], vap[i]);
    var t = 0;
    for (i = 0; i < n - 1; i++) t += 2.0 * ds / (v[i] + v[i + 1]);
    var length = lapLength != null ? lapLength : distance[n - 1] + ds;
    var closing = length - distance[n - 1];
    var lapTime = t + 2.0 * closing / (v[n - 1] + v[0]);
    return { speed: v, lapTime: lapTime };
  }

  var api = { simulateLap: simulateLap, maxCorneringSpeed: maxCorneringSpeed };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LapSim = api;
})(this);
