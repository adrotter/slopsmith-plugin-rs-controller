import unittest

from rocksmith_reader import (
    OFFSETS_BY_CHECKSUM,
    PRE_SONG_TUNERS,
    TIMER_OFFSETS,
    TIMER_RARE_OFFSETS,
    OffsetSet,
    RocksmithReader,
    extract_song_key,
    extract_song_key_buffer,
    is_in_song,
    is_playing,
)


class RocksmithStateTests(unittest.TestCase):
    def test_extracts_valid_preview_and_invalid_song_events(self):
        self.assertEqual(extract_song_key("Play_CherubRock_Preview"), "CherubRock")
        self.assertEqual(extract_song_key("Play_Knights_Invalid"), "Knights")
        self.assertIsNone(extract_song_key("Play_NoSuffix"))
        self.assertIsNone(extract_song_key("Stop_CherubRock_Preview"))

    def test_extracts_song_key_from_observed_padded_preview_buffer(self):
        data = b"\0lay_3DooAway_Preview\0\0\0"

        self.assertEqual(extract_song_key_buffer(data), "3DooAway")

    def test_pause_menu_is_in_song_but_not_playing(self):
        self.assertTrue(is_in_song("LearnASong_Pause"))
        self.assertFalse(is_playing("LearnASong_Pause"))
        self.assertTrue(is_playing("LearnASong_Game"))
        self.assertFalse(is_in_song("MainMenu"))

    def test_riff_repeater_ui_menus_are_paused_in_song_states(self):
        for menu in (
            "RiffRepeater",
            "LearnASong_RiffRepeater",
            "RiffRepeater_AdvancedSettings",
            "RiffRepeater_Pause",
        ):
            with self.subTest(menu=menu):
                self.assertTrue(is_in_song(menu))
                self.assertFalse(is_playing(menu))

    def test_known_rsmods_builds_have_offset_tables(self):
        self.assertIn(0x00B13D7C, OFFSETS_BY_CHECKSUM)
        self.assertIn(0x0176EC34, OFFSETS_BY_CHECKSUM)

class FakeSession:
    base_address = 0x1000
    offsets = OffsetSet("test", 0, 0, 0, 0x10, 0x20)

    def __init__(self, timer: float, rare_timer: float):
        self.timer = timer
        self.rare_timer = rare_timer

    def follow(self, start_address, offsets):
        if offsets == TIMER_OFFSETS:
            return 1
        if offsets == TIMER_RARE_OFFSETS:
            return 2
        return None

    def read_float(self, address):
        return self.timer if address == 1 else self.rare_timer


class RocksmithTimerTests(unittest.TestCase):
    def test_rare_timer_is_used_when_normal_song_timer_is_zero(self):
        reader = RocksmithReader()

        position = reader._read_position(FakeSession(0.0, 12.5), "LearnASong_Game")

        self.assertEqual(position, 12.5)

    def test_pre_song_tuner_returns_zero(self):
        reader = RocksmithReader()
        tuner_menu = next(iter(PRE_SONG_TUNERS))

        position = reader._read_position(FakeSession(10.0, 12.5), tuner_menu)

        self.assertEqual(position, 0.0)


if __name__ == "__main__":
    unittest.main()
