"""从用户手动导出的酷狗 Android 数据补全歌词、封面和音频标签。"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import urllib.request
import zlib
from pathlib import Path


KRC_KEY = b"@Gaw^2tGQ61-\xce\xd2ni"
QUALITY_SUFFIX = re.compile(r"_(?:MQ|HQ|SQ)$", re.IGNORECASE)
WORD_TIMING = re.compile(r"<\d+,\d+,\d+>")
LINE_TIMING = re.compile(r"^\[(\d+),(\d+)\](.*)$")
SUPPORTED_AUDIO_EXTS = frozenset({".flac", ".ogg", ".mp3"})


def decode_krc(path: Path, *, artist: str, title: str, album: str) -> tuple[str, str]:
    """将酷狗 KRC 解码为 (带时间轴 LRC, 纯文本歌词)。"""
    data = path.read_bytes()
    if not data.startswith(b"krc1"):
        raise ValueError(f"not a KRC file: {path.name}")
    encrypted = data[4:]
    compressed = bytes(
        value ^ KRC_KEY[index % len(KRC_KEY)]
        for index, value in enumerate(encrypted)
    )
    source = zlib.decompress(compressed).decode("utf-8-sig")

    timed_lines: list[str] = []
    plain_lines: list[str] = []
    for raw_line in source.splitlines():
        match = LINE_TIMING.match(raw_line)
        if not match:
            continue
        start_ms = int(match.group(1))
        lyric = WORD_TIMING.sub("", match.group(3)).strip()
        if not lyric:
            continue
        minutes, remainder = divmod(start_ms, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        timed_lines.append(
            f"[{minutes:02d}:{seconds:02d}.{milliseconds // 10:02d}]{lyric}"
        )
        plain_lines.append(lyric)

    if not timed_lines:
        raise ValueError(f"no timed lyric lines in {path.name}")
    header = [
        f"[ar:{artist}]",
        f"[ti:{title}]",
        f"[al:{album}]",
        "[by:KuGou Android cache]",
    ]
    return "\n".join(header + timed_lines) + "\n", "\n".join(plain_lines)


def image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("cover is not a supported JPEG, PNG, or WebP image")


def download_cover(url: str, cache_dir: Path) -> tuple[bytes, str]:
    """下载数据库记录的原始封面 URL，并以 URL 哈希进行本地缓存。"""
    url = url.replace("{size}", "720").replace("http://", "https://", 1)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / hashlib.sha256(url.encode("utf-8")).hexdigest()
    if cache_path.exists():
        data = cache_path.read_bytes()
        return data, image_mime(data)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.kugou.com/"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    mime = image_mime(data)
    cache_path.write_bytes(data)
    return data, mime


def atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def embed_metadata(
    audio_path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    lyrics: str,
    cover: bytes,
    cover_mime: str,
) -> None:
    """原子地写入标签；mutagen 仅在调用本函数时才是必需依赖。"""
    try:
        from mutagen.flac import FLAC, Picture
        from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, USLT
        from mutagen.oggvorbis import OggVorbis
    except ImportError as exc:
        raise RuntimeError(
            "embedding metadata requires mutagen; run 'python -m pip install mutagen' "
            "or use --external-only"
        ) from exc

    temp = audio_path.with_name(f".{audio_path.stem}.enrich{audio_path.suffix}")
    shutil.copy2(audio_path, temp)
    try:
        suffix = audio_path.suffix.lower()
        if suffix == ".flac":
            audio = FLAC(temp)
            audio["title"] = title
            audio["artist"] = artist
            audio["album"] = album
            audio["lyrics"] = lyrics
            picture = Picture()
            picture.type = 3
            picture.mime = cover_mime
            picture.desc = "Cover"
            picture.data = cover
            audio.clear_pictures()
            audio.add_picture(picture)
            audio.save()
        elif suffix == ".ogg":
            audio = OggVorbis(temp)
            audio["title"] = title
            audio["artist"] = artist
            audio["album"] = album
            audio["lyrics"] = lyrics
            picture = Picture()
            picture.type = 3
            picture.mime = cover_mime
            picture.desc = "Cover"
            picture.data = cover
            audio["metadata_block_picture"] = [
                base64.b64encode(picture.write()).decode("ascii")
            ]
            audio.save()
        elif suffix == ".mp3":
            try:
                tags = ID3(temp)
            except Exception:
                tags = ID3()
            for frame in ("TIT2", "TPE1", "TALB", "APIC", "USLT"):
                tags.delall(frame)
            tags.add(TIT2(encoding=3, text=title))
            tags.add(TPE1(encoding=3, text=artist))
            tags.add(TALB(encoding=3, text=album))
            tags.add(
                APIC(
                    encoding=3,
                    mime=cover_mime,
                    type=3,
                    desc="Cover",
                    data=cover,
                )
            )
            tags.add(USLT(encoding=3, lang="chi", desc="", text=lyrics))
            tags.save(temp, v2_version=3)
        else:
            raise ValueError(f"unsupported output format: {audio_path.suffix}")
        os.replace(temp, audio_path)
    finally:
        temp.unlink(missing_ok=True)


def load_tracks(database: Path) -> dict[str, sqlite3.Row]:
    """读取本地歌曲与酷狗歌曲表的关联信息。"""
    # 只读打开用户导出的副本，避免 SQLite 创建日志或改写任何数据。
    database_uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT f.musicname, f.singer, f.songname, f.albumname,
                   f.filehash, f.musichash, f.mgg_hash,
                   ks.hash_320, ks.sq_hash, ks.img_url
            FROM localmusic AS lm
            JOIN file AS f ON f.fileid = lm.fileid
            LEFT JOIN kugou_songs AS ks ON ks._id = lm.songid
            """
        ).fetchall()
        return {row["musicname"]: row for row in rows if row["musicname"]}
    except sqlite3.Error as exc:
        raise ValueError(
            "unsupported or incomplete KuGou database; copy the database while the "
            "app is closed and keep its -wal/-shm files beside it when present"
        ) from exc
    finally:
        connection.close()


def find_krc(lyrics_dir: Path, row: sqlite3.Row) -> Path | None:
    hashes = (
        row["filehash"],
        row["musichash"],
        row["hash_320"],
        row["sq_hash"],
        row["mgg_hash"],
    )
    for value in hashes:
        if not value:
            continue
        matches = sorted(lyrics_dir.rglob(f"*-{value}.krc"))
        if not matches:
            # Windows 通常不区分大小写；此回退也保证 Linux 上能匹配大小写不同的 hash。
            expected = str(value).lower()
            matches = sorted(
                path
                for path in lyrics_dir.rglob("*.krc")
                if path.stem.rpartition("-")[2].lower() == expected
            )
        if matches:
            return matches[0]
    return None


def run_enrichment(
    audio_dir: Path | str,
    lyrics_dir: Path | str,
    database: Path | str,
    cover_cache: Path | str,
    *,
    external_only: bool = False,
    log=print,
) -> tuple[int, int, list[str]]:
    """补全目录内音频，返回 (总数, 成功数, 失败信息)。"""
    audio_dir = Path(audio_dir)
    lyrics_dir = Path(lyrics_dir)
    database = Path(database)
    cover_cache = Path(cover_cache)
    if not audio_dir.is_dir():
        raise ValueError(f"audio directory not found: {audio_dir}")
    if not lyrics_dir.is_dir():
        raise ValueError(f"lyrics directory not found: {lyrics_dir}")
    if not database.is_file():
        raise ValueError(f"database not found: {database}")

    tracks = load_tracks(database)
    audio_files = sorted(
        path
        for path in audio_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTS
    )
    ok = 0
    failures: list[str] = []
    for audio_path in audio_files:
        lookup_name = QUALITY_SUFFIX.sub("", audio_path.stem)
        row = tracks.get(lookup_name)
        if row is None:
            failures.append(
                f"{audio_path.name}: no database match for {lookup_name!r}"
            )
            continue
        krc_path = find_krc(lyrics_dir, row)
        if krc_path is None:
            failures.append(f"{audio_path.name}: no matching KRC")
            continue
        if not row["img_url"]:
            failures.append(f"{audio_path.name}: no cover URL")
            continue
        try:
            title = row["songname"] or lookup_name
            artist = row["singer"] or ""
            album = row["albumname"] or title
            lrc, plain_lyrics = decode_krc(
                krc_path,
                artist=artist,
                title=title,
                album=album,
            )
            cover, mime = download_cover(row["img_url"], cover_cache)
            cover_suffix = {
                "image/png": ".png",
                "image/webp": ".webp",
            }.get(mime, ".jpg")
            atomic_write(audio_path.with_suffix(".lrc"), lrc.encode("utf-8-sig"))
            atomic_write(audio_path.with_suffix(cover_suffix), cover)
            if not external_only:
                embed_metadata(
                    audio_path,
                    title=title,
                    artist=artist,
                    album=album,
                    lyrics=plain_lyrics,
                    cover=cover,
                    cover_mime=mime,
                )
            ok += 1
            action = "external files" if external_only else "external files + tags"
            log(f"[+] {audio_path.name}: {action}")
        except Exception as exc:
            failures.append(f"{audio_path.name}: {exc}")

    return len(audio_files), ok, failures
