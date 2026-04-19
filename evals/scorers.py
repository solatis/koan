# evals/scorers.py
# LLM-as-judge scorers for koan eval tasks.
#
# All three scorers use model_graded_qa, which takes a template string
# embedding the question/rubric. The "answer" field is the concatenated
# artifact content from state.output. PASS/FAIL is extracted from the
# model's response via the default grade_pattern ("PASS" / "FAIL").

from inspect_ai.scorer import Scorer, model_graded_qa


_PLAN_SPECIFICITY_TEMPLATE = """
You are evaluating a software engineering plan produced by an AI orchestrator.

Plan artifacts:
{answer}

Rubric:
Grade whether the plan references specific file paths and function names from
the actual codebase rather than vague descriptions.

Score PASS if the plan cites at least 5 specific file paths and at least 3
specific function names that would be found in the codebase.
Score FAIL if the plan uses only vague descriptions, generic module names,
or fewer than the required specific references.

Respond with exactly one word on the last line: PASS or FAIL.
"""


_QUESTION_QUALITY_TEMPLATE = """
You are evaluating the intake questions posed by an AI orchestrator during
a software planning session.

Session artifacts (look for any intake questions section):
{answer}

Rubric:
Grade whether the orchestrator surfaced targeted, non-obvious questions.

Score PASS if at least 2 questions address genuine ambiguities that are not
directly answerable from the task description alone -- for example: scope
boundaries, approach trade-offs, constraint verification, or integration risks.
Score FAIL if the questions are generic (e.g. "what is the deadline?"), redundant
with information already in the task, or derivable mechanically from the task text.

Respond with exactly one word on the last line: PASS or FAIL.
"""


_MEMORY_RELEVANCE_TEMPLATE = """
You are evaluating the memory entries captured by an AI orchestrator after
completing a software planning session.

Memory / curation artifacts:
{answer}

Rubric:
Grade whether the captured memory entries are substantive and task-specific.

Score PASS if at least one entry has type=decision or type=lesson and a body
that is specific to this particular task (not a restatement of general
engineering boilerplate or a copy of an existing invariant).
Score FAIL if all entries are structural or procedural repetitions of
pre-existing invariants, or if no decision/lesson entries were captured.

Respond with exactly one word on the last line: PASS or FAIL.
"""


def plan_specificity() -> Scorer:
    """Grade whether the plan cites specific file paths and function names."""
    return model_graded_qa(template=_PLAN_SPECIFICITY_TEMPLATE)


def question_quality() -> Scorer:
    """Grade whether the orchestrator asked targeted, non-obvious questions."""
    return model_graded_qa(template=_QUESTION_QUALITY_TEMPLATE)


def memory_relevance() -> Scorer:
    """Grade whether captured memory entries are specific to the task."""
    return model_graded_qa(template=_MEMORY_RELEVANCE_TEMPLATE)
