"""Exercise actual request headers without contacting Gemini or using real keys."""
import io
import json
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from configuration import Settings
from core import Store
from generation import Gemini, ProviderError

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "tmp").mkdir(exist_ok=True)


class KeyRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.settings = Settings(self.root, env_file=self.root / "absent.env")
        self.external = patch("configuration.environment_values", return_value={})
        self.external.start()
        self.settings.save(dict(api_key="test-one", api_key_2="test-two", api_key_3="test-three"))
        self.provider = Gemini(self.store, self.settings)
        self.seen = []
        self.raw = json.dumps(dict(candidates=[dict(finishReason="STOP", content=dict(parts=[dict(text='{"ok":true}')]))])).encode()
        self.network = patch("generation.urllib.request.urlopen", side_effect=self.respond)
        self.request = self.network.start()
        self.sleep = patch("generation.time.sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.network.stop()
        self.external.stop()
        self.store.close()
        self.temp.cleanup()

    def respond(self, request, **kwargs):
        self.seen.append(request.get_header("X-goog-api-key"))
        # Credentials are sent only as authentication, never as prompt data or URL parameters.
        for key in ("test-one", "test-two", "test-three"):
            self.assertNotIn(key, request.full_url)
            self.assertNotIn(key.encode(), request.data)
        return io.BytesIO(self.raw)

    def generate(self, prompt):
        return self.provider.generate(prompt, {"type":"OBJECT"})

    def test_outgoing_calls_repeat_three_key_sequence(self):
        for n in range(7):
            self.generate(f"lesson {n}")
        self.assertEqual(["test-one", "test-two", "test-three", "test-one", "test-two", "test-three", "test-one"], self.seen)

    def test_sparse_slots_duplicates_and_single_key_remain_usable(self):
        self.settings.save(dict(clear_key=True))
        for n in range(3):
            self.generate(f"two keys {n}")
        self.assertEqual(["test-two", "test-three", "test-two"], self.seen)
        self.settings.save(dict(api_key_3="test-two"))
        for n in range(2):
            self.generate(f"one distinct key {n}")
        self.assertEqual(["test-two", "test-two"], self.seen[-2:])

    def test_cache_hits_and_key_changes_do_not_repeat_saved_calls(self):
        self.generate("saved lesson")
        self.generate("saved lesson")
        self.generate("next lesson")
        self.assertEqual(["test-one", "test-two"], self.seen)
        self.settings.save(dict(api_key="replacement-key"))
        self.generate("saved lesson")
        self.assertEqual(2, self.request.call_count)
        self.generate("new pool lesson")
        self.assertEqual("replacement-key", self.seen[-1])

    def test_error_advances_turn_without_automatic_retry(self):
        for status in (429, 403, 503):
            with self.subTest(status=status):
                def fail(request, **kwargs):
                    self.seen.append(request.get_header("X-goog-api-key"))
                    raise urllib.error.HTTPError(request.full_url, status, "provider error", {}, None)
                self.request.side_effect = fail
                with self.assertRaises(ProviderError) as error:
                    self.generate(f"unfinished {status}")
                self.assertNotIn("test-", str(error.exception))
                self.request.side_effect = self.respond
                self.generate(f"unfinished {status}")
        self.assertEqual(["test-one", "test-two", "test-three", "test-one", "test-two", "test-three"], self.seen)
        self.assertEqual(6, self.request.call_count)

    def test_concurrent_courses_share_one_rotation(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.generate, [f"course {n}" for n in range(6)]))
        self.assertTrue(all(value["ok"] for value in results))
        self.assertEqual(["test-one", "test-two", "test-three"] * 2, self.seen)

    def test_queued_request_uses_keys_current_at_dispatch(self):
        with patch("generation.time.sleep", side_effect=lambda delay: self.settings.save(dict(clear_key=True))):
            self.generate("waiting lesson")
        self.assertEqual(["test-two"], self.seen)

    def test_no_keys_stops_new_calls_but_cached_content_still_works(self):
        self.generate("saved lesson")
        self.settings.save(dict(clear_key=True, clear_key_2=True, clear_key_3=True))
        self.assertTrue(self.generate("saved lesson")["ok"])
        with self.assertRaisesRegex(ProviderError, "Add a Gemini API key"):
            self.generate("unfinished lesson")
        self.assertEqual(1, self.request.call_count)


if __name__ == "__main__":
    unittest.main()
