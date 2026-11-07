"""Exercise the complete CLI API surface through the real SDK
transport.
"""

import json as jsonlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, override

import httpx
import pytest
import respx
from click.testing import CliRunner
from hackerrank.api import api_operations
from hackerrank.transports import Transport, TransportResponse
from hackerrank.types import JSONValue

from hackerrank_cli import create_cli


def test_template_list_and_selected_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default SDK transport preserves template identity and full JSON."""
    monkeypatch.setenv(name="HACKERRANK_API_TOKEN", value="synthetic")
    base = "https://www.hackerrank.com/x/api/v3/interview_templates"
    templates = [
        {"id": "101", "name": "First", "questions": [201]},
        {"id": "102", "name": "Selected", "questions": [202, 203]},
    ]
    page = {
        "data": templates,
        "next": f"{base}?offset=2&limit=2",
        "total": 3,
        "page_total": 2,
        "offset": 0,
        "extra": {"preserved": True},
    }
    cli = create_cli(transport=None)
    with respx.mock(assert_all_called=True) as router:
        _ = router.get(url=base, params={"limit": "2"}).respond(
            status_code=200, json=page
        )
        _ = router.get(url=f"{base}/102").respond(
            status_code=200, json=templates[1]
        )
        listed = CliRunner().invoke(
            cli=cli,
            args=[
                "api",
                "call",
                "api_list_all_interview_templates",
                "--query",
                '{"limit":2}',
            ],
            catch_exceptions=False,
        )
        assert listed.exit_code == 0
        data = jsonlib.loads(s=listed.output)["data"]
        assert data == page
        selected_id = data["data"][1]["id"]
        shown = CliRunner().invoke(
            cli=cli,
            args=[
                "api",
                "call",
                "api_show_interview_template",
                "--path",
                jsonlib.dumps(obj={"template_id": selected_id}),
            ],
            catch_exceptions=False,
        )
    assert shown.exit_code == 0
    assert jsonlib.loads(s=shown.output)["data"] == templates[1]


@dataclass
class APITransport(Transport):
    """Record complete requests without external API access."""

    status: int
    content: bytes
    fail: bool
    requests: list[
        tuple[
            str,
            str,
            dict[str, str],
            dict[str, str | int] | None,
            Mapping[str, JSONValue] | None,
        ]
    ]

    @override
    def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str | int] | None,
        json: Mapping[str, JSONValue] | None,
        files: Mapping[str, tuple[str, bytes | BinaryIO, str]] | None,
    ) -> TransportResponse:
        """Capture SDK encoding and return a synthetic response."""
        assert files is None
        self.requests.append((method, url, headers, params, json))
        if self.fail:
            raise httpx.ConnectError(message="synthetic-secret")
        return TransportResponse(
            status_code=self.status,
            headers={"retry-after": "180"},
            content=self.content,
        )


def test_every_documented_operation_is_runnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cover all 76 operations, including writes, ATS and separate-token
    SCIM.
    """
    monkeypatch.setenv(name="HACKERRANK_API_TOKEN", value="v3-synthetic")
    monkeypatch.setenv(
        name="HACKERRANK_SCIM_API_TOKEN", value="scim-synthetic"
    )
    body = tmp_path / "body.json"
    _ = body.write_text(data="{}", encoding="utf-8")
    transport = APITransport(
        status=200, content=b'{"ok":true}', fail=False, requests=[]
    )
    cli = create_cli(transport=transport)
    for operation in api_operations().values():
        path = {
            str(object=value["name"]): "1"
            for value in operation.parameters
            if value["location"] == "path"
        }
        query = {
            str(object=value["name"]): "1"
            for value in operation.parameters
            if value["location"] == "query" and value["required"] is True
        }
        args = [
            "api",
            "call",
            operation.id,
            "--path",
            jsonlib.dumps(obj=path),
            "--query",
            jsonlib.dumps(obj=query),
        ]
        if operation.body_required:
            args.extend(["--body-file", str(object=body)])
        result = CliRunner().invoke(cli=cli, args=args, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        request = transport.requests[-1]
        assert request[0] == operation.method
        assert request[1].startswith(
            "https://services.hackerrank.com/scim/v2/"
            if operation.scim
            else "https://www.hackerrank.com/x/api/v3/"
        )
        assert request[2]["Authorization"] == (
            "Bearer scim-synthetic"
            if operation.scim
            else "Bearer v3-synthetic"
        )
        assert jsonlib.loads(s=result.output)["data"] == {"ok": True}


def test_catalogue_help_and_schema_need_no_credentials() -> None:
    """Expose discoverable names and complete request schemas offline."""
    cli = create_cli(transport=None)
    listed = CliRunner().invoke(
        cli=cli, args=["api", "operations"], catch_exceptions=False
    )
    assert {
        value["operation"] for value in jsonlib.loads(s=listed.output)
    } == set(api_operations())
    described = CliRunner().invoke(
        cli=cli,
        args=["api", "describe", "api_create_user"],
        catch_exceptions=False,
    )
    description = jsonlib.loads(s=described.output)
    assert description["operation"]["body_required"] is True
    invalid = CliRunner().invoke(cli=cli, args=["api", "describe", "missing"])
    assert invalid.exit_code != 0
    for args in [
        ["api", "--help"],
        ["api", "call", "--help"],
        ["api", "describe", "--help"],
    ]:
        result = CliRunner().invoke(cli=cli, args=args, catch_exceptions=False)
        assert result.exit_code == 0


@pytest.mark.parametrize(
    argnames="args",
    argvalues=[
        ["api", "call", "missing"],
        ["api", "call", "api_list_all_tests", "--path", "broken"],
        ["api", "call", "api_list_all_tests", "--path", "[]"],
        ["api", "call", "api_retrieve_user", "--path", '{"id":[]}'],
        ["api", "call", "api_retrieve_user", "--path", '{"id":true}'],
        ["api", "call", "api_retrieve_user"],
        ["api", "call", "api_create_user"],
        ["api", "call", "api_list_all_tests", "--query", '{"bad":{}}'],
    ],
)
def test_invalid_inputs_fail_before_network(args: list[str]) -> None:
    """Malformed request inputs never issue a mutation or credential
    lookup.
    """
    transport = APITransport(
        status=200, content=b"{}", fail=False, requests=[]
    )
    result = CliRunner().invoke(cli=create_cli(transport=transport), args=args)
    assert result.exit_code != 0
    assert transport.requests == []


def test_dry_run_and_stdin_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate writes offline and preserve exact request body values."""
    monkeypatch.delenv(name="HACKERRANK_API_TOKEN", raising=False)
    transport = APITransport(status=204, content=b"", fail=False, requests=[])
    cli = create_cli(transport=transport)
    args = [
        "api",
        "call",
        "api_update_interviewer_note",
        "--path",
        '{"interview_id":"1"}',
        "--body-file",
        "-",
    ]
    dry = CliRunner().invoke(
        cli=cli,
        args=[*args, "--dry-run"],
        input='{"content":""}',
        catch_exceptions=False,
    )
    assert dry.exit_code == 0
    assert transport.requests == []
    monkeypatch.setenv(name="HACKERRANK_API_TOKEN", value="synthetic-secret")
    saved = CliRunner().invoke(
        cli=cli,
        args=args,
        input='{"content":"  line\\r\\n"}',
        catch_exceptions=False,
    )
    assert saved.exit_code == 0
    assert transport.requests[-1][4] == {"content": "  line\r\n"}
    assert jsonlib.loads(s=saved.output)["data"] is None
    invalid = CliRunner().invoke(cli=cli, args=args, input="broken")
    assert invalid.exit_code != 0


@pytest.mark.parametrize(argnames="credential", argvalues=["", "   "])
def test_missing_token(
    credential: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty and whitespace-only credentials fail without a request."""
    monkeypatch.setenv(name="HACKERRANK_API_TOKEN", value=credential)
    transport = APITransport(
        status=200, content=b"{}", fail=False, requests=[]
    )
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["api", "call", "api_list_all_tests"],
    )
    assert result.exit_code != 0
    assert transport.requests == []


@pytest.mark.parametrize(argnames="failure", argvalues=[False, True])
def test_api_failures_do_not_print_credentials(
    *, failure: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep API error bodies and transport exceptions out of command
    output.
    """
    monkeypatch.setenv(name="HACKERRANK_API_TOKEN", value="synthetic-secret")
    transport = APITransport(
        status=403,
        content=b'{"errors":["synthetic-secret"]}',
        fail=failure,
        requests=[],
    )
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["api", "call", "api_list_all_tests"],
    )
    assert result.exit_code != 0
    assert "synthetic-secret" not in result.output
