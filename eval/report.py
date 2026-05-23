#!/usr/bin/env python3
"""Pretty-print evaluation or benchmark reports produced by music-manager.

Usage:
    uv run python eval/report.py eval/benchmark.json          # benchmark report
    uv run python eval/report.py eval/report.json             # evaluate report
    uv run python eval/report.py eval/benchmark.json --raw    # include per-track detail
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box


def _pct_color(pct: float | None) -> str:
    if pct is None:
        return "dim"
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "yellow"
    return "red"


def _score_color(score: float) -> str:
    if score >= 8:
        return "green"
    if score >= 5:
        return "yellow"
    return "red"


def print_report(report: dict, show_raw: bool = False, console: Console | None = None) -> None:
    con = console or Console()

    # ── Summary ──────────────────────────────────────────────────────────────
    s = report.get("summary", {})
    con.rule("[bold]Evaluation Summary[/bold]")
    con.print(f"  Total files evaluated:     [bold]{s.get('total_files', 0)}[/bold]")
    pct = s.get("identified_by_current_pct", 0)
    con.print(f"  Identified (current):      [bold {_pct_color(pct)}]{s.get('identified_by_current', 0)}[/bold {_pct_color(pct)}]  ({pct}%)")
    if s.get("identified_by_shazam") is not None:
        con.print(f"  Identified (Shazam):       [bold]{s.get('identified_by_shazam', 0)}[/bold]")
    if s.get("known_albums_provided"):
        matched = s.get("records_matched_to_known", 0)
        total_known = s.get("known_albums_provided", 0)
        total_rec = s.get("total_records", 0)
        con.print(f"  Records matched to known:  [bold]{matched}/{total_rec}[/bold]  ({total_known} albums in ground truth)")
    if s.get("cross_source_agreement_pct") is not None:
        pct2 = s["cross_source_agreement_pct"]
        con.print(f"  Current↔Shazam agreement:  [bold {_pct_color(pct2)}]{pct2}%[/bold {_pct_color(pct2)}]  (album-level)")

    # ── AcoustID Score Distribution ───────────────────────────────────────────
    adist = report.get("acoustid_score_distribution", {})
    if adist:
        con.print()
        con.rule("[bold]AcoustID Score Distribution[/bold]")
        con.print(
            f"  n={adist['count']}  min={adist['min']:.2f}  "
            f"p25={adist['p25']:.2f}  median={adist['median']:.2f}  "
            f"p75={adist['p75']:.2f}  max={adist['max']:.2f}"
        )
        low = adist.get("below_0_5", 0)
        if low > 0:
            con.print(f"  [yellow]⚠  {low} track(s) below 0.5 confidence — potential mis-ID[/yellow]")

    # ── Field Coverage ────────────────────────────────────────────────────────
    coverage = report.get("field_coverage", {})
    if coverage:
        con.print()
        con.rule("[bold]Field Coverage (%)[/bold]")
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
        tbl.add_column("Field", style="bold")
        sources = [(k, v) for k, v in coverage.items() if v]
        for src, _ in sources:
            tbl.add_column(src.replace("_", " ").title())
        fields = ["title", "artist", "album", "album_artist", "year", "track_number", "genre", "has_cover_art"]
        for f in fields:
            row = [f]
            for _, cov_data in sources:
                val = cov_data.get(f)
                if val is None:
                    row.append("[dim]—[/dim]")
                else:
                    color = _pct_color(val)
                    row.append(f"[{color}]{val}%[/{color}]")
            tbl.add_row(*row)
        con.print(tbl)

    # ── Per-Record Summary ────────────────────────────────────────────────────
    per_record = report.get("per_record", [])
    if per_record:
        con.print()
        con.rule("[bold]Per-Record Summary[/bold]")
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
        tbl.add_column("Rec", style="bold")
        tbl.add_column("Trks", justify="right")
        tbl.add_column("Identified As")
        tbl.add_column("Best Known Match")
        tbl.add_column("Sim", justify="right")
        tbl.add_column("Acc", justify="right")
        tbl.add_column("Ok", justify="center")
        tbl.add_column("#s", justify="center")
        tbl.add_column("Art", justify="center")
        tbl.add_column("iPod", justify="right")

        for pr in per_record:
            consensus = pr.get("consensus_album") or "[dim]none[/dim]"
            known = pr.get("best_known_match") or {}
            known_str = f"{known.get('artist', '')} — {known.get('album', '')}" if known else "[dim]no match[/dim]"
            sim = known.get("_similarity")
            sim_str = f"[{_pct_color((sim or 0) * 100)}]{sim:.2f}[/{_pct_color((sim or 0) * 100)}]" if sim else "[dim]—[/dim]"

            acc = pr.get("album_accuracy_pct")
            acc_str = f"[{_pct_color(acc)}]{acc}%[/{_pct_color(acc)}]" if acc is not None else "[dim]—[/dim]"

            consistent = "✓" if pr.get("album_consistent") else "[yellow]✗[/yellow]"
            nums_ok = "[dim]—[/dim]" if not pr.get("track_numbers_found") else ("✓" if not pr.get("track_number_gaps") else "[yellow]gap[/yellow]")
            art = f"{pr.get('cover_art_pct', 0):.0f}%"
            score = pr.get("ipod_score_avg", 0)
            score_str = f"[{_score_color(score)}]{score:.1f}[/{_score_color(score)}]"

            tbl.add_row(
                pr["record_index"],
                str(pr["track_count"]),
                consensus,
                known_str,
                sim_str,
                acc_str,
                consistent,
                nums_ok,
                art,
                score_str,
            )
        con.print(tbl)

    # ── Failure Modes ─────────────────────────────────────────────────────────
    failures = report.get("failure_modes", [])
    if failures:
        con.print()
        con.rule("[bold]Failure Cases[/bold]  (sorted by iPod score, worst first)")
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
        tbl.add_column("File")
        tbl.add_column("Issues", style="yellow")
        tbl.add_column("Current Album")
        tbl.add_column("Shazam Album")
        tbl.add_column("AcoustID", justify="right")
        tbl.add_column("iPod", justify="right")
        for f in failures[:20]:
            tbl.add_row(
                f.get("file", ""),
                ", ".join(f.get("issues", [])),
                f.get("current_album") or "[dim]—[/dim]",
                f.get("shazam_album") or "[dim]—[/dim]",
                f"{f.get('acoustid_score', 0):.2f}",
                f"[{_score_color(f.get('ipod_score', 0))}]{f.get('ipod_score', 0):.0f}/10[/{_score_color(f.get('ipod_score', 0))}]",
            )
        if len(failures) > 20:
            con.print(f"  … and {len(failures) - 20} more in the JSON report")
        con.print(tbl)

    # ── Recommendations ───────────────────────────────────────────────────────
    recs = report.get("recommendations", [])
    if recs:
        con.print()
        con.rule("[bold]Recommendations[/bold]")
        for r in recs:
            con.print(f"  [yellow]→[/yellow] {r}")

    # ── Raw per-file results ──────────────────────────────────────────────────
    if show_raw:
        raw = report.get("raw_results", [])
        if raw:
            con.print()
            con.rule("[bold]Per-File Detail[/bold]")
            for item in raw:
                cp = item.get("current_pipeline", {})
                con.print(
                    f"  [bold]{item['filename']}[/bold]  rec={item['record_index']}"
                    f"  score={cp.get('acoustid_score', 0):.2f}"
                    f"  title={cp.get('title', '—')!r}"
                    f"  album={cp.get('album', '—')!r}"
                    f"  album_artist={cp.get('album_artist', '—')!r}"
                )


def _sim_color(sim: float) -> str:
    if sim >= 0.85:
        return "green"
    if sim >= 0.6:
        return "yellow"
    return "red"


def print_benchmark_report(report: dict, show_raw: bool = False, console: Console | None = None) -> None:
    con = console or Console()
    s = report.get("summary", {})

    con.rule("[bold]Benchmark Summary — Ground-Truth Accuracy[/bold]")
    total = s.get("total_tracks", 0)
    perfect = s.get("perfect_match_pct", 0)
    con.print(f"  Tracks evaluated:   [bold]{total}[/bold]")
    con.print(
        f"  Perfect match:      "
        f"[bold {_pct_color(perfect)}]{s.get('perfect_match_count', 0)} / {total}[/bold {_pct_color(perfect)}]"
        f"  ({perfect}%)  [dim]title + artist + album all ≥ 0.85[/dim]"
    )
    con.print()

    # Field accuracy table
    tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
    tbl.add_column("Field", style="bold")
    tbl.add_column("Match %", justify="right")
    for field_key, label in [
        ("title_match_pct", "Title"),
        ("artist_match_pct", "Artist"),
        ("album_match_pct", "Album"),
        ("album_artist_match_pct", "Album Artist"),
        ("year_match_pct", "Year"),
    ]:
        val = s.get(field_key, 0)
        tbl.add_row(label, f"[{_pct_color(val)}]{val}%[/{_pct_color(val)}]")
    con.print(tbl)

    # Source breakdown
    by_source = s.get("by_source", {})
    if by_source and total:
        con.print("  Source breakdown:")
        for src, count in sorted(by_source.items()):
            pct = round(count / total * 100, 1)
            color = "green" if src == "acoustid" else ("yellow" if src == "shazam" else "red")
            con.print(f"    [{color}]{src}[/{color}]  {count} tracks  ({pct}%)")
    con.print()

    # Per-album table
    per_album = report.get("per_album", [])
    if per_album:
        con.rule("[bold]Per-Album Breakdown[/bold]")
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
        tbl.add_column("Album", style="bold", no_wrap=False)
        tbl.add_column("Trks", justify="right")
        tbl.add_column("Perfect", justify="right")
        tbl.add_column("Title", justify="right")
        tbl.add_column("Artist", justify="right")
        tbl.add_column("Album", justify="right")
        tbl.add_column("Sources")
        for alb in per_album:
            perfect_pct = alb["perfect_match_pct"]
            src_str = "  ".join(
                f"[{'green' if k == 'acoustid' else 'yellow' if k == 'shazam' else 'red'}]{k}:{v}[/]"
                for k, v in alb["sources"].items()
            )
            tbl.add_row(
                alb["album_dir"],
                str(alb["track_count"]),
                f"[{_pct_color(perfect_pct)}]{perfect_pct}%[/{_pct_color(perfect_pct)}]",
                f"[{_pct_color(alb['title_match_pct'])}]{alb['title_match_pct']}%[/{_pct_color(alb['title_match_pct'])}]",
                f"[{_pct_color(alb['artist_match_pct'])}]{alb['artist_match_pct']}%[/{_pct_color(alb['artist_match_pct'])}]",
                f"[{_pct_color(alb['album_match_pct'])}]{alb['album_match_pct']}%[/{_pct_color(alb['album_match_pct'])}]",
                src_str,
            )
        con.print(tbl)

    # Failures
    failures = report.get("failures", [])
    if failures:
        con.print()
        con.rule(f"[bold]Failures[/bold]  ({len(failures)} tracks — sorted worst first)")
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
        tbl.add_column("Track", no_wrap=False)
        tbl.add_column("Field")
        tbl.add_column("Ground Truth")
        tbl.add_column("Identified")
        tbl.add_column("Sim", justify="right")
        tbl.add_column("Src")
        for f in failures[:30]:
            gt = f.get("ground_truth", {})
            idf = f.get("identified", {})
            sims = f.get("similarity", {})
            match = f.get("match", {})
            track_label = Path(f["path"]).name

            rows_added = 0
            for fld, gt_key, id_key, sim_key in [
                ("title", "title", "title", "title"),
                ("artist", "artist", "artist", "artist"),
                ("album", "album", "album", "album"),
            ]:
                if not match.get(fld):
                    sim_val = sims.get(sim_key, 0)
                    tbl.add_row(
                        track_label if rows_added == 0 else "",
                        fld,
                        gt.get(gt_key, "") or "[dim]—[/dim]",
                        idf.get(id_key, "") or "[dim]—[/dim]",
                        f"[{_sim_color(sim_val)}]{sim_val:.2f}[/{_sim_color(sim_val)}]",
                        f.get("source", ""),
                    )
                    rows_added += 1
        if len(failures) > 30:
            con.print(f"  … {len(failures) - 30} more in the JSON report")
        con.print(tbl)

    if show_raw:
        all_results = report.get("all_results", [])
        if all_results:
            con.print()
            con.rule("[bold]All Results[/bold]")
            tbl = Table(box=box.SIMPLE_HEAD, show_header=True)
            tbl.add_column("Track")
            tbl.add_column("T", justify="center")
            tbl.add_column("Ar", justify="center")
            tbl.add_column("Al", justify="center")
            tbl.add_column("T-sim", justify="right")
            tbl.add_column("Ar-sim", justify="right")
            tbl.add_column("Al-sim", justify="right")
            tbl.add_column("Src")
            for r in all_results:
                m = r.get("match", {})
                sims = r.get("similarity", {})
                tbl.add_row(
                    Path(r["path"]).name,
                    "[green]✓[/green]" if m.get("title") else "[red]✗[/red]",
                    "[green]✓[/green]" if m.get("artist") else "[red]✗[/red]",
                    "[green]✓[/green]" if m.get("album") else "[red]✗[/red]",
                    f"{sims.get('title', 0):.2f}",
                    f"{sims.get('artist', 0):.2f}",
                    f"{sims.get('album', 0):.2f}",
                    r.get("source", ""),
                )
            con.print(tbl)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pretty-print a music-manager evaluation or benchmark report.")
    parser.add_argument("report", type=Path, help="Path to JSON report file.")
    parser.add_argument("--raw", action="store_true", help="Show per-file detail.")
    args = parser.parse_args()

    if not args.report.exists():
        print(f"Error: {args.report} not found.", file=sys.stderr)
        sys.exit(1)

    with args.report.open(encoding="utf-8") as fh:
        report_data = json.load(fh)

    # Detect report type by presence of "perfect_match_pct" in summary
    if "perfect_match_pct" in report_data.get("summary", {}):
        print_benchmark_report(report_data, show_raw=args.raw)
    else:
        print_report(report_data, show_raw=args.raw)
