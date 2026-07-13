from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sforge.author import benchmark_yaml, calibrate as calibrate_mod, commit_info, workspace
from sforge.author.config import AuthorConfig
from sforge.author.errors import AuthorError, GutError, ManifestError
from sforge.author.gutters import get_gutter
from sforge.author.gutters.base import GutSpec
from sforge.author.manifest import build_manifest
from sforge.author.tier import classify_tier, enforce_tier
from sforge.harness.config import load_config


def _resolve_tasks_dir(args: argparse.Namespace) -> Path:
    override = getattr(args, "tasks_dir", None)
    sforge_config = load_config({"tasks_dir": override} if override else None)
    return sforge_config.tasks_dir


def cmd_author_clone_gut(args: argparse.Namespace) -> int:
    try:
        return _run(args)
    except AuthorError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return exc.exit_code


def _run(args: argparse.Namespace) -> int:
    config = AuthorConfig.from_namespace(args)

    tasks_dir = _resolve_tasks_dir(args)
    bench_path = tasks_dir / "BENCHMARK.yaml"
    if not bench_path.exists():
        raise ManifestError(
            f"BENCHMARK.yaml not found at {bench_path}; set --tasks-dir or SFORGE_TASKS_DIR"
        )
    status = benchmark_yaml.ensure_base(bench_path, config.base)
    if status == "missing":
        raise ManifestError(
            f"base {config.base!r} not present in {bench_path}; add it there before authoring"
        )

    gutter = get_gutter(config.lang)

    with workspace.temp_workspace() as tmpdir:
        checkout = workspace.clone(config.repo, config.commit, tmpdir)

        commit_date = commit_info.get_commit_date(checkout, config.commit)
        commit_info.check_contamination(
            commit_date, config.model_cutoff, config.allow_precutoff
        )
        if config.allow_precutoff and commit_date < config.model_cutoff:
            print(
                f"Warning: commit {commit_date.isoformat()} predates cutoff "
                f"{config.model_cutoff.isoformat()} (allowed via --allow-precutoff)",
                file=sys.stderr,
            )

        originals: dict[str, bytes] = {}
        gutted_files: dict[str, bytes] = {}
        gut_results = []
        for target in config.gut_targets:
            src_path = checkout / target.rel_path
            if not src_path.exists():
                raise GutError(
                    f"gut target not found: {target.rel_path} in {config.repo}@{config.commit}"
                )
            original_bytes = src_path.read_bytes()
            originals[target.rel_path] = original_bytes
            source_text = original_bytes.decode("utf-8", errors="replace")
            if target.wipe:
                result = gutter.wipe_file(source_text)
            else:
                result = gutter.gut(source_text, GutSpec(target.rel_path, target.funcs))
            gut_results.append(result)
            gutted_files[target.rel_path] = result.gutted_source.encode("utf-8")

        total_loc = sum(r.total_loc_gutted for r in gut_results)
        preliminary_tier = classify_tier(total_loc, 0)

        manifest = build_manifest(config, gut_results)

        if config.dry_run:
            if config.tier != "auto" and config.tier != preliminary_tier:
                print(
                    f"Warning: --tier {config.tier} cannot be enforced during dry-run "
                    f"(test count unavailable). Preliminary tier: {preliminary_tier}",
                    file=sys.stderr,
                )
            print(json.dumps(manifest, indent=2))
            return 0

        config.out_dir.mkdir(parents=True, exist_ok=True)
        out_path = config.out_dir / f"{config.task_id}.json"
        if out_path.exists() and not config.force:
            raise ManifestError(
                f"manifest already exists: {out_path} (use --force to overwrite)"
            )
        pending_path = out_path.with_suffix(".json.pending")
        pending_path.write_text(json.dumps(manifest, indent=2))

        if config.no_calibrate:
            os.replace(pending_path, out_path)
            print(f"Manifest written: {out_path}")
            print(
                f"Tier (preliminary, no tests counted): {preliminary_tier}  "
                f"loc_gutted={total_loc}"
            )
            if config.tier != "auto" and config.tier != preliminary_tier:
                print(
                    f"Warning: --tier {config.tier} cannot be enforced with --no-calibrate "
                    f"(test count unavailable).",
                    file=sys.stderr,
                )
            print("Skipped calibration (--no-calibrate)")
            return 0

        try:
            report = calibrate_mod.calibrate(
                config, pending_path, gutted_files, originals
            )
            test_count = report.golden_total_tests
            observed_tier = classify_tier(total_loc, test_count)
            if config.tier != "auto":
                enforce_tier(config.tier, observed_tier)
            if test_count < config.min_tests:
                raise ManifestError(
                    f"golden test count {test_count} < --min-tests {config.min_tests}"
                )
        except BaseException:
            if pending_path.exists():
                pending_path.unlink()
            raise
        os.replace(pending_path, out_path)

        print(f"Manifest written: {out_path}")
        print(
            f"Tier: {observed_tier}  loc_gutted={total_loc}  tests={test_count}"
        )
        print(
            f"Calibration: gutted={report.gutted_score:.2f} "
            f"(<= {config.gutted_max}) in {report.gutted_runtime:.1f}s; "
            f"golden={report.golden_score:.2f} "
            f"(>= {config.golden_min}) in {report.golden_runtime:.1f}s"
        )

    return 0



