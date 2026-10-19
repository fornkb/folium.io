import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from configuration import Settings, dotenv_values

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "tmp").mkdir(exist_ok=True)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        assert self.root.resolve().is_relative_to((ROOT / "tmp").resolve())
        self.env_file = self.root / ".env"
        self.settings = Settings(self.root, env_file=self.env_file)
        self.external = patch("configuration.environment_values", return_value={})
        self.environment = self.external.start()

    def tearDown(self):
        self.external.stop()
        self.temp.cleanup()

    def test_dotenv_quotes_comments_and_bom(self):
        self.env_file.write_text('\ufeff# local configuration\nexport GEMINI_API_KEY="test-secret" # comment\nGEMINI_MODEL=gemini-test # model\nGOOGLE_API_KEY=\'alternate-key\'\nOTHER=$(never-run-this)\n', encoding="utf-8")
        values = dotenv_values(self.env_file)
        self.assertEqual("test-secret", values["GEMINI_API_KEY"])
        self.assertEqual("gemini-test", values["GEMINI_MODEL"])
        self.assertNotIn("OTHER", values)

    def test_env_file_is_loaded_and_reread_without_restart(self):
        self.assertFalse(self.settings.public()["has_key"])
        self.env_file.write_text("GEMINI_API_KEY=first-test-key\n", encoding="utf-8")
        self.assertEqual("first-test-key", self.settings.get()["api_key"])
        self.assertEqual("env_file", self.settings.public()["key_source"])
        self.env_file.write_text("GEMINI_API_KEY=updated-test-key\n", encoding="utf-8")
        self.assertEqual("updated-test-key", self.settings.get()["api_key"])

    def test_process_environment_overrides_env_file(self):
        self.env_file.write_text("GEMINI_API_KEY=file-test-key\n", encoding="utf-8")
        self.environment.return_value = {"GEMINI_API_KEY":"process-test-key"}
        self.assertEqual("process-test-key", self.settings.get()["api_key"])
        self.assertEqual("environment", self.settings.public()["key_source"])

    def test_google_api_key_is_supported(self):
        self.env_file.write_text("GOOGLE_API_KEY=google-test-key\n", encoding="utf-8")
        self.assertEqual("google-test-key", self.settings.get()["api_key"])

    def test_blank_saved_key_does_not_mask_environment(self):
        self.settings.path.write_text(json.dumps(dict(api_key="")), encoding="utf-8")
        self.environment.return_value = {"GEMINI_API_KEY":"available-test-key"}
        self.assertTrue(self.settings.public()["has_key"])
        self.assertEqual("available-test-key", self.settings.get()["api_key"])

    def test_manual_override_and_remove_falls_back_to_env_file(self):
        self.env_file.write_text("GEMINI_API_KEY=file-test-key\n", encoding="utf-8")
        self.settings.save(dict(api_key="manual-test-key"))
        self.assertEqual("manual-test-key", self.settings.get()["api_key"])
        self.assertEqual("settings", self.settings.public()["key_source"])
        self.settings.save(dict(clear_key=True))
        self.assertEqual("file-test-key", self.settings.get()["api_key"])
        self.assertFalse(self.settings.public()["has_saved_key"])

    def test_saving_options_does_not_copy_env_key_to_settings(self):
        self.env_file.write_text("GEMINI_API_KEY=file-test-key\n", encoding="utf-8")
        self.settings.save(dict(interval=12, api_key=""))
        saved = json.loads(self.settings.path.read_text("utf-8"))
        self.assertNotIn("api_key", saved)
        self.assertNotIn("file-test-key", self.settings.path.read_text("utf-8"))

    def test_public_settings_report_source_without_credentials(self):
        self.env_file.write_text("GEMINI_API_KEY=file-test-key\n", encoding="utf-8")
        public = self.settings.public()
        self.assertTrue(public["env_file_found"])
        self.assertTrue(public["has_key"])
        self.assertNotIn("api_key", public)
        self.assertNotIn("file-test-key", json.dumps(public))


if __name__ == "__main__":
    unittest.main()
