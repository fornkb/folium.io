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

    def test_three_slots_resolve_overrides_independently(self):
        self.env_file.write_text("GEMINI_API_KEY=file-one\nGEMINI_API_KEY_2=file-two\nGEMINI_API_KEY_3=file-three\n", encoding="utf-8")
        self.environment.return_value = {"GEMINI_API_KEY_2":"process-two"}
        self.settings.save(dict(api_key_3="saved-three"))
        self.assertEqual(["file-one", "process-two", "saved-three"], self.settings.get()["api_keys"])
        public = self.settings.public()
        self.assertEqual(3, public["key_count"])
        self.assertEqual(["env_file", "environment", "settings"], [s["key_source"] for s in public["key_slots"]])
        self.assertEqual([False, False, True], [s["has_saved_key"] for s in public["key_slots"]])
        for secret in ("file-one", "process-two", "saved-three"):
            self.assertNotIn(secret, json.dumps(public))

    def test_optional_google_aliases_and_gemini_precedence(self):
        self.env_file.write_text("GOOGLE_API_KEY_2=google-two\nGOOGLE_API_KEY_3=google-three\nGEMINI_API_KEY_3=gemini-three\n", encoding="utf-8")
        self.assertEqual(["google-two", "gemini-three"], self.settings.get()["api_keys"])
        self.assertTrue(self.settings.public()["has_key"])
        self.assertFalse(self.settings.public()["key_slots"][0]["has_key"])

    def test_empty_inputs_preserve_all_keys_across_restart(self):
        self.settings.save(dict(api_key="saved-one", api_key_2="saved-two", api_key_3="saved-three"))
        self.settings.save(dict(api_key="", api_key_2="  ", api_key_3="", interval=12))
        restored = Settings(self.root, env_file=self.env_file)
        self.assertEqual(["saved-one", "saved-two", "saved-three"], restored.get()["api_keys"])
        self.assertEqual(12, restored.public()["interval"])

    def test_removing_one_saved_key_keeps_other_slots_and_environment_fallback(self):
        self.env_file.write_text("GEMINI_API_KEY_2=file-two\n", encoding="utf-8")
        self.settings.save(dict(api_key="saved-one", api_key_2="saved-two", api_key_3="saved-three"))
        self.settings.save(dict(clear_key_2=True))
        self.assertEqual(["saved-one", "file-two", "saved-three"], self.settings.get()["api_keys"])
        self.assertFalse(self.settings.public()["key_slots"][1]["has_saved_key"])
        self.settings.save(dict(clear_key_3=True))
        self.assertEqual(["saved-one", "file-two"], self.settings.get()["api_keys"])

    def test_saving_options_does_not_persist_any_environment_keys(self):
        self.env_file.write_text("GEMINI_API_KEY=env-one\nGEMINI_API_KEY_2=env-two\nGEMINI_API_KEY_3=env-three\n", encoding="utf-8")
        self.settings.save(dict(interval=12, api_key="", api_key_2="", api_key_3=""))
        saved = json.loads(self.settings.path.read_text("utf-8"))
        self.assertEqual({"model":"gemini-3.8-flash", "interval":12}, saved)

    def test_duplicate_keys_count_once_without_changing_slot_status(self):
        self.settings.save(dict(api_key="repeated-key", api_key_2="repeated-key", api_key_3="other-key"))
        self.assertEqual(["repeated-key", "other-key"], self.settings.get()["api_keys"])
        self.assertEqual(2, self.settings.public()["key_count"])
        self.assertTrue(all(s["has_key"] for s in self.settings.public()["key_slots"]))


if __name__ == "__main__":
    unittest.main()
