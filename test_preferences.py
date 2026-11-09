import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from preferences import Preferences, load_preferences, save_preferences


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='.test-prefs-', dir=Path(__file__).resolve().parent)
        self.path = Path(self.folder.name) / 'settings.json'

    def tearDown(self):
        self.folder.cleanup()

    def test_missing_corrupt_and_invalid_preferences_use_safe_defaults(self):
        self.assertEqual(load_preferences(self.path), Preferences())
        for data in ('broken json', '[]', '{"appearance": "invalid", "media": null, "video_height": true}'):
            self.path.write_text(data)
            self.assertEqual(load_preferences(self.path), Preferences())

    def test_round_trip_saves_only_preferences(self):
        settings = Preferences(output_folder=self.folder.name, media='video', audio_format='MP3',
                               appearance='Dark', video_height=1080)
        save_preferences(self.path, settings)
        self.assertEqual(load_preferences(self.path), settings)
        self.assertEqual(set(json.loads(self.path.read_text())),
                         {'output_folder', 'media', 'audio_format', 'appearance', 'video_height'})

    def test_failed_atomic_save_preserves_previous_settings(self):
        save_preferences(self.path, Preferences())
        original = self.path.read_bytes()
        with patch.object(Path, 'replace', side_effect=PermissionError('Simulated write failure')):
            with self.assertRaises(PermissionError):
                save_preferences(self.path, Preferences(appearance='Dark'))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
