"""工作区清理：临时文件、成功后的源文件等。

与解密流水线解耦，可被自动模式单独调用，也可作为「仅清理」入口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CleanupReport:
    """一次清理操作的统计。"""

    temp_removed: int = 0
    sources_removed: int = 0
    progress_reset: bool = False
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"temp={self.temp_removed}",
            f"sources={self.sources_removed}",
        ]
        if self.progress_reset:
            parts.append("progress_reset=yes")
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return ", ".join(parts)


def cleanup_temp_files(directory: Path | str) -> int:
    """清理目录中解密遗留的 temp_*.bin，返回删除数量。"""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    removed = 0
    for p in directory.glob("temp_*.bin"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def remove_source_file(path: Path | str) -> bool:
    """删除已成功解密的源加密文件。成功返回 True。"""
    path = Path(path)
    try:
        path.unlink(missing_ok=True)
        return not path.exists()
    except OSError:
        return False


def cleanup_workspace(
    output_dir: Path | str = "output",
    music_files_dir: Path | str | None = None,
    *,
    remove_sources: bool = False,
    source_names: set[str] | None = None,
    progress_path: Path | str | None = None,
    reset_progress: bool = False,
) -> CleanupReport:
    """统一工作区清理入口。

    参数：
      output_dir: 输出目录（清理 temp_*.bin）
      music_files_dir: 可选，input/music_files
      remove_sources: 是否按 source_names 删除源文件
      source_names: 要删除的源文件名集合（相对 music_files_dir）
      progress_path: 进度 JSON 路径
      reset_progress: 是否删除进度文件（重新跑批）
    """
    report = CleanupReport()
    output_dir = Path(output_dir)

    try:
        report.temp_removed = cleanup_temp_files(output_dir)
    except OSError as e:
        report.errors.append(f"temp cleanup: {e}")

    if remove_sources and music_files_dir is not None and source_names:
        base = Path(music_files_dir)
        for name in source_names:
            src = base / name
            if not src.is_file():
                continue
            if remove_source_file(src):
                report.sources_removed += 1
            else:
                report.errors.append(f"failed to remove source: {name}")

    if reset_progress and progress_path is not None:
        p = Path(progress_path)
        try:
            if p.exists():
                p.unlink()
                report.progress_reset = True
        except OSError as e:
            report.errors.append(f"progress reset: {e}")

    return report
