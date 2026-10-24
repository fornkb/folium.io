"""Model roles, cache separation, and settings persistence without live inference."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from configuration import Settings
from core import Store
from generation import (Gemini, TEACHING, SCOPED_TEACHING, PACKAGE, SCOPED_PACKAGE,
                        TEACHING_PLAN, SCOPED_TEACHING_PLAN, SCOPE_BATCH, SCOPE_MERGE,
                        OUTLINE, ASSESSMENT, PYQ_SCHEMA, VISUAL_SCOPE)
from test_core import test_directory


class ModelTests(unittest.TestCase):
    def test_defaults_and_environment_role_precedence(self):
        with test_directory() as folder, patch("configuration.environment_values", return_value={}) as environment:
            path = Path(folder) / "models.env"
            settings = Settings(folder, env_file=path)
            self.assertEqual("gemini-3.8-flash", settings.get()["model"])
            self.assertEqual("gemini-3.5-flash-lite", settings.get()["task_model"])
            self.assertEqual(settings.get()["task_model"], settings.get()["vision_model"])
            path.write_text("GEMINI_MODEL=gemini-teach-file\nGEMINI_TASK_MODEL=gemini-task-file\n", encoding="utf-8")
            self.assertEqual("gemini-teach-file", settings.get()["model"])
            self.assertEqual("gemini-task-file", settings.get()["vision_model"])
            environment.return_value = {"GEMINI_TASK_MODEL": "gemini-task-process"}
            self.assertEqual("gemini-task-process", settings.get()["task_model"])
            settings.save(dict(model="gemini-teach-saved", task_model="gemini-task-saved"))
            restored = Settings(folder, env_file=path)
            self.assertEqual("gemini-teach-saved", restored.public()["model"])
            self.assertEqual("gemini-task-saved", restored.public()["task_model"])
            self.assertEqual("gemini-task-saved", restored.public()["vision_model"])
            restored.save(dict(vision_model="gemini-vision-saved"))
            self.assertEqual("gemini-vision-saved", restored.get()["vision_model"])

    def test_role_updates_preserve_credentials_and_reject_invalid_models(self):
        with test_directory() as folder, patch("configuration.environment_values", return_value={}):
            settings = Settings(folder, env_file=Path(folder) / "absent.env")
            settings.save(dict(api_key="synthetic-one", api_key_2="synthetic-two"))
            settings.save(dict(model="gemini-3.8-flash", task_model="gemini-3.5-flash-lite", vision_model="gemini-3.5-flash-lite"))
            self.assertEqual(["synthetic-one", "synthetic-two"], settings.get()["api_keys"])
            before = settings.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "other tasks"):
                settings.save(dict(task_model="invalid/model"))
            self.assertEqual(before, settings.path.read_bytes())
            self.assertNotIn("synthetic-", json.dumps(settings.public()))

    def test_provider_routes_every_schema_and_caches_by_selected_model(self):
        with test_directory() as folder, patch("configuration.environment_values", return_value={}):
            store = Store(folder)
            settings = Settings(folder, env_file=Path(folder) / "absent.env")
            settings.save(dict(api_key="synthetic-key", model="gemini-teaching-test", task_model="gemini-task-test"))
            provider = Gemini(store, settings)
            requests = []
            raw = json.dumps(dict(candidates=[dict(content=dict(parts=[dict(text='{"ok":true}')]))])).encode()
            def respond(request, timeout):
                requests.append(request)
                return io.BytesIO(raw)
            with patch("generation.urllib.request.urlopen", side_effect=respond), patch("generation.time.sleep"):
                for schema in (TEACHING, SCOPED_TEACHING, PACKAGE, SCOPED_PACKAGE):
                    provider.generate("same prompt", schema)
                    self.assertIn("/gemini-teaching-test:", requests[-1].full_url)
                for schema in (TEACHING_PLAN, SCOPED_TEACHING_PLAN, SCOPE_BATCH, SCOPE_MERGE, OUTLINE, ASSESSMENT, PYQ_SCHEMA, VISUAL_SCOPE):
                    provider.generate("same prompt", schema)
                    self.assertIn("/gemini-task-test:", requests[-1].full_url)
                count = len(requests)
                provider.generate("same prompt", ASSESSMENT)
                self.assertEqual(count, len(requests))
                settings.save(dict(model="gemini-teaching-changed"))
                provider.generate("same prompt", ASSESSMENT)
                self.assertEqual(count, len(requests))
                settings.save(dict(task_model="gemini-task-changed"))
                provider.generate("same prompt", ASSESSMENT)
                self.assertEqual(count + 1, len(requests))
                self.assertIn("/gemini-task-changed:", requests[-1].full_url)
                provider.generate("same prompt", TEACHING)
                self.assertIn("/gemini-teaching-changed:", requests[-1].full_url)
            store.close()


if __name__ == "__main__":
    unittest.main()
