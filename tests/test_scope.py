"""Scope coverage, bounded retrieval, durable stages, and portable source identity."""
import copy
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from core import Store
from generation import (Jobs, ProviderError, SCOPE_BATCH, SCOPE_MERGE, OUTLINE,
                        TEACHING_PLAN, SCOPED_TEACHING_PLAN, scoped_excerpts, Gemini, Settings, validate_plan)
from scope import (prepare_sources, validate_batch, records_for, review_outline,
                   ranges_for, coverage, validate_merge, catalogue, review_signature,
                   validate_saved_scope, identity, module_packet)
from fixtures import scope_fixture, pdf_fixture, lesson_fixture, TEST_MODULES
from test_core import test_directory


class ScopeProvider:
    def __init__(self, doc_id=None):
        self.calls = []
        self.fail_at = None
        self.doc_id = doc_id

    def generate(self, prompt, schema, validator):
        self.calls.append((schema, prompt))
        if len(self.calls) == self.fail_at:
            raise ProviderError("Quota pause")
        if schema == SCOPE_BATCH:
            return validator(scope_fixture(prompt))
        if schema == OUTLINE:
            records = json.loads(prompt.split("SCOPE CATALOGUE\n")[1])
            return validator(dict(description="Saved scope outline", modules=[dict(id="m1", title="Complexity", description="Growth rates",
                topics=["Topic A", "Topic B"], prerequisites=[], scope_ids=[r["id"] for r in records])], exclusions=[]))
        if schema in (TEACHING_PLAN, SCOPED_TEACHING_PLAN):
            ids = [r["id"] for r in json.loads(prompt.split("APPROVED SCOPE PACKET\n")[1])["records"]] if schema == SCOPED_TEACHING_PLAN else []
            return validator(dict(overview="Overview", objectives=["Compute growth"], lessons=[dict(id="l1", title="Growth",
                topics=["Topic A", "Topic B"], concepts=["Complexity"], gaps=[],scope_ids=ids)]))
        package = lesson_fixture(TEST_MODULES[0], self.doc_id, 1)
        for s in package["sections"]:
            s.update(sources=[], provenance="generated")
        return validator(package)


class ScopeTests(unittest.TestCase):
    def docs(self):
        return [dict(id="a", name="Notes.pdf", role="material", digest="digest-a", pages=[
            "Header\nUnique first content\nFooter", "Header\nSecond topic\nFooter",
            "Header\nThird topic\nFooter", "", "Damaged \ufffd symbol"])]

    def test_all_text_is_batched_without_tail_loss_or_oversize(self):
        docs = [dict(id="a", name="dense.pdf", role="material", digest="a", pages=["ABC "*18000 + "TAIL_TOPIC"])]
        state, batches = prepare_sources(docs, budget=1000)
        parts = [s for b in batches for s in b["segments"]]
        self.assertEqual(docs[0]["pages"][0], "".join(s["text"] for s in parts))
        self.assertTrue(all(sum(len(s["text"]) for s in b["segments"]) <= 1000 for b in batches))
        self.assertIn("TAIL_TOPIC", parts[-1]["text"])
        self.assertEqual(len(parts), state["inventory"][0]["pages"][0]["expected_segments"])

    def test_inventory_preserves_unresolved_pages_and_removes_only_boundary_boilerplate(self):
        state, batches = prepare_sources(self.docs())
        text = " ".join(s["text"] for b in batches for s in b["segments"])
        self.assertNotIn("Header", text)
        self.assertNotIn("Footer", text)
        self.assertIn("Third topic", text)
        self.assertEqual([4,5], [r["page"] for r in coverage(state)["unresolved"]])
        self.assertFalse(state["complete"])

    def test_duplicate_pages_share_processing_and_keep_all_locations(self):
        docs = [dict(id="a", name="dup.pdf", role="material", digest="a", pages=["Same text"]*3)]
        state, batches = prepare_sources(docs)
        self.assertEqual(1, len(batches[0]["segments"]))
        batch = batches[0]
        result = validate_batch(scope_fixture("\n"+json.dumps(dict(segments=batch["segments"]))), batch)
        result.update(doc_id="a", manifest=[{k:s[k] for k in ("page","start","end")} for s in batch["segments"]])
        state["batches"][batch["id"]] = result
        self.assertEqual([1,2,3], records_for(state)[0]["pages"])
        self.assertEqual(3, coverage(state)["processed_pages"])

    def test_partial_dense_page_is_not_reported_as_processed(self):
        docs=[dict(id="a", name="dense.pdf", role="material", digest="a", pages=["A"*3000])]
        state, batches=prepare_sources(docs,budget=1000)
        batch=batches[0]
        result=validate_batch(scope_fixture("\n"+json.dumps(dict(segments=batch["segments"]))),batch)
        result.update(doc_id="a",manifest=[{k:s[k] for k in ("page","start","end")} for s in batch["segments"]])
        state["batches"][batch["id"]]=result
        self.assertEqual(0,coverage(state)["processed_pages"])

    def test_scope_requires_a_decision_for_every_segment_and_real_quote(self):
        _, batches=prepare_sources(self.docs())
        batch=batches[0]
        value=scope_fixture("\n"+json.dumps(dict(segments=batch["segments"])))
        bad=copy.deepcopy(value);bad["segments"].pop()
        with self.assertRaisesRegex(ValueError,"omitted"):validate_batch(bad,batch)
        bad=copy.deepcopy(value);bad["records"][0]["anchors"]=[dict(segment_index=0,quote="Invented formula")]
        with self.assertRaisesRegex(ValueError,"original text"):validate_batch(bad,batch)
        bad=copy.deepcopy(value);bad["records"][0]["segment_indexes"]=[999]
        with self.assertRaisesRegex(ValueError,"outside"):validate_batch(bad,batch)

    def test_review_rejects_unmapped_records_and_out_of_bounds_ranges(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Review");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            Jobs(store,ScopeProvider())._outline(c["id"])
            c=store.course(c["id"]);modules=copy.deepcopy(c["modules"])
            modules[0]["source_ranges"][0]["end_page"]=999
            with self.assertRaisesRegex(ValueError,"actual"):review_outline(c,modules,[],store.docs(c["id"]))
            modules=copy.deepcopy(c["modules"]);modules[0]["scope_ids"]=[]
            with self.assertRaisesRegex(ValueError,"scope records"):review_outline(c,modules,[],store.docs(c["id"]))
            bad=copy.deepcopy(c["modules"]);bad[0]["scope_ids"].append("invented")
            with self.assertRaises(ValueError):review_outline(c,bad,[],store.docs(c["id"]))
            store.close()

    def test_bounded_retrieval_cannot_leak_other_modules_and_finds_page_tail(self):
        docs=[dict(id="a",name="A.pdf",role="material",pages=["Prefix "*2000+"Target notation here", "Target secret outside"]),
              dict(id="b",name="B.pdf",role="material",pages=["Target other PDF"])]
        module=dict(source_ranges=[dict(doc_id="a",start_page=1,end_page=1)])
        selected=scoped_excerpts(docs,module,"Target notation")
        self.assertTrue(selected)
        self.assertEqual({("a",1)}, {(p["doc_id"],p["page"]) for p in selected})
        self.assertIn("Target notation",selected[0]["text"])
        self.assertLessEqual(sum(len(p["text"]) for p in selected),12000)
        self.assertEqual([],scoped_excerpts(docs,module,"unmatched"))

    def test_scope_batches_resume_after_restart_and_partial_backup(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Resume");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            fake=ScopeProvider();fake.fail_at=2
            # Force one page per batch without altering source content or identity.
            native=prepare_sources
            with patch("generation.prepare_sources",side_effect=lambda docs:native(docs,budget=230)):
                with self.assertRaises(ProviderError):Jobs(store,fake)._outline(c["id"])
                self.assertEqual(1,len(store.course(c["id"])["scope"]["batches"]))
                first_prompt=fake.calls[0][1]
                store.close();store=Store(folder)
                fake.fail_at=None;Jobs(store,fake)._outline(c["id"])
                self.assertEqual(1,sum(prompt==first_prompt for _,prompt in fake.calls))
            self.assertEqual("outline",store.course(c["id"])["status"])
            store.close()

    def test_backup_round_trip_keeps_scope_ids_and_remaps_every_source(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Portable");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            Jobs(store,ScopeProvider())._outline(c["id"]);c=store.course(c["id"])
            c["scope_review"]=review_signature(c["modules"],[],c["scope"]["fingerprint"]);store.save(c)
            restored=store.import_course(store.export(c["id"]))
            new_doc=store.docs(restored["id"])[0]["id"]
            self.assertNotEqual(doc["id"],new_doc)
            self.assertEqual(c["modules"][0]["scope_ids"],restored["modules"][0]["scope_ids"])
            self.assertEqual(new_doc,restored["modules"][0]["source_ranges"][0]["doc_id"])
            self.assertEqual(new_doc,records_for(restored["scope"])[0]["doc_id"])
            validate_saved_scope(restored["scope"],store.docs(restored["id"]))
            twice=store.import_course(store.export(restored["id"]))
            self.assertTrue(twice["scope_review"])
            store.close()

    def test_backup_before_outline_can_resume_without_repeating_scope(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Partial");store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            fake=ScopeProvider();fake.fail_at=2
            with self.assertRaises(ProviderError):Jobs(store,fake)._outline(c["id"])
            restored=store.import_course(store.export(c["id"]))
            fresh=ScopeProvider();Jobs(store,fresh)._outline(restored["id"])
            self.assertEqual([OUTLINE],[schema for schema,_ in fresh.calls])
            store.close()

    def test_saved_scope_tampering_is_rejected_before_import_creates_course(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Tamper");store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            Jobs(store,ScopeProvider())._outline(c["id"])
            with zipfile.ZipFile(io.BytesIO(store.export(c["id"]))) as source:
                entries={name:source.read(name) for name in source.namelist()}
            value=json.loads(entries["folium.json"])
            next(iter(value["course"]["scope"]["batches"].values()))["records"][0]["pages"]=[999]
            entries["folium.json"]=json.dumps(value).encode();output=io.BytesIO()
            with zipfile.ZipFile(output,"w") as z:
                for name,data in entries.items():z.writestr(name,data)
            with self.assertRaises(ValueError):store.import_course(output.getvalue())
            self.assertEqual(1,len(store.courses()));store.close()

    def test_generated_teaching_works_without_support_citations(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Teach");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            fake=ScopeProvider(doc["id"]);jobs=Jobs(store,fake);jobs._outline(c["id"])
            c=store.course(c["id"])
            with self.assertRaisesRegex(ValueError,"Review and save"):jobs.start(c["id"],"generate")
            c["scope_review"]=review_signature(c["modules"],[],c["scope"]["fingerprint"]);store.save(c)
            jobs._packages(c["id"])
            pkg=store.course(c["id"])["modules"][0]["package"]
            self.assertEqual("approved_scope",pkg["teaching_mode"])
            self.assertTrue(all(s["provenance"]=="generated" and not s["sources"] for s in pkg["sections"]))
            plans=[p for schema,p in fake.calls if schema==SCOPED_TEACHING_PLAN]
            self.assertIn("APPROVED SCOPE PACKET",plans[0]);self.assertNotIn("[SOURCE",plans[0])
            before=len(fake.calls);jobs._packages(c["id"]);self.assertEqual(before,len(fake.calls))
            store.import_course(store.export(c["id"]));store.close()

    def test_merge_requires_exact_lineage_and_a_smaller_result(self):
        records=[dict(id=str(i),title="Topic "+str(i),subtopics=["Detail "*50],depth="Derive "*50,
                      methods=[],conventions=[],uncertainties=[],role="material") for i in range(3)]
        row=dict(title="Topics",subtopics=["Distinct topics"],depth="Derive",methods=[],conventions=[],uncertainties=[],record_ids=["0","1","2"])
        result=validate_merge(dict(records=[row]),records,"key")
        self.assertEqual(["0","1","2"],result[0]["leaf_ids"])
        row["record_ids"].pop()
        with self.assertRaisesRegex(ValueError,"omitted"):validate_merge(dict(records=[row]),records,"key")

    def test_hierarchical_outline_expands_leaf_ids_and_survives_backup(self):
        class LargeProvider(ScopeProvider):
            def generate(self,prompt,schema,validator):
                if schema==SCOPE_BATCH:
                    self.calls.append((schema,prompt));value=scope_fixture(prompt)
                    value["records"]=[dict(value["records"][0],title="Concept "+str(i),subtopics=["Distinct detail "*25],depth="Derive "*50) for i in range(8)]
                    return validator(value)
                if schema==SCOPE_MERGE:
                    self.calls.append((schema,prompt));records=json.loads(prompt.split("\n")[-1])
                    return validator(dict(records=[dict(title="Complexity",subtopics=["Topic A","Topic B"],depth="Compute growth",methods=[],conventions=[],uncertainties=[],record_ids=[r["id"] for r in records])]))
                return super().generate(prompt,schema,validator)
        with test_directory() as folder:
            store=Store(folder);c=store.create("Large scope");store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            fake=LargeProvider()
            with patch("generation.CATALOGUE_CHARS",900):Jobs(store,fake)._outline(c["id"])
            c=store.course(c["id"])
            self.assertEqual(8,len(c["modules"][0]["scope_ids"]))
            self.assertEqual(1,len(c["scope"]["merges"]))
            restored=store.import_course(store.export(c["id"]))
            self.assertEqual(c["modules"][0]["scope_ids"],restored["modules"][0]["scope_ids"])
            validate_saved_scope(restored["scope"],store.docs(restored["id"]));store.close()

    def test_scope_module_extension_preserves_saved_package_and_review(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Extend scope");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            fake=ScopeProvider(doc["id"]);jobs=Jobs(store,fake);jobs._outline(c["id"])
            c=store.course(c["id"]);c["scope_review"]=review_signature(c["modules"],[],c["scope"]["fingerprint"]);store.save(c);jobs._packages(c["id"])
            c=store.course(c["id"]);before=copy.deepcopy(c["modules"][0]["package"])
            added=dict(c["modules"][0]);added.pop("package");added.update(id="m2",title="Extra applications")
            c=store.extend(c["id"],[added])
            self.assertEqual(before,c["modules"][0]["package"])
            self.assertEqual(review_signature(c["modules"],[],c["scope"]["fingerprint"]),c["scope_review"])
            jobs._packages(c["id"])
            self.assertEqual(before,store.course(c["id"])["modules"][0]["package"])
            self.assertEqual(1,len(list((store.root/"backups").glob("*.zip"))))
            store.close()

    def test_raw_provider_response_is_saved_even_if_validation_fails(self):
        with test_directory() as folder:
            store=Store(folder);settings=Settings(folder);settings.save(dict(api_key="private-test-key"))
            response=json.dumps(dict(candidates=[dict(content=dict(parts=[dict(text='{"value": 1}')]))],usageMetadata=dict(promptTokenCount=11))).encode()
            with patch("urllib.request.urlopen",return_value=io.BytesIO(response)):
                with self.assertRaises(ValueError):Gemini(store,settings).generate("test",{},lambda v: (_ for _ in ()).throw(ValueError("bad")))
            rows=store.db.execute("SELECT key,data FROM cache").fetchall()
            self.assertEqual(1,len(rows));self.assertTrue(rows[0][0].startswith("raw:"))
            self.assertNotIn("private-test-key",rows[0][1])
            self.assertEqual(11,json.loads(rows[0][1])["usage"]["promptTokenCount"])
            store.close()

    def test_normalizing_validators_receive_original_response_on_cache_hit(self):
        with test_directory() as folder:
            store=Store(folder);settings=Settings(folder);settings.save(dict(api_key="private-test-key"))
            response=json.dumps(dict(candidates=[dict(content=dict(parts=[dict(text='{"value": 1}')]))])).encode()
            validator=lambda value:dict(normalized=value["value"]+1)
            provider=Gemini(store,settings)
            with patch("urllib.request.urlopen",return_value=io.BytesIO(response)) as network:
                first=provider.generate("normalize",{},validator)
                second=provider.generate("normalize",{},validator)
                self.assertEqual(first,second);self.assertEqual(1,network.call_count)
            store.close()

    def test_lesson_plan_must_cover_scope_and_packet_uses_assigned_records(self):
        plan=dict(overview="Overview",objectives=["Learn"],lessons=[dict(id="l1",title="Lesson",topics=["A"],concepts=["A"],gaps=[],scope_ids=["r1"])])
        with self.assertRaisesRegex(ValueError,"omitted approved"):validate_plan(plan,["A"],["r1","r2"])
        validate_plan(plan,["A"],["r1"])
        with test_directory() as folder:
            store=Store(folder);c=store.create("Packets");store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            Jobs(store,ScopeProvider())._outline(c["id"]);c=store.course(c["id"])
            batch=next(iter(c["scope"]["batches"].values()));extra=dict(batch["records"][0]);extra.update(id="different",title="Unrelated subject")
            batch["records"].append(extra);m=c["modules"][0];m["scope_ids"].append("different")
            packet=module_packet(c,m,[m["scope_ids"][0]])
            self.assertEqual(1,len(packet["records"]));self.assertNotIn("Unrelated subject",json.dumps(packet))
            store.close()

    def test_fabricated_source_quotation_pauses_without_losing_plan(self):
        class BadQuote(ScopeProvider):
            def generate(self,prompt,schema,validator):
                if schema not in (SCOPE_BATCH,OUTLINE,TEACHING_PLAN,SCOPED_TEACHING_PLAN,SCOPE_MERGE):
                    package=lesson_fixture(TEST_MODULES[0],self.doc_id,1)
                    for section in package["sections"]:section["provenance"]="source_excerpt"
                    package["sections"][0]["body"]="A fabricated quotation that is absent from the PDF."
                    return validator(package)
                return super().generate(prompt,schema,validator)
        with test_directory() as folder:
            store=Store(folder);c=store.create("Quotes");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            jobs=Jobs(store,BadQuote(doc["id"]));jobs._outline(c["id"])
            with self.assertRaisesRegex(ValueError,"match the supplied original"):jobs._packages(c["id"])
            m=store.course(c["id"])["modules"][0]
            self.assertIn("plan",m["preparation"]);self.assertNotIn("package",m)
            store.close()

    def test_original_quote_survives_backup_and_changed_wording_is_rejected(self):
        with test_directory() as folder:
            store=Store(folder);c=store.create("Original quote");doc=store.add_pdf(c["id"],"notes.pdf","material",pdf_fixture())
            module=copy.deepcopy(TEST_MODULES[0]);pkg=lesson_fixture(module,doc["id"],1)
            section=pkg["sections"][0];section.update(provenance="source_excerpt",body="Core concept")
            module["package"]=pkg;c.update(modules=[module],status="ready");store.save(c)
            store.import_course(store.export(c["id"]))
            section["body"]="Invented original wording";store.save(c)
            with self.assertRaisesRegex(ValueError,"does not match"):store.import_course(store.export(c["id"]))
            store.close()
