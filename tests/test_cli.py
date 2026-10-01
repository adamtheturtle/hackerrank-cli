"""Exercise CLI mutations through the real SDK's transport boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, override
from zipfile import ZipFile

import httpx
import httpx2
import pytest
from click.testing import CliRunner
from hackerrank.transports import Transport, TransportResponse
from hackerrank.types import JSONValue

from hackerrank_cli import create_cli
from hackerrank_cli._sources import prepare_source

USAGE_ERROR = 2


type Request = tuple[
    str,
    str,
    Mapping[str, JSONValue] | None,
    dict[str, tuple[str, bytes, str]] | None,
]


@dataclass
class RecordingTransport(Transport):
    """Record SDK requests without connecting to HackerRank."""

    status: int
    failure: httpx.TransportError | httpx2.TransportError | None
    requests: list[Request]
    metadata: dict[str, str]

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
        """Implement the SDK transport protocol without metadata
        updates.
        """
        assert headers["Authorization"] == "Bearer synthetic-secret"
        assert params is None
        copied_files: dict[str, tuple[str, bytes, str]] | None = None
        if files is not None:
            copied_files = {}
            for key, (name, content, mime) in files.items():
                assert isinstance(content, bytes)
                copied_files[key] = (name, content, mime)
        self.requests.append((method, url, json, copied_files))
        if self.failure is not None:
            raise self.failure
        return TransportResponse(
            status_code=self.status,
            headers={},
            content=b'{"message":"synthetic-secret"}',
        )


def recording_transport(
    *,
    status: int,
    failure: httpx.TransportError | httpx2.TransportError | None,
) -> RecordingTransport:
    """Create an isolated request log and synthetic question metadata."""
    return RecordingTransport(
        status=status,
        failure=failure,
        requests=[],
        metadata={
            "name": "Synthetic example",
            "problem_statement": "Keep these notes",
            "role_type": "backend",
            "internal_notes": "existing notes",
        },
    )


@pytest.mark.parametrize(
    argnames="arguments",
    argvalues=[
        ["--help"],
        ["questions", "--help"],
        ["questions", "upload", "--help"],
        ["--version"],
    ],
)
def test_help_version(arguments: list[str]) -> None:
    """Help and version never require authentication or a transport."""
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=arguments,
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 0
    assert result.output != ""
    assert transport.requests == []


@pytest.mark.parametrize(
    argnames="arguments",
    argvalues=[
        [],
        ["--directory", ".", "--file", "example.py"],
        ["--file", "example.py", "--exclude", "*.zip"],
    ],
)
def test_source_parsing(arguments: list[str]) -> None:
    """Exactly one source is required and exclusions apply to
    directories.
    """
    result = CliRunner().invoke(
        cli=create_cli(), args=["questions", "upload", "123456", *arguments]
    )
    assert result.exit_code == USAGE_ERROR
    assert "Error:" in result.output


@pytest.mark.parametrize(
    argnames="question_id",
    argvalues=["0", "-1", "../123", "\uff11\uff12\uff13", "123?x", "abc", " "],
)
def test_invalid_id(question_id: str, tmp_path: Path) -> None:
    """Reject malformed IDs before any transport call."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass\n")
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "--file",
            str(object=source),
            "--",
            question_id,
        ],
    )
    assert result.exit_code == USAGE_ERROR
    assert "positive decimal integer" in result.output
    assert transport.requests == []


@pytest.mark.parametrize(
    argnames="contents",
    argvalues=[
        "",
        "\ufeff# input-begin\r\n  pass  \r\n# input-end\r\n\r\n",
        "\n\nπ = 3  \n\n",
        "pass",
    ],
)
def test_exact_file_and_metadata(contents: str, tmp_path: Path) -> None:
    """Send exact text in a project ZIP and preserve all metadata."""
    source = tmp_path / "starter.py"
    _ = source.write_bytes(data=contents.encode(encoding="utf-8"))
    transport = recording_transport(status=200, failure=None)
    before = dict(transport.metadata)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", "--file", str(object=source)],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 0, result.output
    [(method, url, json, files)] = transport.requests
    assert (method, url, json) == (
        "POST",
        "https://www.hackerrank.com/x/api/v3/questions/123456/upload_project_zip",
        None,
    )
    assert files is not None
    assert tuple(files) == ("file",)
    filename, contents_bytes, mime = files["file"]
    assert (filename, mime) == ("project.zip", "application/zip")
    with ZipFile(file=BytesIO(initial_bytes=contents_bytes)) as archive:
        assert {n: archive.read(name=n) for n in archive.namelist()} == {
            "starter.py": contents.encode(encoding="utf-8")
        }
    assert transport.metadata == before
    assert result.output == "Updated HackerRank project question 123456\n"


@pytest.mark.parametrize(argnames="key", argvalues=[None, "", "   "])
def test_missing_key(key: str | None, tmp_path: Path) -> None:
    """Unset and empty credentials fail without SDK requests."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass\n")
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", "--file", str(object=source)],
        env={"HACKERRANK_API_TOKEN": key},
    )
    assert result.exit_code == 1
    assert "HACKERRANK_API_TOKEN is missing or empty" in result.output
    assert transport.requests == []


@pytest.mark.parametrize(
    argnames="status", argvalues=[400, 401, 403, 404, 429, 500, 502, 503, 504]
)
def test_api_errors_without_retries(status: int, tmp_path: Path) -> None:
    """Expose safe status messages, with exactly the SDK's one request."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass\n")
    transport = recording_transport(status=status, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", "--file", str(object=source)],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 1
    assert (
        result.output
        == f"Error: HackerRank rejected the upload (HTTP {status}).\n"
    )
    assert len(transport.requests) == 1


def test_network_failure(tmp_path: Path) -> None:
    """Transport diagnostics cannot disclose credentials."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass\n")
    transport = recording_transport(
        status=200, failure=httpx.ConnectError(message="synthetic-secret")
    )
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", "--file", str(object=source)],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 1
    assert (
        result.output == "Error: Could not reach HackerRank. "
        "Check your network connection.\n"
    )
    assert len(transport.requests) == 1


def write_files(root: Path, files: dict[str, bytes]) -> None:
    """Create a synthetic source tree."""
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(data=contents)


def test_directory_zip_and_metadata(tmp_path: Path) -> None:
    """Inspect the prepared ZIP sent through the real SDK."""
    write_files(
        root=tmp_path,
        files={
            "main.py": b"pass\r\n",
            "sub/data.bin": b"\x00\xff",
            "bundle.zip": b"zip",
            ".git/config": b"private",
            "sub/.GIT/config": b"private",
        },
    )
    transport = recording_transport(status=200, failure=None)
    before = dict(transport.metadata)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            "--directory",
            str(object=tmp_path),
        ],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 0, result.output
    [(method, url, data, files)] = transport.requests
    assert (method, url, data) == (
        "POST",
        "https://www.hackerrank.com/x/api/v3/questions/123456/upload_project_zip",
        None,
    )
    assert files is not None
    [(name, contents, mime)] = files.values()
    assert (name, mime) == ("project.zip", "application/zip")
    with ZipFile(file=BytesIO(initial_bytes=contents)) as archive:
        assert {
            name: archive.read(name=name) for name in archive.namelist()
        } == {
            "main.py": b"pass\r\n",
            "sub/data.bin": b"\x00\xff",
            "bundle.zip": b"zip",
        }
    assert transport.metadata == before


@pytest.mark.parametrize(
    argnames="git_marker", argvalues=["directory", "file", "absent"]
)
def test_nested_ignore_precedence(git_marker: str, tmp_path: Path) -> None:
    """Check root and nested rules, pruning, and final excludes."""
    root = tmp_path / "repo"
    project = root / "project"
    write_files(root=root, files={".gitignore": b"project/root-ignored.py\n"})
    if git_marker == "directory":
        (root / ".git").mkdir()
    elif git_marker == "file":
        _ = (root / ".git").write_text(data="gitdir: elsewhere\n")
    write_files(
        root=project,
        files={
            ".gitignore": (
                b"*.tmp\n!keep.tmp\n/anchored.py\npruned/\n*.zip\n!keep.zip\n"
            ),
            "root-ignored.py": b"root",
            "main.py": b"main",
            "drop.tmp": b"drop",
            "keep.tmp": b"keep",
            "anchored.py": b"anchor",
            "keep.zip": b"zip",
            "nested/.gitignore": b"!drop.tmp\nkeep.tmp\n",
            "nested/drop.tmp": b"nested",
            "nested/keep.tmp": b"drop",
            "nested/anchored.py": b"nested anchor",
            "pruned/.gitignore": b"!keep.py\n",
            "pruned/keep.py": b"pruned",
            "nested/.git": b"metadata",
        },
    )
    with prepare_source(
        directory=project, file=None, excludes=("*.zip",)
    ) as source:
        expected: tuple[str, ...] = (
            ".gitignore",
            "keep.tmp",
            "main.py",
            "nested/.gitignore",
            "nested/anchored.py",
            "nested/drop.tmp",
        )
        if git_marker == "absent":
            expected = (*expected, "root-ignored.py")
        assert source.files == expected
        assert source.directory is not None
        assert tuple(
            sorted(
                path.relative_to(source.directory).as_posix()
                for path in source.directory.rglob(pattern="*")
                if path.is_file()
            )
        ) == tuple(sorted(expected))
    assert not source.directory.exists()


def test_final_exclusion_negations(tmp_path: Path) -> None:
    """Final patterns undo only their own exclusions, never Git
    ignores.
    """
    write_files(
        root=tmp_path,
        files={
            ".gitignore": b"ignored.zip\n",
            "ignored.zip": b"ignore",
            "keep.zip": b"keep",
            "drop.zip": b"drop",
            ".git": b"gitdir: example",
        },
    )
    with prepare_source(
        directory=tmp_path,
        file=None,
        excludes=("*.zip", "!keep.zip", "!ignored.zip", "!.git"),
    ) as source:
        assert source.files == (".gitignore", "keep.zip")


@pytest.mark.parametrize(argnames="mode", argvalues=["file", "directory"])
def test_offline_dry_run(mode: str, tmp_path: Path) -> None:
    """Select and read sources with no key or transport request."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass\n")
    transport = recording_transport(status=200, failure=None)
    path = tmp_path if mode == "directory" else source
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            f"--{mode}",
            str(object=path),
            "--dry-run",
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    selected = "starter.py" if mode == "directory" else str(object=source)
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"Would update HackerRank project question 123456\n  {selected}\n"
    )
    assert transport.requests == []


@pytest.mark.parametrize(
    argnames=("mode", "kind"),
    argvalues=[
        (mode, kind)
        for mode in ("file", "directory")
        for kind in (
            "missing",
            "wrong-kind",
            "invalid-utf8",
            "empty",
            "symlink",
        )
        if (mode, kind) not in {("file", "empty"), ("file", "invalid-utf8")}
    ],
)
def test_input_errors(mode: str, kind: str, tmp_path: Path) -> None:
    """Invalid inputs fail before authentication or mutation."""
    source = tmp_path / "source"
    if kind != "missing":
        if mode == "directory":
            source.mkdir()
            if kind == "invalid-utf8":
                _ = (source / ".gitignore").write_bytes(data=b"\xff")
        else:
            _ = source.write_bytes(
                data=b"\xff" if kind == "invalid-utf8" else b"pass"
            )
    if kind == "wrong-kind":
        source = tmp_path if mode == "file" else tmp_path / "file"
        if mode == "directory":
            _ = source.write_text(data="pass")
    if kind == "symlink":
        target = source
        source = tmp_path / "link"
        source.symlink_to(
            target=target, target_is_directory=mode == "directory"
        )
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            f"--{mode}",
            str(object=source),
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "HACKERRANK_API_TOKEN" not in result.output
    assert transport.requests == []


@pytest.mark.parametrize(argnames="retries", argvalues=["-1", "bad"])
def test_invalid_retries(retries: str, tmp_path: Path) -> None:
    """Reject unsupported retry counts before any SDK request."""
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass")
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            "--file",
            str(object=source),
            "--retries",
            retries,
        ],
    )
    assert result.exit_code == USAGE_ERROR
    assert transport.requests == []


def test_httpx2_network_failure(tmp_path: Path) -> None:
    """Supported SDK transports handle either HTTP client's error
    family.
    """
    source = tmp_path / "starter.py"
    _ = source.write_text(data="pass")
    transport = recording_transport(
        status=200, failure=httpx2.ConnectError(message="synthetic-secret")
    )
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", "--file", str(object=source)],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 1
    assert result.output == (
        "Error: Could not reach HackerRank. Check your network connection.\n"
    )
    assert len(transport.requests) == 1
