"""The job payload the API and the worker exchange.

They are separate processes, so anything that does not survive a JSON round trip is a run that silently
does the wrong thing on the other side -- most importantly the human feedback attached to a resume.
"""

from __future__ import annotations

import pytest

from meridian.graph.jobs import JobKind, RunJob
from meridian.schemas.enums import AgentName, FeedbackAction
from meridian.schemas.research import HumanFeedback


def test_start_job_round_trips() -> None:
    job = RunJob(kind=JobKind.START, session_id="run_abc")

    restored = RunJob.from_json(job.to_json())

    assert restored == job
    assert restored.feedback is None


def test_feedback_survives_the_round_trip() -> None:
    feedback = [
        HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD"),
        HumanFeedback(action=FeedbackAction.RERUN_AGENT, agent=AgentName.VALUATION),
        HumanFeedback(action=FeedbackAction.COMMENT, comment="check the margin trend"),
    ]
    job = RunJob(kind=JobKind.RESUME, session_id="run_abc", feedback=feedback)

    restored = RunJob.from_json(job.to_json())

    assert restored.kind is JobKind.RESUME
    assert restored.feedback is not None
    assert [f.action for f in restored.feedback] == [f.action for f in feedback]
    assert restored.feedback[0].ticker == "AMD"
    assert restored.feedback[1].agent is AgentName.VALUATION
    assert restored.feedback[2].comment == "check the margin trend"


def test_an_empty_feedback_list_is_not_confused_with_none() -> None:
    """`[]` means "approve with no extra work"; `None` means the job carries no feedback at all."""
    assert RunJob.from_json(RunJob(kind=JobKind.RESUME, session_id="r", feedback=[]).to_json()).feedback == []
    assert RunJob.from_json(RunJob(kind=JobKind.RESUME, session_id="r").to_json()).feedback is None


def test_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        RunJob.from_json('{"kind": "explode", "session_id": "run_abc"}')
