"""Exercise the released SDK's default HTTPX transport entirely offline."""

from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
import respx
from click.testing import CliRunner
from respx.models import AllMockedAssertionError

from hackerrank_cli import main
from tests.test_cli import write_files

_TWO_ATTEMPTS = 2
_THREE_ATTEMPTS = 3

_URL = (
    "https://www.hackerrank.com/x/api/v3/questions/123456/upload_project_zip"
)


def _archive_bytes(request: httpx.Request) -> bytes:
    """Validate SDK/HTTPX multipart serialization and return ZIP bytes."""
    assert request.method == "POST"
    assert str(request.url) == _URL
    assert request.headers["authorization"] == "Bearer synthetic-secret"
    content_type = request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("ascii")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + request.content,
    )
    assert message.is_multipart()
    [part] = message.iter_parts()
    assert part.get_param("name", header="content-disposition") == "file"
    assert part.get_filename() == "project.zip"
    assert part.get_content_type() == "application/zip"
    payload = part.get_payload(decode=True)
    assert isinstance(payload, bytes)
    return payload


@pytest.mark.parametrize(
    "contents",
    [b"", b"\xef\xbb\xbf# marker\r\npass  \r\n\r\n", b"\x00\xff", b"pass"],
)
def test_exact_file_over_httpx(contents: bytes, tmp_path: Path) -> None:
    """Binary and text files survive both archive and multipart encoding."""
    source = tmp_path / "starter.py"
    _ = source.write_bytes(contents)

    def upload(request: httpx.Request) -> httpx.Response:
        """Check the only request field and the complete archive."""
        with ZipFile(BytesIO(_archive_bytes(request))) as archive:
            assert {n: archive.read(n) for n in archive.namelist()} == {
                "starter.py": contents
            }
        return httpx.Response(HTTPStatus.OK, json={"file_path": "project.zip"})

    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).mock(side_effect=upload)
        result = CliRunner().invoke(
            main,
            ["questions", "upload", "123456", "--file", str(source)],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        assert result.output == "Updated HackerRank project question 123456\n"
        assert route.call_count == 1
        assert len(router.calls) == 1


def test_directory_and_metadata_over_httpx(tmp_path: Path) -> None:
    """Only a file part is sent; title and other metadata remain untouched."""
    source = tmp_path / "project"
    write_files(
        source,
        {
            "main.py": b"pass\r\n",
            "sub/data.bin": b"\x00\xff",
            "bundle.zip": b"skip",
            ".git/config": b"private",
        },
    )
    metadata = {
        "name": "Synthetic title",
        "problem_statement": "Existing notes",
        "environment_id": 92,
        "configuration": {"run_command": "python main.py"},
    }
    state = {**metadata, "files": {"old.py": b"old"}}
    uploaded = {"main.py": b"pass\r\n", "sub/data.bin": b"\x00\xff"}

    def upload(request: httpx.Request) -> httpx.Response:
        """Apply only the archive payload to the synthetic question state."""
        with ZipFile(BytesIO(_archive_bytes(request))) as archive:
            state["files"] = {n: archive.read(n) for n in archive.namelist()}
        return httpx.Response(HTTPStatus.OK, json={"file_path": "project.zip"})

    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).mock(side_effect=upload)
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                "--directory",
                str(source),
                "--exclude",
                "*.zip",
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        assert route.call_count == 1
        assert len(router.calls) == 1
    assert state == {**metadata, "files": uploaded}


@pytest.mark.parametrize(
    "status",
    [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND],
)
def test_auth_and_nonretryable_failure(
    status: HTTPStatus, tmp_path: Path
) -> None:
    """Permanent errors never retry, even with retries enabled."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).respond(
            status.value, json={"message": "synthetic-secret"}
        )
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                "--file",
                str(source),
                "--retries",
                "2",
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert result.output == (
            f"Error: HackerRank rejected the upload (HTTP {status.value}).\n"
        )
        assert route.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_sdk_retry_identical_archive(status: int, tmp_path: Path) -> None:
    """SDK retries preserve the complete ZIP without re-reading sources."""
    source = tmp_path / "starter.py"
    _ = source.write_bytes(b"pass\r\n")
    archives: list[bytes] = []

    def upload(request: httpx.Request) -> httpx.Response:
        """Record each payload, fail once, then accept the retry."""
        archives.append(_archive_bytes(request))
        if len(archives) == 1:
            _ = source.write_bytes(b"changed after preparation")
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(HTTPStatus.OK, json={})

    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).mock(side_effect=upload)
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                "--file",
                str(source),
                "--retries",
                "1",
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        assert route.call_count == _TWO_ATTEMPTS
    first, second = archives
    assert first == second
    with ZipFile(BytesIO(second)) as archive:
        assert archive.read("starter.py") == b"pass\r\n"


def test_retry_exhaustion(tmp_path: Path) -> None:
    """The CLI respects the SDK attempt limit and reports a safe status."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).respond(
            HTTPStatus.SERVICE_UNAVAILABLE,
            headers={"Retry-After": "0"},
            json={"message": "synthetic-secret"},
        )
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                "--file",
                str(source),
                "--retries",
                "2",
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert result.output == (
            "Error: HackerRank rejected the upload (HTTP 503).\n"
        )
        assert route.call_count == _THREE_ATTEMPTS


@pytest.mark.parametrize("content", [b"not JSON synthetic-secret", b"null"])
def test_invalid_response(content: bytes, tmp_path: Path) -> None:
    """Invalid success bodies are handled without printing response data."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).respond(HTTPStatus.OK, content=content)
        result = CliRunner().invoke(
            main,
            ["questions", "upload", "123456", "--file", str(source)],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert result.output == (
            "Error: HackerRank returned an invalid response. The upload may "
            "have succeeded; check the question before trying again.\n"
        )
        assert route.call_count == 1


@pytest.mark.parametrize("mode", ["directory", "file"])
def test_offline_dry_run(mode: str, tmp_path: Path) -> None:
    """No routes and no token are needed for a dry run."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    path = tmp_path if mode == "directory" else source
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                f"--{mode}",
                str(path),
                "--dry-run",
            ],
            env={"HACKERRANK_API_TOKEN": None},
        )
        assert result.exit_code == 0, result.output
        assert len(router.calls) == 0


def test_http_mock_fails_closed() -> None:
    """Unregistered requests fail instead of reaching the real service."""
    with (
        respx.mock(assert_all_mocked=True, assert_all_called=False),
        pytest.raises(AllMockedAssertionError),
    ):
        _ = httpx.get("https://www.hackerrank.com/unexpected")


def test_network_retry_over_httpx(tmp_path: Path) -> None:
    """SDK network retries remain enabled without replacing retry methods."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    attempts: list[bytes] = []

    def upload(request: httpx.Request) -> httpx.Response:
        """Time out once, then accept the identical retried archive."""
        attempts.append(_archive_bytes(request))
        if len(attempts) == 1:
            msg = "synthetic-secret"
            raise httpx.ReadTimeout(msg)
        return httpx.Response(HTTPStatus.OK, json={})

    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).mock(side_effect=upload)
        result = CliRunner().invoke(
            main,
            [
                "questions",
                "upload",
                "123456",
                "--file",
                str(source),
                "--retries",
                "1",
            ],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 0, result.output
        assert result.output == "Updated HackerRank project question 123456\n"
        assert route.call_count == _TWO_ATTEMPTS
    first, second = attempts
    assert first == second


def test_timeout_over_default_httpx(tmp_path: Path) -> None:
    """Default retries stay disabled and network exception text is hidden."""
    source = tmp_path / "starter.py"
    _ = source.write_text("pass")
    with respx.mock(assert_all_mocked=True) as router:
        route = router.post(_URL).mock(
            side_effect=httpx.ReadTimeout("synthetic-secret")
        )
        result = CliRunner().invoke(
            main,
            ["questions", "upload", "123456", "--file", str(source)],
            env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
        )
        assert result.exit_code == 1
        assert result.output == (
            "Error: Could not reach HackerRank. "
            "Check your network connection.\n"
        )
        assert route.call_count == 1
