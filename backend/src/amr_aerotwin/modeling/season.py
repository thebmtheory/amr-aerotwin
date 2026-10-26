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
from scipy import stats


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
    car_share: float
    car_share_ci90: tuple[float, float]
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
    """Share of qualifying-gap variance between teams (car) vs within teams (driver + execution).

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
    return VarianceSplit(
        car_share=share(arr),
        car_share_ci90=(float(np.percentile(boots, 5)), float(np.percentile(boots, 95))),
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
    effect_mean_pct: float  # step at the MAP changepoint (negative = got faster)
    effect_ci90_pct: tuple[float, float]


def bayesian_changepoint(
    y: np.ndarray,
    covariate: np.ndarray | None = None,
    events: list[str] | None = None,
    rounds: np.ndarray | None = None,
    min_segment: int = 3,
    prior_no_change: float = 0.5,
) -> ChangepointResult:
    """Single mean-shift changepoint with exact model evidence for every location.

    Models: M0 y = a + b x + e;  M_tau y = a + b x + d 1[i >= tau] + e. Prior mass
    `prior_no_change` on M0, the rest uniform over admissible tau.
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
    lml0 = log_marginal_likelihood(x0, z)
    lmls = []
    for t in taus:
        step = (np.arange(n) >= t).astype(float)
        lmls.append(log_marginal_likelihood(np.column_stack([x0, step]), z))
    lmls_a = np.array(lmls)
    log_prior_tau = np.log((1 - prior_no_change) / max(len(taus), 1))
    logw = np.concatenate([[np.log(prior_no_change) + lml0], log_prior_tau + lmls_a])
    w = np.exp(logw - logw.max())
    w /= w.sum()
    post = np.zeros(n)
    post[taus] = w[1:]
    map_i = int(taus[int(np.argmax(w[1:]))]) if taus else None

    eff, ci = float("nan"), (float("nan"), float("nan"))
    if map_i is not None:
        step = (np.arange(n) >= map_i).astype(float)
        x = np.column_stack([x0, step])
        p = x.shape[1]
        vn = np.linalg.inv(np.eye(p) / 10.0 + x.T @ x)
        bn = vn @ x.T @ z
        an = 1.0 + n / 2.0
        bnn = 1.0 + 0.5 * float(z @ z - bn @ np.linalg.inv(vn) @ bn)
        scale = np.sqrt(bnn / an * vn[-1, -1])
        t90 = stats.t.ppf(0.95, 2 * an)
        eff = float(bn[-1] * sd)
        ci = (float((bn[-1] - t90 * scale) * sd), float((bn[-1] + t90 * scale) * sd))
    return ChangepointResult(
        rounds=np.arange(n) if rounds is None else np.asarray(rounds),
        events=events or [str(i) for i in range(n)],
        posterior_tau=post,
        p_no_change=float(w[0]),
        map_index=map_i,
        effect_mean_pct=eff,
        effect_ci90_pct=ci,
    )


# --------------------------------------------------------------------------- upgrades (DiD)
@dataclass(frozen=True)
class UpgradeEffect:
    season: int
    event: str
    effect_pct: float  # change in gap to pole after the upgrade vs rivals (negative = gained)
    team_placebo_p: float  # share of rival teams with |placebo| >= |effect|
    time_placebo_p: float  # share of non-upgrade dates with |placebo| >= |effect|
    n_pre: int
    n_post: int
    placebo_effects: list[float]


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
    d["treated"] = ((d["team"] == treated_team) & d["round"].isin(post)).astype(float)
    cols = [pd.get_dummies(d["team"], dtype=float), pd.get_dummies(d["round"], prefix="r", dtype=float).iloc[:, 1:]]
    if "track_x" in d:
        xc = d["track_x"] - d["track_x"].mean()
        slopes = pd.get_dummies(d["team"], dtype=float).mul(xc, axis=0).add_prefix("x_").iloc[:, 1:]
        cols.append(slopes)
    x = pd.concat(cols + [d[["treated"]]], axis=1).to_numpy(float)
    beta = np.linalg.lstsq(x, d["gap_pct"].to_numpy(float), rcond=None)[0]
    return float(beta[-1]), len(pre), len(post)


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

        def pval(pl: list[float]) -> float:
            return float(np.mean(np.abs(pl) >= abs(eff))) if pl else float("nan")

        out.append(UpgradeEffect(
            season=int(up["season"]), event=str(up["event"]), effect_pct=eff,
            team_placebo_p=pval(team_pl), time_placebo_p=pval(time_pl),
            n_pre=n_pre, n_post=n_post, placebo_effects=team_pl + time_pl,
        ))
    return out
