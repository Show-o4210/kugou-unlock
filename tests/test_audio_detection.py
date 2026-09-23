from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kugou_unlock.audio import (
    KGM_MAGIC,
    collect_encrypted_files,
    crypto_ext_of,
    detect_process_kind,
    encrypted_base_stem,
)


def crypto_header(version: int) -> bytes:
    return KGM_MAGIC + b"\x00" * 4 + version.to_bytes(4, "little")


class AudioDetectionTests(unittest.TestCase):
    def test_crypto_suffix_can_have_arbitrary_trailing_suffixes(self) -> None:
        path = Path("artist.song.kgg.flac.download")
        self.assertEqual(crypto_ext_of(path), ".kgg")
        self.assertEqual(encrypted_base_stem(path), "artist.song")

    def test_rightmost_crypto_suffix_wins(self) -> None:
        path = Path("archive.kgm.track.kgg.unknown")
        self.assertEqual(crypto_ext_of(path), ".kgg")
        self.assertEqual(encrypted_base_stem(path), "archive.kgm.track")

    def test_header_detects_kgg_without_known_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "song.special-cache"
            path.write_bytes(crypto_header(5))
            self.assertEqual(detect_process_kind(path), "kgg")

    def test_header_overrides_misleading_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "song.kgg.flac.bak"
            path.write_bytes(crypto_header(3))
            self.assertEqual(detect_process_kind(path), "kgm")

    def test_plain_audio_header_overrides_crypto_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "already-clear.kgg.flac"
            path.write_bytes(b"fLaC" + b"\x00" * 20)
            self.assertEqual(detect_process_kind(path), "plain")

    def test_directory_collection_uses_content_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kgg = root / "one.cache"
            kgm = root / "two.unusual"
            kgg.write_bytes(crypto_header(5))
            kgm.write_bytes(crypto_header(3))
            kgg_files, kgm_files = collect_encrypted_files(root)
            self.assertEqual(kgg_files, [kgg])
            self.assertEqual(kgm_files, [kgm])


if __name__ == "__main__":
    unittest.main()
