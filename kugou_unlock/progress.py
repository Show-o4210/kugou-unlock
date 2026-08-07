"""解密进度断点：写入 JSON，支持中断后跳过已成功项。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROGRESS_VERSION = 1


def _file_fingerprint(path: Path) -> dict[str, Any]:
    """用 size + mtime 标识文件内容版本，避免同名替换后误跳过。"""
    try:
        st = path.stat()
        return {"size": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return {"size": 0, "mtime": 0.0}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


@dataclass
class FileRecord:
    status: str  # pending | success | failed | skipped
    kind: str  # kgg | kgm | plain
    src_name: str
    size: int = 0
    mtime: float = 0.0
    output: str | None = None
    error: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "kind": self.kind,
            "src_name": self.src_name,
            "size": self.size,
            "mtime": self.mtime,
            "output": self.output,
            "error": self.error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileRecord:
        return cls(
            status=str(data.get("status", "pending")),
            kind=str(data.get("kind", "")),
            src_name=str(data.get("src_name", "")),
            size=int(data.get("size") or 0),
            mtime=float(data.get("mtime") or 0.0),
            output=data.get("output"),
            error=data.get("error"),
            updated_at=data.get("updated_at"),
        )


class ProgressStore:
    """线程安全的进度 JSON 存储。

    默认路径 tools/progress.json。每次 mark 后原子写入磁盘，
    崩溃重启后可跳过 status=success 且指纹未变、输出仍在的文件。
    """

    def __init__(self, path: Path | str, output_dir: Path | str | None = None):
        self.path = Path(path)
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "version": PROGRESS_VERSION,
            "updated_at": None,
            "files": {},
            "stats": {"success": 0, "failed": 0, "skipped": 0, "pending": 0},
        }
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        files = raw.get("files") or {}
        if not isinstance(files, dict):
            files = {}
        self._data = {
            "version": int(raw.get("version") or PROGRESS_VERSION),
            "updated_at": raw.get("updated_at"),
            "files": files,
            "stats": raw.get("stats")
            or {"success": 0, "failed": 0, "skipped": 0, "pending": 0},
        }

    def _recompute_stats(self) -> None:
        stats = {"success": 0, "failed": 0, "skipped": 0, "pending": 0}
        for rec in self._data["files"].values():
            st = rec.get("status", "pending") if isinstance(rec, dict) else "pending"
            if st in stats:
                stats[st] += 1
            else:
                stats["pending"] += 1
        self._data["stats"] = stats

    def _save_unlocked(self) -> None:
        self._data["updated_at"] = _now_iso()
        self._recompute_stats()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def get_record(self, src_name: str) -> FileRecord | None:
        with self._lock:
            raw = self._data["files"].get(src_name)
            if not isinstance(raw, dict):
                return None
            return FileRecord.from_dict(raw)

    def should_skip(self, src_path: Path, kind: str) -> tuple[bool, str]:
        """若应跳过（已成功且指纹匹配、输出仍在），返回 (True, reason)。"""
        src_path = Path(src_path)
        src_name = src_path.name
        with self._lock:
            raw = self._data["files"].get(src_name)
            if not isinstance(raw, dict):
                return False, ""
            rec = FileRecord.from_dict(raw)
            if rec.status != "success":
                return False, ""

            fp = _file_fingerprint(src_path)
            # 源已删但成功记录在：视为已完成（工作区清理后常见）
            if not src_path.exists():
                if rec.output and self.output_dir is not None:
                    out = self.output_dir / rec.output
                    if out.is_file():
                        return True, "already done (source removed, output present)"
                # 无源无输出：不跳过（应重新出现任务时再处理）
                if rec.output and self.output_dir is not None:
                    return False, ""
                return True, "already done (source removed)"

            # 源还在：指纹一致且输出存在才跳过
            if rec.size and rec.size != fp["size"]:
                return False, ""
            if rec.mtime and abs(rec.mtime - float(fp["mtime"])) > 1.0:
                return False, ""
            if rec.output and self.output_dir is not None:
                out = self.output_dir / rec.output
                if not out.is_file():
                    return False, ""
            return True, "already done (checkpoint)"

    def mark(
        self,
        src_path: Path,
        *,
        kind: str,
        status: str,
        output: str | None = None,
        error: str | None = None,
    ) -> None:
        src_path = Path(src_path)
        src_name = src_path.name
        fp = _file_fingerprint(src_path) if src_path.exists() else {"size": 0, "mtime": 0.0}
        with self._lock:
            prev = self._data["files"].get(src_name) or {}
            size = int(fp["size"]) or int(prev.get("size") or 0)
            mtime = float(fp["mtime"]) or float(prev.get("mtime") or 0.0)
            self._data["files"][src_name] = {
                "status": status,
                "kind": kind,
                "src_name": src_name,
                "size": size,
                "mtime": mtime,
                "output": output if output is not None else prev.get("output"),
                "error": error,
                "updated_at": _now_iso(),
            }
            self._save_unlocked()

    def stats(self) -> dict[str, int]:
        with self._lock:
            self._recompute_stats()
            return dict(self._data["stats"])

    def path_str(self) -> str:
        return str(self.path)
