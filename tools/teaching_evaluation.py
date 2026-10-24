"""Export synthetic teaching prompts and a human rubric; never contacts Gemini."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generation import SCOPED_TEACHING
from prompts import VERSION, SYSTEM, TEACHING_SYSTEM, LESSON_INSTRUCTIONS


CASES = [
    dict(id="derivation", title="Sum of an arithmetic sequence", topics=["Arithmetic series"],
         concepts=["Derive the sum by pairing terms", "Use the formula in a worked example"],
         scope="Finite arithmetic sequences; algebra prerequisites; derive n(a1+an)/2 and explain why pairing works. No infinite series.",
         checks=["Explains the central pairing step", "Handles odd n or explains the reversed-sum method", "Works and checks a numerical example"]),
    dict(id="concept", title="Conditional probability", topics=["Conditional probability"],
         concepts=["Restricted sample spaces", "Interpret P(A|B)", "Distinguish P(A|B) from P(B|A)"],
         scope="Finite equally likely outcomes, basic fractions; connect counting to P(A intersection B)/P(B), P(B)>0. No measure theory.",
         checks=["Connects the denominator to the new sample space", "Uses one consistent concrete example", "Avoids reversing the condition"]),
    dict(id="procedure", title="Linear search", topics=["Linear search"],
         concepts=["Trace a search", "Explain termination and unsuccessful searches", "Compare best and worst case"],
         scope="Beginner programming; array indexing, loops, equality. Explain an unsorted-array search with a trace; no advanced algorithms.",
         checks=["Defines the index convention", "Shows both found and missing cases", "Explains why the worst case grows with array length"]),
    dict(id="sparse-notes", title="Eigenvectors", topics=["Eigenvectors and eigenvalues"],
         concepts=["Interpret Av=lambda v", "Find eigenvalues and nonzero eigenvectors of a 2x2 matrix"],
         scope="Notes contain only Av=lambda v and det(A-lambda I)=0. Reviewed scope permits explaining and solving real 2x2 examples; no spectral theorem proofs.",
         checks=["Teaches despite sparse notes", "Explains why v must be nonzero", "Verifies a computed pair by multiplication"]),
    dict(id="ambiguous-convention", title="Variance", topics=["Variance"],
         concepts=["Squared deviations from a mean", "Distinguish population variance and sample variance"],
         scope="Introductory statistics; notes use variance without specifying division by n or n-1. Teach the distinction and flag the unresolved course convention.",
         checks=["Does not silently choose the course convention", "States which definition each calculation uses", "Explains units and interprets the result"]),
]


def evaluation_suite():
    cases = []
    for case in CASES:
        lesson = dict(id="l1", title=case["title"], topics=case["topics"], concepts=case["concepts"], gaps=[])
        plan = dict(overview=case["scope"], objectives=case["concepts"], lessons=[lesson])
        prompt = LESSON_INSTRUCTIONS.format(module=case["title"], lesson=case["title"],
            topics=json.dumps(case["topics"]), concepts=json.dumps(case["concepts"]), gaps="[]",
            plan=json.dumps(plan), context="Synthetic evaluation course")
        prompt += "\nREVIEWED SCOPE\n" + case["scope"] + "\nNo original source excerpts are supplied; use generated provenance and sources=[]."
        cases.append(dict(id=case["id"], user_prompt=prompt, checks=case["checks"]))
    return dict(prompt_version=VERSION, system_instruction=SYSTEM+"\n\n"+TEACHING_SYSTEM,
        response_schema=SCOPED_TEACHING, cases=cases,
        rubric=dict(scale="Human score 0 (missing/wrong), 1 (partial), 2 (good); report factual errors separately.",
            criteria=["Scope and level", "Plain-language explanations", "Important reasoning steps",
                      "Useful worked examples", "Consistent notation", "Readable math and layout"],
            record=["Model", "Prompt version", "Case", "Request and token counts", "Failures", "Human scores and corrections"],
            limitation="No inference or quality measurement has been performed by exporting this suite. Structural checks do not establish teaching quality."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save the suite as JSON; otherwise write to stdout.")
    args = parser.parse_args()
    content = json.dumps(evaluation_suite(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"Saved {len(CASES)} synthetic evaluation prompts to {args.output}")
    else:
        print(content)
