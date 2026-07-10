from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

import docker

from sforge.author.config import AuthorConfig
from sforge.author.errors import CalibrationError
from sforge.harness.benchmark import load_benchmark
from sforge.harness.config import SForgeConfig, create_backend_from_config
from sforge.harness.docker_build import build_all_images
from sforge.harness.run_evaluation import judge_submission
from sforge.harness.task_spec import make_task_spec


@dataclass
class CalibrationReport:
    gutted_score: float
    golden_score: float
    gutted_runtime: float
    golden_runtime: float
    gutted_log_dir: Path
    golden_log_dir: Path
    golden_total_tests: int = 0


def pack_submission(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel_path, content in files.items():
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _extract_score(report) -> float:
    score = getattr(report, "score_0_100", None)
    if score is None:
        score = getattr(report, "score", None)
    if score is None:
        return float("nan")
    return float(score)


def calibrate(
    config: AuthorConfig,
    manifest_path: Path,
    gutted_files: dict[str, bytes],
    golden_files: dict[str, bytes],
) -> CalibrationReport:
    log_root = Path("logs/author") / config.task_id
    log_root.mkdir(parents=True, exist_ok=True)

    tasks_dir = manifest_path.parent
    sforge_config = SForgeConfig(
        log_dir=log_root,
        tasks_dir=tasks_dir,
        backend="docker",
    )

    benchmark = load_benchmark(tasks_dir)
    task_spec = make_task_spec(manifest_path, benchmark)

    try:
        docker_client = docker.from_env()
    except Exception as exc:
        raise CalibrationError(
            f"calibration requires Docker; failed to initialise client: {exc}"
        ) from exc

    backend = create_backend_from_config(sforge_config, docker_client=docker_client)

    build_all_images(
        task_spec,
        sforge_config,
        docker_client,
        force_rebuild=False,
        force_rebuild_base=False,
        verbose=True,
    )

    gutted_log_dir = log_root / "calibrate-gutted"
    gutted_log_dir.mkdir(parents=True, exist_ok=True)
    gutted_archive = pack_submission(gutted_files)
    t0 = time.time()
    gutted_report = judge_submission(
        task_spec,
        gutted_archive,
        sforge_config,
        backend,
        submission_id="calibrate-gutted",
        log_dir=gutted_log_dir,
        verbose=True,
    )
    gutted_runtime = getattr(gutted_report, "runtime_seconds", None) or (time.time() - t0)
    gutted_score = _extract_score(gutted_report)

    if not (gutted_score <= config.gutted_max):
        raise CalibrationError(
            f"calibration failed: gutted score {gutted_score:.2f} > gutted_max {config.gutted_max}. "
            f"Logs: {gutted_log_dir}"
        )

    golden_log_dir = log_root / "calibrate-golden"
    golden_log_dir.mkdir(parents=True, exist_ok=True)
    golden_archive = pack_submission(golden_files)
    t0 = time.time()
    golden_report = judge_submission(
        task_spec,
        golden_archive,
        sforge_config,
        backend,
        submission_id="calibrate-golden",
        log_dir=golden_log_dir,
        verbose=True,
    )
    golden_runtime = getattr(golden_report, "runtime_seconds", None) or (time.time() - t0)
    golden_score = _extract_score(golden_report)

    if not (golden_score >= config.golden_min):
        raise CalibrationError(
            f"calibration failed: golden score {golden_score:.2f} < golden_min {config.golden_min}. "
            f"Logs: {golden_log_dir}"
        )

    return CalibrationReport(
        gutted_score=gutted_score,
        golden_score=golden_score,
        gutted_runtime=float(gutted_runtime),
        golden_runtime=float(golden_runtime),
        gutted_log_dir=gutted_log_dir,
        golden_log_dir=golden_log_dir,
        golden_total_tests=int(getattr(golden_report, "total_tests", 0) or 0),
    )
