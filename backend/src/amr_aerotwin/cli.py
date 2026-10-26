"""Command line entry point: `aerotwin fetch | build | analyse | report | all | event-report`."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from amr_aerotwin.data.repository import DEFAULT_CACHE_DIR
from amr_aerotwin.pipeline.season import PROCESSED_DIR, analyse, build, fetch


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aerotwin", description=__doc__)
    parser.add_argument("command", choices=["fetch", "build", "analyse", "report", "all", "event-report"])
    parser.add_argument("--event", default="British Grand Prix", help="Grand Prix name for event-report")
    parser.add_argument("--reports", type=Path, default=PROCESSED_DIR.parents[1] / "reports")
    parser.add_argument("--years", type=int, nargs="+", default=[2025, 2026])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--site", type=Path, default=PROCESSED_DIR.parents[1] / "site")
    parser.add_argument("--processes", type=int, default=None)
    parser.add_argument("--no-mcmc", action="store_true", help="skip the Metropolis check (faster)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    t0 = time.time()
    if args.command in ("fetch", "all"):
        fetch(args.years, args.cache)
    if args.command in ("build", "all"):
        build(args.years, args.cache, args.out, args.processes, run_mcmc=not args.no_mcmc)
    if args.command in ("analyse", "all"):
        analyse(args.out)
    if args.command in ("report", "all", "event-report"):
        from amr_aerotwin.report.event_report import build_event_report, report_events

        # `event-report` builds the named event; `report` refreshes every event report that exists
        for ev in [args.event] if args.command == "event-report" else report_events(args.reports, args.out):
            logging.info("wrote %s", build_event_report(ev, args.reports, args.out))
    if args.command in ("report", "all"):
        from amr_aerotwin.report.build import build_site
        from amr_aerotwin.report.note import build_note, update_readme

        build_site(args.out, args.site, args.reports)
        build_note(args.out / "season.json", args.site.parent / "docs" / "technical_note.md")
        update_readme(args.out / "season.json", args.site.parent / "README.md")
    logging.info("done in %.0f s", time.time() - t0)


if __name__ == "__main__":
    main()
