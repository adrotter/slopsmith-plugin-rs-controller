import tempfile
import json
import unittest
from pathlib import Path

from routes import SongResolver


class SongResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dlc = root / "dlc"
        self.config = root / "config"
        self.dlc.mkdir()
        self.resolver = SongResolver(self.dlc, self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, name):
        path = self.dlc / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        return path

    def test_sloppak_is_preferred_over_psarc(self):
        self.touch("songs/cherubrock_p.psarc")
        self.touch("songs/cherubrock_p.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("CherubRock")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/cherubrock_p.sloppak")

    def test_psarc_is_used_when_no_sloppak_exists(self):
        self.touch("songs/knights_p.psarc")
        self.touch("songs/knights_m.psarc")
        self.resolver.rescan()

        match = self.resolver.resolve("knights")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "psarc")
        self.assertEqual(match.filename, "songs/knights_p.psarc")

    def test_manual_mapping_handles_nonmatching_names(self):
        self.touch("custom/my-audio-name.sloppak")
        self.resolver.set_mapping("odd_song_key", "custom/my-audio-name.sloppak")

        match = self.resolver.resolve("odd_song_key")

        self.assertIsNotNone(match)
        self.assertFalse(match.automatic)
        self.assertEqual(match.filename, "custom/my-audio-name.sloppak")

    def test_automatic_sloppak_beats_manual_psarc(self):
        self.touch("songs/priority_p.sloppak")
        self.touch("custom/manual.psarc")
        self.resolver.rescan()
        self.resolver.set_mapping("priority", "custom/manual.psarc")

        match = self.resolver.resolve("priority")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertTrue(match.automatic)

    def test_converted_sloppak_matches_source_psarc_dlc_key(self):
        source = self.touch("cdlc/Pink-Floyd_Have-A-Cigar_v1_p.psarc")
        output = self.touch("sloppak/Pink-Floyd_Have-A-Cigar_v1.sloppak")
        jobs = {
            "jobs": [{
                "filename": source.relative_to(self.dlc).as_posix(),
                "output_path": str(output),
                "state": "done",
            }]
        }
        self.config.mkdir()
        (self.config / "sloppak_converter_jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        resolver = SongResolver(self.dlc, self.config, lambda _: {"floydcigar"})
        resolver.rescan()

        match = resolver.resolve("FloydCigar")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertTrue(match.automatic)
        self.assertEqual(match.filename, "sloppak/Pink-Floyd_Have-A-Cigar_v1.sloppak")

    def test_manual_mapping_rejects_missing_files(self):
        with self.assertRaises(ValueError):
            self.resolver.set_mapping("missing", "not-there.sloppak")


if __name__ == "__main__":
    unittest.main()
