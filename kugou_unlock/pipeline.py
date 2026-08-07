"""多线程解密流水线：任务提交 → 并发执行 → 进度落盘 → 可选清理源文件。"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio import collect_processable_files, pass_through_plain_audio
from .cleanup import cleanup_temp_files, cleanup_workspace, remove_source_file
from .kgg import decrypt_kgg_file, read_audio_hash_from_kgg
from .kgm import decrypt_kgm_family_file
from .progress import ProgressStore


@dataclass(frozen=True)
class Job:
    path: Path
    kind: str  # kgg | kgm | plain


@dataclass
class JobResult:
    path: Path
    kind: str
    ok: bool
    skipped: bool = False
    output_name: str | None = None
    error: str | None = None
    message: str = ""


def default_worker_count() -> int:
    """默认线程数：CPU 核数，夹在 2～8 之间，适合磁盘流式解密。"""
    n = os.cpu_count() or 4
    return max(2, min(8, n))


def _build_jobs(music_files_dir: Path) -> list[Job]:
    kgg_files, kgm_files, plain_files = collect_processable_files(music_files_dir)
    jobs = [Job(path=p, kind="kgg") for p in kgg_files]
    jobs.extend(Job(path=p, kind="kgm") for p in kgm_files)
    jobs.extend(Job(path=p, kind="plain") for p in plain_files)
    return jobs


def _process_job(
    job: Job,
    *,
    output_dir: Path,
    key_mapping: dict[str, str],
    progress: ProgressStore,
    remove_source: bool,
    log_lock: threading.Lock,
    log: Callable[[str], None],
) -> JobResult:
    path, kind = job.path, job.kind

    skip, reason = progress.should_skip(path, kind)
    if skip:
        progress.mark(path, kind=kind, status="success")  # 刷新时间戳
        with log_lock:
            log(f"[*] Skip {path.name}: {reason}")
        return JobResult(path=path, kind=kind, ok=True, skipped=True, message=reason)

    try:
        if kind == "kgg":
            audio_hash = read_audio_hash_from_kgg(path)
            if not audio_hash:
                raise ValueError("failed to read audio hash")
            ekey_str = key_mapping.get(audio_hash)
            if not ekey_str:
                raise ValueError(f"EKey not found for hash {audio_hash}")
            out_path = decrypt_kgg_file(path, output_dir, ekey_str, quiet=True)
            out_name = Path(out_path).name if out_path else None
        elif kind == "kgm":
            out_name = decrypt_kgm_family_file(path, output_dir)
        elif kind == "plain":
            out_name = pass_through_plain_audio(path, output_dir)
        else:
            raise ValueError(f"Unknown job kind: {kind}")

        progress.mark(path, kind=kind, status="success", output=out_name, error=None)

        action = "Copied" if kind == "plain" else "Decrypted"
        if remove_source:
            if remove_source_file(path):
                with log_lock:
                    log(f"    [+] {action}: {path.name} -> output/{out_name}")
                    log(f"    [-] Removed source: {path.name}")
            else:
                with log_lock:
                    log(f"    [+] {action}: {path.name} -> output/{out_name}")
                    log(f"    [!] Could not remove source: {path.name}")
        else:
            with log_lock:
                log(f"    [+] {action}: {path.name} -> output/{out_name}")

        return JobResult(path=path, kind=kind, ok=True, output_name=out_name)

    except Exception as e:
        err = str(e)
        progress.mark(path, kind=kind, status="failed", error=err)
        with log_lock:
            verb = "copying" if kind == "plain" else "decrypting"
            log(f"    [!] Error {verb} {path.name}: {err}")
        return JobResult(path=path, kind=kind, ok=False, error=err)


def run_pipeline(
    music_files_dir: Path | str,
    output_dir: Path | str,
    key_mapping: dict[str, str] | None = None,
    *,
    workers: int | None = None,
    progress_path: Path | str | None = None,
    remove_source: bool = True,
    clean_temps: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[int, int, int, int]:
    """并发解密流水线。

    返回 (total, success, failed, skipped)。
    """
    music_files_dir = Path(music_files_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    key_mapping = key_mapping or {}
    workers = workers if workers and workers > 0 else default_worker_count()
    log = log or print

    if progress_path is None:
        progress_path = Path("tools") / "progress.json"
    progress = ProgressStore(progress_path, output_dir=output_dir)

    if clean_temps:
        n = cleanup_temp_files(output_dir)
        if n:
            log(f"[*] Cleaned {n} leftover temp file(s) from output/")

    jobs = _build_jobs(music_files_dir)
    total = len(jobs)
    if total == 0:
        log("[*] No processable audio files found.")
        return 0, 0, 0, 0

    n_kgg = sum(1 for j in jobs if j.kind == "kgg")
    n_kgm = sum(1 for j in jobs if j.kind == "kgm")
    n_plain = sum(1 for j in jobs if j.kind == "plain")
    log(
        f"[*] Found {total} file(s) "
        f"(kgg={n_kgg}, kgm={n_kgm}, plain={n_plain}). "
        f"Workers={workers}, progress={progress.path_str()}"
    )
    if n_kgg and not key_mapping:
        log("[!] Warning: No key mapping loaded. .kgg files may fail to decrypt.")

    log_lock = threading.Lock()
    success = failed = skipped = 0
    done = 0

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kgg-unlock") as pool:
        futures = [
            pool.submit(
                _process_job,
                job,
                output_dir=output_dir,
                key_mapping=key_mapping,
                progress=progress,
                remove_source=remove_source,
                log_lock=log_lock,
                log=log,
            )
            for job in jobs
        ]
        for fut in as_completed(futures):
            result = fut.result()
            done += 1
            if result.skipped:
                skipped += 1
            elif result.ok:
                success += 1
            else:
                failed += 1
            with log_lock:
                log(f"[*] Progress {done}/{total} (ok={success} skip={skipped} fail={failed})")

    # 收尾清理临时文件
    cleanup_workspace(output_dir=output_dir)
    log(f"[*] Progress saved to {progress.path_str()}")
    return total, success, failed, skipped
