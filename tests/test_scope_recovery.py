"""Optional quote failures cannot discard scope or force repeated paid calls."""
import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from configuration import Settings
from core import Store
from generation import Gemini, Jobs, SCOPE_BATCH
from scope import prepare_sources, validate_batch, coverage, validate_saved_scope, catalogue_record
from fixtures import scope_fixture, pdf_fixture
from test_core import test_directory
from test_scope import ScopeProvider


class ScopeRecoveryTests(unittest.TestCase):
    def batch(self):
        docs = [dict(id="native", name="Logic.pdf", role="material", digest="digest",
                     pages=["A proofis a sequence of sentences. Use p implies q.", "Another related concept without quotation issues."])]
        state, batches = prepare_sources(docs)
        batch = batches[0]
        value = scope_fixture("\n" + json.dumps(dict(segments=batch["segments"])))
        value["records"][0]["anchors"] = [
            dict(segment_index=0, quote="A proof is a sequence of sentences"),
            dict(segment_index=0, quote="Use p implies q.")]
        return state, batch, value

    def test_optional_unmatched_quote_is_omitted_and_visible_not_fuzzy_verified(self):
        state, batch, value = self.batch()
        result = validate_batch(value, batch, strict_anchors=False)
        self.assertEqual([dict(page=1, quote="Use p implies q.")], result["records"][0]["anchors"])
        self.assertIn("quotation could not be matched", result["records"][0]["anchor_warnings"][0]["reason"])
        self.assertIn("quotation could not be matched", catalogue_record(result["records"][0])["uncertainties"][0])
        result.update(doc_id=batch["doc_id"], manifest=[{k: s[k] for k in ("page", "start", "end")} for s in batch["segments"]])
        state["batches"][batch["id"]] = result
        self.assertEqual(1, len(coverage(state)["unresolved"]))
        self.assertEqual(1, coverage(state)["unresolved"][0]["page"])
        with self.assertRaisesRegex(ValueError, "original text"):
            validate_batch(value, batch)
        for quote in ("Use q implies p.", "Invented formula", "Use P implies Q."):
            bad = copy.deepcopy(value)
            bad["records"][0]["anchors"] = [dict(segment_index=0, quote=quote)]
            self.assertEqual([], validate_batch(bad, batch, strict_anchors=False)["records"][0]["anchors"])
        bad = copy.deepcopy(value)
        bad["records"][0]["segment_indexes"] = [999]
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_batch(bad, batch, strict_anchors=False)

    def test_complete_failed_response_recovers_after_restart_without_network(self):
        _, batch, value = self.batch()
        with test_directory() as folder, patch("configuration.environment_values", return_value={}):
            store = Store(folder)
            settings = Settings(folder, env_file=Path(folder) / "absent.env")
            settings.save(dict(api_key="synthetic-key"))
            raw = json.dumps(dict(candidates=[dict(finishReason="STOP", content=dict(parts=[dict(text=json.dumps(value))]))])).encode()
            with patch("generation.urllib.request.urlopen", return_value=io.BytesIO(raw)) as network, patch("generation.time.sleep"):
                with self.assertRaisesRegex(ValueError, "original text"):
                    Gemini(store, settings).generate("scope test", SCOPE_BATCH, lambda v: validate_batch(v, batch))
                self.assertEqual(1, network.call_count)
            store.close()
            store = Store(folder)
            provider = Gemini(store, settings)
            with patch("generation.urllib.request.urlopen", side_effect=AssertionError("Must reuse saved response")) as network:
                result = provider.generate("scope test", SCOPE_BATCH, lambda v: validate_batch(v, batch, strict_anchors=False))
                again = provider.generate("scope test", SCOPE_BATCH, lambda v: validate_batch(v, batch, strict_anchors=False))
                self.assertEqual(result, again)
                self.assertTrue(result["records"][0]["anchor_warnings"])
                self.assertEqual(0, network.call_count)
            store.close()

    def test_truncated_or_still_invalid_raw_response_requires_fresh_request(self):
        for finish_reason, response in (("MAX_TOKENS", {"ok": True}), ("STOP", {"ok": False})):
            with self.subTest(finish_reason=finish_reason), test_directory() as folder, patch("configuration.environment_values", return_value={}):
                store = Store(folder)
                settings = Settings(folder, env_file=Path(folder) / "absent.env")
                settings.save(dict(api_key="synthetic-key"))
                def validate(value):
                    if not value["ok"]:
                        raise ValueError("Unusable response")
                    return value
                def encoded(value, finish):
                    return json.dumps(dict(candidates=[dict(finishReason=finish, content=dict(parts=[dict(text=json.dumps(value))]))])).encode()
                with patch("generation.urllib.request.urlopen", side_effect=[io.BytesIO(encoded(response, finish_reason)), io.BytesIO(encoded({"ok": True}, "STOP"))]) as network, patch("generation.time.sleep"):
                    with self.assertRaises(ValueError):
                        Gemini(store, settings).generate("unfinished", {"type": "OBJECT"}, validate)
                    self.assertTrue(Gemini(store, settings).generate("unfinished", {"type": "OBJECT"}, validate)["ok"])
                    self.assertEqual(2, network.call_count)
                store.close()

    def test_discovery_saves_warning_and_backup_remains_strict_and_portable(self):
        class QuotedProvider(ScopeProvider):
            def generate(self, prompt, schema, validator):
                if schema == SCOPE_BATCH:
                    self.calls.append((schema, prompt))
                    value = scope_fixture(prompt)
                    value["records"][0]["uncertainties"] = ["Existing uncertainty " + str(i) for i in range(20)]
                    value["records"][0]["anchors"] = [dict(segment_index=0, quote="Unmatched optional quote " + str(i)) for i in range(6)]
                    return validator(value)
                return super().generate(prompt, schema, validator)
        with test_directory() as folder:
            store = Store(folder)
            course = store.create("Anchor recovery")
            store.add_pdf(course["id"], "notes.pdf", "material", pdf_fixture())
            fake = QuotedProvider()
            Jobs(store, fake)._outline(course["id"])
            saved = store.course(course["id"])
            self.assertEqual("outline", saved["status"])
            self.assertTrue(saved["scope"]["complete"])
            record = next(iter(saved["scope"]["batches"].values()))["records"][0]
            self.assertEqual([], record["anchors"])
            self.assertEqual(20, len(record["uncertainties"]))
            self.assertEqual(1, len(record["anchor_warnings"]))  # Same-page warnings deduplicate.
            restored = store.import_course(store.export(course["id"]))
            validate_saved_scope(restored["scope"], store.docs(restored["id"]))
            tampered = copy.deepcopy(restored["scope"])
            next(iter(tampered["batches"].values()))["records"][0]["anchors"] = [dict(page=1, quote="Invented quote")]
            with self.assertRaisesRegex(ValueError, "saved scope anchor"):
                validate_saved_scope(tampered, store.docs(restored["id"]))
            store.close()


if __name__ == "__main__":
    unittest.main()
