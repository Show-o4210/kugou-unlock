from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from kugou_unlock.enrich import KRC_KEY, decode_krc, run_enrichment


def write_krc(path: Path, text: str) -> None:
    compressed = zlib.compress(text.encode("utf-8"))
    encrypted = bytes(
        value ^ KRC_KEY[index % len(KRC_KEY)]
        for index, value in enumerate(compressed)
    )
    path.write_bytes(b"krc1" + encrypted)


class EnrichTests(unittest.TestCase):
    def test_decode_krc_creates_timed_and_plain_lyrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.krc"
            write_krc(path, "[1234,2000]<0,500,0>Hello<500,500,0> world\n")
            lrc, plain = decode_krc(
                path, artist="Artist", title="Title", album="Album"
            )
            self.assertIn("[00:01.23]Hello world", lrc)
            self.assertEqual(plain, "Hello world")

    def test_external_only_writes_sidecars_from_manual_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio_dir = root / "audio"
            lyrics_dir = root / "lyrics"
            audio_dir.mkdir()
            lyrics_dir.mkdir()
            (audio_dir / "Singer - Song_SQ.flac").write_bytes(b"fLaC")
            write_krc(
                lyrics_dir / "cache-HASH.krc",
                "[0,1000]<0,1000,0>First line\n",
            )

            database = root / "songs.db"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE localmusic (fileid INTEGER, songid INTEGER);
                CREATE TABLE file (
                    fileid INTEGER, musicname TEXT, singer TEXT, songname TEXT,
                    albumname TEXT, filehash TEXT, musichash TEXT, mgg_hash TEXT
                );
                CREATE TABLE kugou_songs (
                    _id INTEGER, hash_320 TEXT, sq_hash TEXT, img_url TEXT
                );
                INSERT INTO localmusic VALUES (1, 2);
                INSERT INTO file VALUES
                    (1, 'Singer - Song', 'Singer', 'Song', 'Album',
                     'HASH', NULL, NULL);
                INSERT INTO kugou_songs VALUES
                    (2, NULL, NULL, 'https://example.invalid/cover.jpg');
                """
            )
            connection.commit()
            connection.close()

            cover = b"\xff\xd8\xff" + b"fake-jpeg"
            with patch(
                "kugou_unlock.enrich.download_cover",
                return_value=(cover, "image/jpeg"),
            ):
                total, ok, failures = run_enrichment(
                    audio_dir,
                    lyrics_dir,
                    database,
                    root / "cache",
                    external_only=True,
                    log=lambda _message: None,
                )

            self.assertEqual((total, ok, failures), (1, 1, []))
            self.assertTrue((audio_dir / "Singer - Song_SQ.lrc").exists())
            self.assertEqual(
                (audio_dir / "Singer - Song_SQ.jpg").read_bytes(), cover
            )


if __name__ == "__main__":
    unittest.main()
