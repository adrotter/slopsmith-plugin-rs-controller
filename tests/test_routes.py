import tempfile
import json
import unittest
from pathlib import Path

from routes import SongIdentity, SongResolver


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

    def test_sloppak_filename_can_match_title_inside_artist_title_name(self):
        self.touch("songs/The Cure - Boys Don't Cry.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("BoysDontCry")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/The Cure - Boys Don't Cry.sloppak")

    def test_sloppak_filename_can_match_reversed_artist_title_name(self):
        self.touch("songs/Boys Don't Cry - The Cure.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("TheCureBoysDontCry")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Boys Don't Cry - The Cure.sloppak")

    def test_sloppak_filename_can_match_compact_reversed_artist_title_name(self):
        self.touch("songs/Boys Don't Cry-The Cure.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("TheCureBoysDontCry")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Boys Don't Cry-The Cure.sloppak")

    def test_sloppak_filename_can_match_underscored_artist_title_separator(self):
        self.touch("songs/The_Cure_-_Boys_Don't_Cry_v1_p.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("BoysDontCry")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/The_Cure_-_Boys_Don't_Cry_v1_p.sloppak")

    def test_sloppak_filename_part_can_match_short_title(self):
        self.touch("songs/Chimney_-_Yellow_Moon_Band.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Chimney")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Chimney_-_Yellow_Moon_Band.sloppak")

    def test_sloppak_filename_part_can_match_five_letter_title(self):
        self.touch("songs/Breed_-_Nirvana.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Breed")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Breed_-_Nirvana.sloppak")

    def test_sloppak_filename_part_can_match_four_letter_title(self):
        self.touch("songs/Time_-_Pink_Floyd.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Time")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Time_-_Pink_Floyd.sloppak")

    def test_sloppak_filename_part_can_match_three_letter_title(self):
        self.touch("songs/Now_-_Paramore.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Now")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Now_-_Paramore.sloppak")

    def test_ambiguous_filename_part_alias_is_ignored(self):
        self.touch("songs/SharedTitle_-_First_Artist.sloppak")
        self.touch("songs/SharedTitle_-_Second_Artist.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("SharedTitle")

        self.assertIsNone(match)

    def test_short_numeric_title_can_match_artist_title_sloppak(self):
        self.touch("songs/Blur - Song 2.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Song2")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/Blur - Song 2.sloppak")

    def test_ambiguous_short_numeric_fuzzy_match_is_ignored(self):
        self.touch("songs/First Artist - Song 2.sloppak")
        self.touch("songs/Second Artist - Song 2.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("Song2")

        self.assertIsNone(match)

    def test_fuzzy_sloppak_beats_exact_psarc(self):
        self.touch("songs/boysdontcry_p.psarc")
        self.touch("songs/The Cure - Boys Don't Cry.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("BoysDontCry")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "songs/The Cure - Boys Don't Cry.sloppak")

    def test_ambiguous_fuzzy_sloppak_match_is_ignored(self):
        self.touch("songs/First Artist - Shared Title.sloppak")
        self.touch("songs/Second Artist - Shared Title.sloppak")
        self.resolver.rescan()

        match = self.resolver.resolve("SharedTitle")

        self.assertIsNone(match)

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

    def test_psarc_matches_dlc_key_when_filename_differs(self):
        source = self.touch("cdlc/Pink-Floyd_Have-A-Cigar_v1_p.psarc")
        resolver = SongResolver(self.dlc, self.config, lambda path: {"floydcigar"} if path == source else set())

        match = resolver.resolve("FloydCigar")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "psarc")
        self.assertTrue(match.automatic)
        self.assertEqual(match.filename, "cdlc/Pink-Floyd_Have-A-Cigar_v1_p.psarc")

    def test_psarc_metadata_key_can_match_sloppak_title_and_artist(self):
        source = self.touch("songs/official_pack.psarc")
        sloppak = self.touch("sloppak/Now_-_Paramore.sloppak")

        def read_psarc_metadata(path):
            if path == source:
                return {"paramorenow": SongIdentity("Now", "Paramore", "Paramore")}
            return {}

        def read_sloppak_identity(path):
            if path == sloppak:
                return SongIdentity("Now", "Paramore", "Paramore")
            return None

        resolver = SongResolver(
            self.dlc,
            self.config,
            psarc_metadata_reader=read_psarc_metadata,
            sloppak_identity_reader=read_sloppak_identity,
        )

        match = resolver.resolve("ParamoreNow")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertTrue(match.automatic)
        self.assertEqual(match.filename, "sloppak/Now_-_Paramore.sloppak")

    def test_base_songs_psarc_metadata_can_match_sloppak_title_and_artist(self):
        source = self.dlc.parent / "songs.psarc"
        source.write_bytes(b"base songs")
        sloppak = self.touch("sloppak/Don_t_Stop_-_Crimson.sloppak")

        def read_psarc_metadata(path):
            if path == source:
                return {"dontstop": SongIdentity("Don't Stop", "Crimson", "Crimson")}
            return {}

        def read_sloppak_identity(path):
            if path == sloppak:
                return SongIdentity("Don't Stop", "Crimson", "Crimson")
            return None

        resolver = SongResolver(
            self.dlc,
            self.config,
            psarc_metadata_reader=read_psarc_metadata,
            sloppak_identity_reader=read_sloppak_identity,
        )

        match = resolver.resolve("DontStop")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertTrue(match.automatic)
        self.assertEqual(match.filename, "sloppak/Don_t_Stop_-_Crimson.sloppak")

    def test_base_songs_psarc_is_not_used_as_playable_fallback(self):
        source = self.dlc.parent / "songs.psarc"
        source.write_bytes(b"base songs")

        resolver = SongResolver(
            self.dlc,
            self.config,
            psarc_metadata_reader=lambda path: {
                "dontstop": SongIdentity("Don't Stop", "Crimson", "Crimson")
            } if path == source else {},
        )

        match = resolver.resolve("DontStop")

        self.assertIsNone(match)

    def test_psarc_metadata_uses_psarc_when_sloppak_identity_is_ambiguous(self):
        source = self.touch("songs/official_pack.psarc")
        first = self.touch("sloppak/custom-one.sloppak")
        second = self.touch("other/custom-two.sloppak")

        def read_psarc_metadata(path):
            if path == source:
                return {"paramorenow": SongIdentity("Now", "Paramore", "Paramore")}
            return {}

        def read_sloppak_identity(path):
            if path in {first, second}:
                return SongIdentity("Now", "Paramore", "Paramore")
            return None

        resolver = SongResolver(
            self.dlc,
            self.config,
            psarc_metadata_reader=read_psarc_metadata,
            sloppak_identity_reader=read_sloppak_identity,
        )

        match = resolver.resolve("ParamoreNow")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "psarc")
        self.assertEqual(match.filename, "songs/official_pack.psarc")

    def test_persisted_song_index_is_reused_after_restart(self):
        source = self.touch("cdlc/nonmatching-name_p.psarc")
        resolver = SongResolver(self.dlc, self.config, lambda path: {"internalkey"} if path == source else set())
        resolver.rescan()

        index_path = self.config / "rocksmith_sync_song_index.json"
        self.assertTrue(index_path.is_file())

        def fail_if_reparsed(_):
            raise AssertionError("persisted song index should avoid reparsing PSARCs")

        restarted = SongResolver(self.dlc, self.config, fail_if_reparsed)
        match = restarted.resolve("InternalKey")

        self.assertIsNotNone(match)
        self.assertEqual(match.filename, "cdlc/nonmatching-name_p.psarc")

    def test_song_index_is_invalidated_when_library_changes(self):
        self.touch("songs/first_p.psarc")
        calls = []

        def read_keys(path):
            calls.append(path)
            return set()

        resolver = SongResolver(self.dlc, self.config, read_keys)
        resolver.rescan()
        initial_calls = len(calls)
        self.touch("songs/second_p.psarc")

        match = resolver.resolve("second")

        self.assertIsNotNone(match)
        self.assertEqual(match.filename, "songs/second_p.psarc")
        self.assertGreater(len(calls), initial_calls)

    def test_song_index_is_invalidated_when_converter_jobs_change(self):
        source = self.touch("cdlc/nonmatching-name_p.psarc")
        output = self.touch("sloppak/nonmatching-name.sloppak")
        self.config.mkdir()
        jobs_path = self.config / "sloppak_converter_jobs.json"
        jobs_path.write_text(json.dumps({"jobs": []}), encoding="utf-8")
        resolver = SongResolver(self.dlc, self.config, lambda path: {"internalkey"} if path == source else set())
        resolver.rescan()
        jobs_path.write_text(
            json.dumps(
                {
                    "jobs": [{
                        "filename": source.relative_to(self.dlc).as_posix(),
                        "output_path": str(output),
                        "state": "done",
                    }]
                }
            ),
            encoding="utf-8",
        )

        match = resolver.resolve("InternalKey")

        self.assertIsNotNone(match)
        self.assertEqual(match.format, "sloppak")
        self.assertEqual(match.filename, "sloppak/nonmatching-name.sloppak")

    def test_manual_mapping_rejects_missing_files(self):
        with self.assertRaises(ValueError):
            self.resolver.set_mapping("missing", "not-there.sloppak")


if __name__ == "__main__":
    unittest.main()
