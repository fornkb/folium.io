import copy
import json
import unittest
from pathlib import Path

from core import Store, safe_text, grade, module_state, assessment_evidence
from generation import source_pages, validate_plan, Jobs, TEACHING_PLAN, ProviderError
from test_core import test_directory
from sample import SPECS, sample_package


class TeachingTests(unittest.TestCase):
    def test_outline_sampling_includes_all_files_independent_of_order(self):
        docs = [dict(id=str(i),name=f"Subject {i}.pdf",role="material",pages=[str(i)*3000 for _ in range(42)]) for i in range(8)]
        first = source_pages(docs)
        second = source_pages(list(reversed(docs)))
        self.assertEqual({d["id"] for d in docs}, {p["doc_id"] for p in first})
        self.assertEqual(first, second)
        self.assertLessEqual(sum(len(p["text"]) for p in first), 65000)
        self.assertTrue(all(any(p["doc_id"] == d["id"] and p["page"] == 42 for p in first) for d in docs))

    def test_unicode_repairs_keep_math_and_recover_pairs(self):
        self.assertEqual("α ⊗ |ψ⟩ 😀 �", safe_text("α ⊗ |ψ⟩ \ud83d\ude00 \ud83c"))
        self.assertEqual("a\nb", safe_text("a\x00\nb"))

    def test_existing_extraction_is_backed_up_before_repair(self):
        with test_directory() as folder:
            store = Store(folder)
            with store.db:
                store.db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",("a","b","broken.pdf","material",json.dumps(["x\ud83c"]),"digest"))
            store.close()
            store = Store(folder)
            self.assertEqual("x�", store.docs("b")[0]["pages"][0])
            self.assertEqual(1, len(list((Path(folder)/"backups").glob("*.db"))))
            store.close()

    def test_plan_cannot_omit_or_duplicate_required_topics(self):
        plan = dict(overview="Overview",objectives=["Apply ideas"],lessons=[dict(id="l1",title="First",topics=["A"],concepts=["A1"],gaps=[])])
        with self.assertRaisesRegex(ValueError,"omitted or duplicated"):
            validate_plan(plan,["A","B"])
        plan["lessons"].append(dict(id="l2",title="Second",topics=["B"],concepts=["B1"],gaps=[]))
        validate_plan(plan,["A","B"])
        plan["lessons"][1]["topics"].append("A")
        with self.assertRaises(ValueError):validate_plan(plan,["A","B"])

    def test_resume_retains_plan_and_completed_lesson(self):
        with test_directory() as folder:
            store = Store(folder)
            course = store.create("Resumption")
            root = Path(__file__).resolve().parents[1]
            doc = store.add_pdf(course["id"],"notes.pdf","material",(root/"sample_sources/Course-notes.pdf").read_bytes())
            course["modules"]=[dict(id="m1",title="Complexity",topics=["A","B"],prerequisites=[])]
            store.save(course)
            class Fake:
                calls = []
                fail = True
                def generate(self,prompt,schema,validator):
                    if schema == TEACHING_PLAN:
                        self.calls.append("plan")
                        return validator(dict(overview="Overview",objectives=["Apply"],lessons=[dict(id=f"l{i+1}",title=t,topics=[t],concepts=[t],gaps=[]) for i,t in enumerate(["A","B"])]))
                    topic = "A" if 'Lesson: A\n' in prompt else "B"
                    self.calls.append(topic)
                    if topic == "B" and self.fail:raise ProviderError("Quota")
                    pkg = sample_package(SPECS[0],doc["id"],1)
                    for q in pkg["questions"]:q["topic"]=topic
                    return validator(pkg)
            fake=Fake(); jobs=Jobs(store,fake)
            with self.assertRaises(ProviderError):jobs._packages(course["id"])
            self.assertIn("l1",store.course(course["id"])["modules"][0]["preparation"]["lessons"])
            fake.fail=False
            jobs._packages(course["id"])
            self.assertEqual(["plan","A","B","B"],fake.calls)
            module=store.course(course["id"])["modules"][0]
            self.assertEqual(2,len(module["package"]["coverage_map"]))
            self.assertEqual(len(module["package"]["questions"]),len({q["id"] for q in module["package"]["questions"]}))
            store.close()

    def test_repeated_bank_does_not_increase_unique_evidence(self):
        module=dict(topics=["A"],package=dict(questions=[dict(id=f"q{i}",type="objective",question=f"Question {i}",options=["a","b"],correct_index=0,solution="a",topic="A") for i in range(8)]))
        answers={q["id"]:0 for q in module["package"]["questions"]}
        grade(module,answers); result=grade(module,answers)
        self.assertEqual(0,result["new_questions"])
        self.assertEqual(8,assessment_evidence(module)["unique"])
        self.assertEqual("learning",module_state(module))
        with self.assertRaises(ValueError):grade(module,{"q0":0},["q0","q0"])
        self.assertEqual(1,grade(module,{"q0":0},["q0"])["total"])

    def test_mastery_requires_topic_coverage_and_first_encounter_evidence(self):
        module=dict(topics=["A","B"],package=dict(questions=[dict(id=f"q{i}",type="objective",question=f"Question {i}",options=["a","b"],correct_index=0,solution="a",topic="A" if i<6 else "B") for i in range(12)]))
        grade(module,{f"q{i}":0 for i in range(6)},[f"q{i}" for i in range(6)])
        self.assertEqual("learning",module_state(module))
        grade(module,{f"q{i}":0 for i in range(6,12)},[f"q{i}" for i in range(6,12)])
        self.assertEqual("mastered",module_state(module))
        module["package"]["questions"][0]["question"]="Revised question"
        self.assertEqual(0,assessment_evidence(module)["unique"])

    def test_course_extension_preserves_saved_packages_and_creates_backup(self):
        with test_directory() as folder:
            store=Store(folder); c=store.create("Extension")
            c["modules"]=[dict(id="m1",title="Saved",topics=["A"],prerequisites=[],package={"saved":True},notes="Keep")]
            store.save(c)
            result=store.extend(c["id"],[dict(id="m2",title="Missing",topics=["B"],prerequisites=["m1"])])
            self.assertEqual(c["modules"][0],result["modules"][0])
            self.assertEqual(1,len(list((Path(folder)/"backups").glob("*.zip"))))
            with self.assertRaises(ValueError):store.extend(c["id"],[dict(id="m1",title="Duplicate",topics=["C"],prerequisites=[])])
            store.close()
