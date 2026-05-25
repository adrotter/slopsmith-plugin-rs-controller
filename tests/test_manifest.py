import json
import unittest
from pathlib import Path


class PluginManifestTests(unittest.TestCase):
    def test_backend_routes_are_registered(self):
        root = Path(__file__).parents[1]
        manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["id"], "rocksmith_sync")
        self.assertEqual(manifest["routes"], "routes.py")
        self.assertTrue((root / manifest["routes"]).is_file())


if __name__ == "__main__":
    unittest.main()
