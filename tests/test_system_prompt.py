"""Set project AI prompts through the released SDK's HTTP transport."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from click.testing import CliRunner
from hackerrank.types import JSONValue

from hackerrank_cli import main
from tests.test_cli import USAGE_ERROR

_BASE = "https://www.hackerrank.com/x/api/v3/questions/123456"
_QUESTION: dict[str, JSONValue] = {
    "id": "123456",
    "type": "fullstack",
    "name": "Project",
    "internal_notes": "Keep notes",
    "languages": ["python"],
    "problem_statement": "Build it.",
    "recommended_duration": 60,
    "tags": ["backend"],
    "options": [],
    "answer": [],
}


@pytest.mark.parametrize(
    argnames="prompt",
    argvalues=["", "  Give hints.\r\nDo not solve.  ", "🐢" * 15_000],
    ids=["empty", "multiline", "unicode-limit"],
)
def test_prompt_update_preserves_metadata(tmp_path: Path, prompt: str) -> None:
    """Empty files clear prompts; exact text survives a full update."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_bytes(data=prompt.encode(encoding="utf-8"))
    with respx.mock(assert_all_called=True) as router:
        _ = router.get(url=_BASE).respond(status_code=200, json=_QUESTION)
        update = router.put(url=_BASE).respond(status_code=200, json=_QUESTION)
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        assert (
            result.output
            == "Set system prompt for HackerRank project question 123456\n"
        )
        call: object = update.calls.last
        assert isinstance(call, respx.models.Call)
        expected = {
            key: value for key, value in _QUESTION.items() if key != "id"
        }
        assert json.loads(s=call.request.content) == {
            **expected,
            "custom_system_prompt": prompt,
        }
        assert (
            call.request.headers["authorization"] == "Bearer synthetic-secret"
        )


@pytest.mark.parametrize(
    argnames=("contents", "message"),
    argvalues=[(b"\xff", "UTF-8"), (b"x" * 15_001, "15,000")],
    ids=["invalid-utf8", "overlong"],
)
def test_invalid_prompt_is_local(
    tmp_path: Path, contents: bytes, message: str
) -> None:
    """Validate before reading credentials or making a request."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_bytes(data=contents)
    with respx.mock(assert_all_mocked=True) as router:
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": ""},
        )
        assert result.exit_code != 0
        assert message in result.output
        assert len(router.calls) == 0


def test_prompt_dry_run(tmp_path: Path) -> None:
    """Dry runs do not need an API token or expose prompt contents."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Private instructions", encoding="utf-8")
    with respx.mock(assert_all_mocked=True) as router:
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
                "--dry-run",
            ],
            env={"HACKERRANK_API_TOKEN": ""},
        )
        assert result.exit_code == 0, result.output
        assert "Private instructions" not in result.output
        assert len(router.calls) == 0


def test_nonproject_question_is_not_updated(tmp_path: Path) -> None:
    """Other question types must not be mutated."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Hints", encoding="utf-8")
    with respx.mock(assert_all_mocked=True) as router:
        _ = router.get(url=_BASE).respond(
            status_code=200, json={**_QUESTION, "type": "code"}
        )
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert "project (fullstack)" in result.output
        assert len(router.calls) == 1


@pytest.mark.parametrize(argnames="status", argvalues=[403, 500])
def test_prompt_errors_omit_secrets(tmp_path: Path, status: int) -> None:
    """Failed writes are reported without API response data or retries."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Hints", encoding="utf-8")
    with respx.mock(assert_all_called=True) as router:
        _ = router.get(url=_BASE).respond(status_code=200, json=_QUESTION)
        update = router.put(url=_BASE).respond(
            status_code=status, json={"error": "synthetic-secret"}
        )
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert f"HTTP {status}" in result.output
        assert "synthetic-secret" not in result.output
        assert update.call_count == 1


@pytest.mark.parametrize(
    argnames="question_id", argvalues=["0", "invalid", "\uff11\uff12\uff13"]
)
def test_invalid_question_id(tmp_path: Path, question_id: str) -> None:
    """Invalid target IDs fail without a request."""
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Hints", encoding="utf-8")
    with respx.mock(assert_all_mocked=True) as router:
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                question_id,
                "--prompt-file",
                str(object=prompt_file),
            ],
        )
        assert result.exit_code == USAGE_ERROR
        assert "positive decimal integer" in result.output
        assert len(router.calls) == 0


@pytest.mark.parametrize(
    argnames="failure", argvalues=["transport", "response"]
)
def test_prompt_request_failure(tmp_path: Path, failure: str) -> None:
    """Network failures and invalid success responses have safe
    diagnostics.
    """
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Hints", encoding="utf-8")
    with respx.mock(assert_all_called=True) as router:
        route = router.get(url=_BASE)
        if failure == "transport":
            _ = route.mock(
                side_effect=httpx.ConnectError(message="synthetic-secret")
            )
        else:
            _ = route.respond(
                status_code=200, content=b"invalid synthetic-secret"
            )
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert "synthetic-secret" not in result.output
        assert route.call_count == 1


def test_sparse_question_metadata(tmp_path: Path) -> None:
    """Optional metadata can be absent from the read without breaking an
    update.
    """
    prompt_file = tmp_path / "prompt.txt"
    _ = prompt_file.write_text(data="Hints", encoding="utf-8")
    question = {"id": "123456", "type": "fullstack", "name": "Project"}
    with respx.mock(assert_all_called=True) as router:
        _ = router.get(url=_BASE).respond(status_code=200, json=question)
        update = router.put(url=_BASE).respond(status_code=200, json=question)
        result = CliRunner().invoke(
            cli=main,
            args=[
                "questions",
                "set-system-prompt",
                "123456",
                "--prompt-file",
                str(object=prompt_file),
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        call: object = update.calls.last
        assert isinstance(call, respx.models.Call)
        assert json.loads(s=call.request.content) == {
            "name": "Project",
            "type": "fullstack",
            "internal_notes": "",
            "problem_statement": "",
            "recommended_duration": 0,
            "languages": [],
            "tags": [],
            "options": [],
            "answer": [],
            "custom_system_prompt": "Hints",
        }
