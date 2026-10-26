"""Season-level performance: qualifying gaps, car vs driver variance, pace changepoints and
upgrade effects.

Pace metric: the "supertime" gap, team best qualifying lap as % slower than the fastest lap
of the event. Percentages make tracks of different lap length comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import lgamma, log, pi

import numpy as np
import pandas as pd

from amr_aerotwin.modeling.intervals import boot_ci


# --------------------------------------------------------------------------- supertimes
def supertime_table(quali: pd.DataFrame) -> pd.DataFrame:
    """Team-best gap to the fastest lap (%) per event.

    `quali` columns: season, event, round, team, driver, lap_time_s.
    """
    best = quali.groupby(["season", "round", "event"])["lap_time_s"].transform("min")
    q = quali.assign(gap_pct=(quali["lap_time_s"] / best - 1.0) * 100.0)
    team = q.groupby(["season", "round", "event", "team"], as_index=False)["gap_pct"].min()
    return team.sort_values(["season", "round", "gap_pct"]).reset_index(drop=True)


# --------------------------------------------------------------------------- car vs driver
@dataclass(frozen=True)
class VarianceSplit:
    car_share: float  # pooled: mean between-team component / mean total
    car_share_ci90: tuple[float, float]
    median_event_share: float  # median of the per-event shares
    event_share_iqr: tuple[float, float]
    sigma_car_pct: float
    sigma_within_pct: float
    n_events: int


def _anova_components(df: pd.DataFrame) -> tuple[float, float] | None:
    """One-way random-effects ANOVA within one event: (between-team var, within-team var)."""
    g = df.groupby("team")["gap_pct"]
    sizes = g.size()
    df = df[df["team"].isin(sizes[sizes >= 2].index)]
    if df["team"].nunique() < 4:
        return None
    g = df.groupby("team")["gap_pct"]
    k, n = g.ngroups, len(df)
    grand = df["gap_pct"].mean()
    ssb = float((g.size() * (g.mean() - grand) ** 2).sum())
    ssw = float(((df["gap_pct"] - g.transform("mean")) ** 2).sum())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - (g.size() ** 2).sum() / n) / (k - 1)
    return max((msb - msw) / n0, 0.0), msw


def car_vs_driver_variance(quali: pd.DataFrame, n_boot: int = 500, seed: int = 2) -> VarianceSplit:
    """Between-team share of qualifying-gap variance (car, plus how drivers sort into teams)
    vs within-team share (driver, lap execution, session and track evolution).

    Components are estimated per event (so track effects cancel) and averaged; the
    bootstrap resamples events.
    """
    best = quali.groupby(["season", "round"])["lap_time_s"].transform("min")
    q = quali.assign(gap_pct=(quali["lap_time_s"] / best - 1.0) * 100.0)
    comps = [c for _, ev in q.groupby(["season", "round"]) if (c := _anova_components(ev)) is not None]
    arr = np.array(comps)

    def share(a: np.ndarray) -> float:
        b, w = a[:, 0].mean(), a[:, 1].mean()
        return float(b / (b + w)) if b + w > 0 else float("nan")

    rng = np.random.default_rng(seed)
    boots = [share(arr[rng.integers(0, len(arr), len(arr))]) for _ in range(n_boot)]
    per_event = arr[:, 0] / np.maximum(arr[:, 0] + arr[:, 1], 1e-12)
    return VarianceSplit(
        car_share=share(arr),
        car_share_ci90=boot_ci(boots, len(arr)),
        median_event_share=float(np.median(per_event)),
        event_share_iqr=(float(np.percentile(per_event, 25)), float(np.percentile(per_event, 75))),
        sigma_car_pct=float(np.sqrt(arr[:, 0].mean())),
        sigma_within_pct=float(np.sqrt(arr[:, 1].mean())),
        n_events=len(arr),
    )


# --------------------------------------------------------------------------- changepoint
def log_marginal_likelihood(x: np.ndarray, y: np.ndarray, g: float = 10.0, a0: float = 1.0, b0: float = 1.0) -> float:
    """Exact log evidence of a Bayesian linear model with a normal-inverse-gamma prior.

    beta | s2 ~ N(0, s2 g I),  s2 ~ InvGamma(a0, b0). Use with standardised y.
    """
    n, p = x.shape
    v0_inv = np.eye(p) / g
    vn_inv = v0_inv + x.T @ x
    vn = np.linalg.inv(vn_inv)
    bn = vn @ x.T @ y
    an = a0 + n / 2.0
    bnn = b0 + 0.5 * float(y @ y - bn @ vn_inv @ bn)
    _, logdet_vn = np.linalg.slogdet(vn)
    logdet_v0 = p * log(g)
    return (
        -0.5 * n * log(2 * pi)
        + 0.5 * (logdet_vn - logdet_v0)
        + a0 * log(b0) - an * log(bnn)
        + lgamma(an) - lgamma(a0)
    )


@dataclass(frozen=True)
class ChangepointResult:
    rounds: np.ndarray
    events: list[str]
    posterior_tau: np.ndarray  # P(change happens at event i | data), i aligned with `rounds`
    p_no_change: float
    map_index: int | None
    map_probability: float  # posterior probability of the single most likely location
    effect_mean_pct: float  # step averaged over the posterior of tau, given a change (- = faster)
    effect_ci90_pct: tuple[float, float]
    effect_avg_pct: float = float("nan")  # step averaged over all models, no change (step 0) included
    effect_avg_ci90_pct: tuple[float, float] = (float("nan"), float("nan"))


def _step_posterior(x0: np.ndarray, z: np.ndarray, tau: int, g: float) -> tuple[float, float, float]:
    """Posterior (mean, scale, dof) of the step coefficient for a change at `tau` (Student-t)."""
    n = len(z)
    x = np.column_stack([x0, (np.arange(n) >= tau).astype(float)])
    p = x.shape[1]
    vn_inv = np.eye(p) / g + x.T @ x
    vn = np.linalg.inv(vn_inv)
    bn = vn @ x.T @ z
    an = 1.0 + n / 2.0
    bnn = 1.0 + 0.5 * float(z @ z - bn @ vn_inv @ bn)
    return float(bn[-1]), float(np.sqrt(bnn / an * vn[-1, -1])), 2 * an


def bayesian_changepoint(
    y: np.ndarray,
    covariate: np.ndarray | None = None,
    events: list[str] | None = None,
    rounds: np.ndarray | None = None,
    min_segment: int = 3,
    prior_no_change: float = 0.5,
    g: float = 10.0,
    n_draws: int = 20000,
    seed: int = 0,
) -> ChangepointResult:
    """Single mean-shift changepoint with exact model evidence for every location.

    Models: M0 y = a + b x + e;  M_tau y = a + b x + d 1[i >= tau] + e. Prior mass
    `prior_no_change` on M0, the rest uniform over admissible tau. The reported step is
    averaged over the posterior of tau (not conditioned on the most likely tau), so its
    interval includes the uncertainty about *where* the change happened.
    """
    y = np.asarray(y, float)
    n = len(y)
    mu, sd = y.mean(), y.std() if y.std() > 0 else 1.0
    z = (y - mu) / sd
    base = [np.ones(n)]
    if covariate is not None:
        c = np.asarray(covariate, float)
        base.append((c - c.mean()) / (c.std() if c.std() > 0 else 1.0))
    x0 = np.column_stack(base)
    taus = list(range(min_segment, n - min_segment + 1))
    lml0 = log_marginal_likelihood(x0, z, g=g)
    lmls = np.array([log_marginal_likelihood(np.column_stack([x0, (np.arange(n) >= t).astype(float)]), z, g=g) for t in taus])
    log_prior_tau = np.log((1 - prior_no_change) / max(len(taus), 1))
    logw = np.concatenate([[np.log(prior_no_change) + lml0], log_prior_tau + lmls])
    w = np.exp(logw - logw.max())
    w /= w.sum()
    post = np.zeros(n)
    post[taus] = w[1:]
    map_i = int(taus[int(np.argmax(w[1:]))]) if taus else None

    eff, ci = float("nan"), (float("nan"), float("nan"))
    if taus and w[1:].sum() > 0:
        rng = np.random.default_rng(seed)
        wt = w[1:] / w[1:].sum()
        params = [_step_posterior(x0, z, t, g) for t in taus]
        pick = rng.choice(len(taus), size=n_draws, p=wt)
        draws = np.array([params[i][0] + params[i][1] * rng.standard_t(params[i][2]) for i in pick]) * sd
        eff = float(np.mean(draws))
        ci = (float(np.percentile(draws, 5)), float(np.percentile(draws, 95)))
        # Unconditional: with probability P(no change) the step is exactly zero
        avg = np.where(rng.random(n_draws) < w[0], 0.0, draws)
        eff_avg, ci_avg = float(np.mean(avg)), (float(np.percentile(avg, 5)), float(np.percentile(avg, 95)))
    else:
        eff_avg, ci_avg = float("nan"), (float("nan"), float("nan"))
    return ChangepointResult(
        rounds=np.arange(n) if rounds is None else np.asarray(rounds),
        events=events or [str(i) for i in range(n)],
        posterior_tau=post,
        p_no_change=float(w[0]),
        map_index=map_i,
        map_probability=float(post[map_i]) if map_i is not None else float("nan"),
        effect_mean_pct=eff,
        effect_ci90_pct=ci,
        effect_avg_pct=eff_avg,
        effect_avg_ci90_pct=ci_avg,
    )


def _logsumexp(v: np.ndarray) -> float:
    m = float(np.max(v))
    return m + float(np.log(np.sum(np.exp(v - m))))


def changepoint_count_evidence(
    y: np.ndarray, covariate: np.ndarray | None = None, min_segment: int = 3, g: float = 10.0,
) -> dict[str, object]:
    """Evidence for zero, one or two mean shifts, each averaged uniformly over its admissible locations.

    A season that rises and then falls back (a mid-season peak) can make a single step look
    convincing; comparing against two steps shows whether one step is the better description.
    Returns log evidences, Bayes factors and the most likely pair of change locations with
    the two steps (posterior means, in the units of y).
    """
    y = np.asarray(y, float)
    n = len(y)
    mu, sd = y.mean(), y.std() if y.std() > 0 else 1.0
    z = (y - mu) / sd
    base = [np.ones(n)]
    if covariate is not None:
        c = np.asarray(covariate, float)
        base.append((c - c.mean()) / (c.std() if c.std() > 0 else 1.0))
    x0 = np.column_stack(base)
    step = lambda t: (np.arange(n) >= t).astype(float)  # noqa: E731
    taus = list(range(min_segment, n - min_segment + 1))
    pairs = [(a, b) for a in taus for b in taus if b - a >= min_segment]
    lml0 = log_marginal_likelihood(x0, z, g=g)
    l1 = np.array([log_marginal_likelihood(np.column_stack([x0, step(t)]), z, g=g) for t in taus])
    l2 = np.array([log_marginal_likelihood(np.column_stack([x0, step(a), step(b)]), z, g=g) for a, b in pairs])
    ev1 = _logsumexp(l1) - np.log(len(l1)) if len(l1) else -np.inf
    ev2 = _logsumexp(l2) - np.log(len(l2)) if len(l2) else -np.inf
    out: dict[str, object] = {"log_evidence": [float(lml0), float(ev1), float(ev2)],
                              "bf_one_vs_none": float(np.exp(ev1 - lml0)), "bf_two_vs_one": float(np.exp(ev2 - ev1))}
    if pairs:
        k = int(np.argmax(l2))
        a, b = pairs[k]
        x = np.column_stack([x0, step(a), step(b)])
        vn = np.linalg.inv(np.eye(x.shape[1]) / g + x.T @ x)
        bn = vn @ x.T @ z
        out.update({"map_pair_index": [a, b], "map_pair_probability": float(np.exp(l2[k] - _logsumexp(l2))),
                    "map_pair_steps": [float(bn[-2] * sd), float(bn[-1] * sd)]})
    return out


# --------------------------------------------------------------------------- upgrades (DiD)
@dataclass(frozen=True)
class UpgradeEffect:
    season: int
    event: str
    effect_pct: float  # change in gap to pole after the upgrade vs rivals (negative = gained)
    team_placebo_p: float  # (1 + #rivals with |placebo| >= |effect|) / (1 + #rivals)
    time_placebo_p: float  # same over non-upgrade dates of the season
    n_pre: int  # treated team's events in the pre window
    n_post: int
    placebo_sd_pct: float  # spread of team placebos: the rivals' noise at this date
    mde_pct: float  # effect the leading test detects with 80% power at 10%, two-sided (see permutation_mde_sd)
    p_floor: float  # smallest team-placebo p this design can produce: 1 / (1 + number of rivals)
    overlapping: list[str]  # other declared upgrades inside this window
    placebo_effects: list[float]
    time_placebo_sd_pct: float = float("nan")  # spread of the treated team's own estimates at other dates
    noise_ratio: float = float("nan")  # time-placebo sd / team-placebo sd
    lead_test: str = "team"  # "time" when the treated team is much noisier than its rivals
    lead_p: float = float("nan")
    n_team_placebos: int = 0
    n_time_placebos: int = 0


def permutation_mde_sd(n_placebos: int, alpha: float = 0.10, power: float = 0.80) -> float:
    """Smallest effect, in units of the estimate's noise sd, that a two-sided permutation test
    against `n_placebos` placebos detects with the given power.

    p = (1 + #{|placebo| >= |effect|}) / (1 + N), so rejecting at `alpha` allows at most
    k = floor(alpha (1 + N)) - 1 placebos as extreme as the effect. With the effect estimate
    ~ N(delta, 1) and placebos ~ N(0, 1), P(reject | e) = P(Binomial(N, q(e)) <= k) with
    q(e) = 2 Phi(-|e|); the power is its average over e. With ten placebos this needs about
    2.9 sd (not the normal-theory 2.5), and below 1 / alpha - 1 placebos nothing is detectable.
    """
    from scipy import stats as st
    from scipy.integrate import trapezoid

    k = int(np.floor(alpha * (1 + n_placebos) + 1e-9)) - 1
    if n_placebos < 1 or k < 0:
        return float("inf")
    e = np.linspace(-12, 18, 6001)

    def pw(delta: float) -> float:
        q = 2 * st.norm.cdf(-np.abs(e))
        return float(trapezoid(st.binom.cdf(k, n_placebos, q) * st.norm.pdf(e - delta), e))

    lo, hi = 0.0, 15.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if pw(mid) < power else (lo, mid)
    return 0.5 * (lo + hi)


def _did_estimate(panel: pd.DataFrame, treated_team: str, start_round: int, window: int) -> tuple[float, int, int] | None:
    """Two-way fixed-effects DiD on rounds within +-window of `start_round`.

    gap(team, event) = team FE + event FE + team-specific track-type slope + delta * treated.
    Event fixed effects absorb anything common to all teams at a venue; the team-specific
    slope on the event's high-speed share controls for cars that suit some layouts.
    """
    rounds = sorted(panel["round"].unique())
    if start_round not in rounds:
        return None
    i0 = rounds.index(start_round)
    pre = rounds[max(0, i0 - window): i0]
    post = rounds[i0: i0 + window]
    if len(pre) < 2 or len(post) < 2:
        return None
    d = panel[panel["round"].isin(pre + post)].copy()
    teams = sorted(d["team"].unique())
    if treated_team not in teams:
        return None
    tr = d[d["team"] == treated_team]
    n_pre_t, n_post_t = int(tr["round"].isin(pre).sum()), int(tr["round"].isin(post).sum())
    if n_pre_t < 2 or n_post_t < 2:
        return None
    d["treated"] = ((d["team"] == treated_team) & d["round"].isin(post)).astype(float)
    cols = [pd.get_dummies(d["team"], dtype=float), pd.get_dummies(d["round"], prefix="r", dtype=float).iloc[:, 1:]]
    if "track_x" in d:
        xc = d["track_x"] - d["track_x"].mean()
        slopes = pd.get_dummies(d["team"], dtype=float).mul(xc, axis=0).add_prefix("x_").iloc[:, 1:]
        cols.append(slopes)
    x = pd.concat(cols + [d[["treated"]]], axis=1).to_numpy(float)
    beta = np.linalg.lstsq(x, d["gap_pct"].to_numpy(float), rcond=None)[0]
    return float(beta[-1]), n_pre_t, n_post_t


def upgrade_effects(
    panel: pd.DataFrame,
    upgrades: pd.DataFrame,
    treated_team: str,
    window: int = 4,
) -> list[UpgradeEffect]:
    """DiD effect of each declared upgrade with permutation (placebo) inference.

    `panel`: season, round, event, team, gap_pct[, track_x]. `upgrades`: season, event.
    Team placebos pretend each rival brought the upgrade on the same date; time placebos
    move the treated date to every other admissible round of the same season.
    """
    out = []
    for _, up in upgrades.iterrows():
        sp = panel[panel["season"] == up["season"]]
        match = sp[sp["event"] == up["event"]]
        if match.empty:
            continue
        r0 = int(match["round"].iloc[0])
        est = _did_estimate(sp, treated_team, r0, window)
        if est is None:
            continue
        eff, n_pre, n_post = est
        team_pl = [e[0] for t in sp["team"].unique() if t != treated_team
                   if (e := _did_estimate(sp, t, r0, window)) is not None]
        upgrade_rounds = set(
            sp[sp["event"].isin(upgrades[upgrades["season"] == up["season"]]["event"])]["round"]
        )
        time_pl = [e[0] for r in sorted(sp["round"].unique()) if r not in upgrade_rounds
                   if (e := _did_estimate(sp, treated_team, int(r), window)) is not None]

        def pval(pl: list[float], eff: float = eff) -> float:
            # Permutation p-value including the observed statistic: never below 1/(N+1)
            return float((1 + np.sum(np.abs(pl) >= abs(eff))) / (1 + len(pl))) if pl else float("nan")

        rounds_all = sorted(sp["round"].unique())
        i0 = rounds_all.index(r0)
        window_rounds = set(rounds_all[max(0, i0 - window): i0 + window])
        overlapping = sorted(
            str(e) for e in upgrades[upgrades["season"] == up["season"]]["event"]
            if e != up["event"] and not sp[(sp["event"] == e) & sp["round"].isin(window_rounds)].empty
        )
        sd_pl = float(np.std(team_pl, ddof=1)) if len(team_pl) > 2 else float("nan")
        sd_time = float(np.std(time_pl, ddof=1)) if len(time_pl) > 2 else float("nan")
        ratio = sd_time / sd_pl if sd_pl > 0 else float("nan")
        # Team placebos are a valid reference only if the treated team's own estimates are about
        # as noisy as its rivals'. When they are much noisier, beating every rival says little, and
        # the treated team's own estimates at other dates (time placebos) are the right null.
        lead = "time" if np.isfinite(ratio) and ratio > 1.5 else "team"
        n_lead = len(time_pl) if lead == "time" else len(team_pl)
        noise = max(v for v in (sd_pl, sd_time) if np.isfinite(v)) if np.isfinite(sd_pl) or np.isfinite(sd_time) else float("nan")
        out.append(UpgradeEffect(
            season=int(up["season"]), event=str(up["event"]), effect_pct=eff,
            team_placebo_p=pval(team_pl), time_placebo_p=pval(time_pl),
            n_pre=n_pre, n_post=n_post, placebo_sd_pct=sd_pl, mde_pct=permutation_mde_sd(n_lead) * noise,
            p_floor=1.0 / (1 + len(team_pl)) if team_pl else float("nan"),
            overlapping=overlapping, placebo_effects=team_pl + time_pl,
            time_placebo_sd_pct=sd_time, noise_ratio=ratio, lead_test=lead,
            lead_p=pval(time_pl) if lead == "time" else pval(team_pl),
            n_team_placebos=len(team_pl), n_time_placebos=len(time_pl),
        ))
    return out
