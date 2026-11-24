"""Validate offline archives against the bytes sent through the SDK."""

from io import BytesIO
from pathlib import Path
from shutil import which
from subprocess import run
from zipfile import ZipFile

import pytest
from click.testing import CliRunner

from hackerrank_cli import create_cli
from tests.test_cli import USAGE_ERROR, recording_transport


def _entries(contents: bytes) -> dict[str, tuple[bytes, int]]:
    """Read file contents and stored permissions from a project ZIP."""
    with ZipFile(file=BytesIO(initial_bytes=contents)) as archive:
        return {
            info.filename: (archive.read(name=info), info.external_attr >> 16)
            for info in archive.infolist()
        }


@pytest.mark.parametrize(argnames="single_file", argvalues=[False, True])
@pytest.mark.parametrize(argnames="stdout", argvalues=[False, True])
def test_export_matches_upload(
    tmp_path: Path, *, single_file: bool, stdout: bool
) -> None:
    """Export the same bytes and permissions as an upload, without a
    key.
    """
    source = tmp_path / "starter"
    source.mkdir()
    script = source / "run.sh"
    contents = b"#!/bin/sh\r\n# input-begin\r\n\x00\xff  \r\n"
    _ = script.write_bytes(data=contents)
    script.chmod(mode=0o755)
    if single_file:
        options = ["--file", str(object=script)]
    else:
        _ = (source / ".gitignore").write_text(data="ignored.txt\n")
        _ = (source / "ignored.txt").write_text(data="ignored")
        _ = (source / "metadata.yml").write_text(data="excluded")
        options = [
            "--directory",
            str(object=source),
            "--exclude",
            "metadata.yml",
            "--exclude",
            ".gitignore",
        ]
    destination = tmp_path / "starter.zip"
    output = "-" if stdout else str(object=destination)
    transport = recording_transport(status=200, failure=None)
    cli = create_cli(transport=transport)
    result = CliRunner().invoke(
        cli=cli,
        args=["questions", "archive", *options, "--output", output],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    assert transport.requests == []
    exported = result.stdout_bytes if stdout else destination.read_bytes()
    assert _entries(contents=exported) == {
        "run.sh": (contents, script.stat().st_mode)
    }
    uploaded = CliRunner().invoke(
        cli=cli,
        args=["questions", "upload", "123456", *options],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert uploaded.exit_code == 0, uploaded.output
    [(_, _, _, files)] = transport.requests
    assert files is not None
    assert _entries(contents=files["file"][1]) == _entries(contents=exported)


@pytest.mark.parametrize(
    argnames="options",
    argvalues=[
        [],
        ["--directory", ".", "--file", "example.py"],
        ["--file", "example.py", "--exclude", "*.zip"],
        ["--file", "example.py", "--git-index"],
    ],
)
def test_invalid_source_options(tmp_path: Path, options: list[str]) -> None:
    """Reject ambiguous sources before creating an output file."""
    output = tmp_path / "archive.zip"
    result = CliRunner().invoke(
        cli=create_cli(),
        args=[
            "questions",
            "archive",
            *options,
            "--output",
            str(object=output),
        ],
    )
    assert result.exit_code == USAGE_ERROR
    assert output.exists() is False


@pytest.mark.parametrize(argnames="existing", argvalues=[False, True])
def test_output_errors(tmp_path: Path, *, existing: bool) -> None:
    """Do not overwrite an existing file, and report missing parents."""
    source = tmp_path / "starter.py"
    _ = source.write_bytes(data=b"pass\n")
    output = source if existing else tmp_path / "missing" / "archive.zip"
    result = CliRunner().invoke(
        cli=create_cli(),
        args=[
            "questions",
            "archive",
            "--file",
            str(object=source),
            "--output",
            str(object=output),
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 1
    assert source.read_bytes() == b"pass\n"
    assert "Error:" in result.stderr


def test_preparation_failure(tmp_path: Path) -> None:
    """An empty selection leaves no archive behind."""
    source = tmp_path / "empty"
    source.mkdir()
    output = tmp_path / "archive.zip"
    result = CliRunner().invoke(
        cli=create_cli(),
        args=[
            "questions",
            "archive",
            "--directory",
            str(object=source),
            "--output",
            str(object=output),
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 1
    assert result.stderr == "Error: No files selected for upload.\n"
    assert output.exists() is False


def test_git_index_selection(tmp_path: Path) -> None:
    """Both commands retain ignored tracked files and apply exclusions."""
    git = which(cmd="git")
    assert git is not None
    root = tmp_path / "repository"
    root.mkdir()
    _ = run(args=[git, "init", "-q"], cwd=root, check=True)  # noqa: S603
    _ = (root / ".gitignore").write_text(data="*.db\n")
    source = root / "starter"
    source.mkdir()
    tracked = source / "tracked.db"
    _ = tracked.write_bytes(data=b"fixture")
    (source / "removed.db").touch()
    _ = run(  # noqa: S603
        args=[
            git,
            "add",
            "-f",
            "--",
            "starter/tracked.db",
            "starter/removed.db",
        ],
        cwd=root,
        check=True,
    )
    (source / "removed.db").unlink()
    (source / "untracked.db").touch()
    (source / "scratch.txt").touch()
    _ = (source / "solution.txt").write_text(data="solution")
    options = ["--directory", str(object=source), "--exclude", "scratch.txt"]
    transport = recording_transport(status=200, failure=None)
    cli = create_cli(transport=transport)
    runner = CliRunner()
    for flags, expected in [
        ([], {"solution.txt"}),
        (["--git-index"], {"solution.txt", "tracked.db"}),
    ]:
        archived = runner.invoke(
            cli=cli,
            args=["questions", "archive", *options, *flags, "--output", "-"],
            env={"HACKERRANK_API_TOKEN": None},
        )
        assert archived.exit_code == 0, archived.output
        assert set(_entries(contents=archived.stdout_bytes)) == expected
    uploaded = runner.invoke(
        cli=cli,
        args=["questions", "upload", "123456", *options, "--git-index"],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert uploaded.exit_code == 0, uploaded.output
    [(_, _, _, files)] = transport.requests
    assert files is not None
    assert _entries(contents=files["file"][1]) == {
        "solution.txt": (
            b"solution",
            (source / "solution.txt").stat().st_mode,
        ),
        "tracked.db": (b"fixture", tracked.stat().st_mode),
    }


@pytest.mark.parametrize(argnames="missing_git", argvalues=[False, True])
def test_git_index_requires_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, missing_git: bool
) -> None:
    """Fail before producing archive bytes if Git cannot enumerate
    files.
    """
    message = "requires Git" if missing_git else "in a Git checkout"
    if missing_git:
        monkeypatch.setenv(name="PATH", value=str(object=tmp_path))
    result = CliRunner().invoke(
        cli=create_cli(),
        args=[
            "questions",
            "archive",
            "--directory",
            str(object=tmp_path),
            "--git-index",
            "--output",
            "-",
        ],
    )
    assert result.exit_code == 1
    assert message in result.stderr
    assert result.stdout_bytes == b""
