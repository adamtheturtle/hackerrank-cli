"""Verify symlink and filesystem boundaries using real temporary trees."""

import os
import stat
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from click.testing import CliRunner

from hackerrank_cli import create_cli
from hackerrank_cli._sources import prepare_source, require_regular_file
from tests.test_cli import recording_transport, write_files


@pytest.mark.parametrize(
    argnames="kind", argvalues=["file", "directory", "broken", "ignore"]
)
@pytest.mark.parametrize(argnames="dry_run", argvalues=[True, False])
def test_selected_links_rejected(
    kind: str, tmp_path: Path, *, dry_run: bool
) -> None:
    """Selection never dereferences links, even during a dry run."""
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    if kind == "directory":
        outside.mkdir()
        _ = (outside / "secret").write_text(data="never copy")
    elif kind != "broken":
        _ = outside.write_text(data="never copy")
    link = source / (".gitignore" if kind == "ignore" else "link")
    link.symlink_to(target=outside, target_is_directory=kind == "directory")
    transport = recording_transport(status=200, failure=None)
    arguments = [
        "questions",
        "upload",
        "123456",
        "--directory",
        str(object=source),
    ]
    if dry_run:
        arguments.append("--dry-run")
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=arguments,
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 1
    assert "Symbolic links are not supported" in result.output
    assert transport.requests == []


def test_ignored_links_and_git_metadata(tmp_path: Path) -> None:
    """Pruned symlinks and Git metadata never reach the staged
    directory.
    """
    source = tmp_path / "source"
    write_files(
        root=source, files={".gitignore": b"ignored\n", "main.py": b"pass"}
    )
    outside = tmp_path / "outside"
    _ = outside.write_text(data="secret")
    (source / "ignored").symlink_to(target=outside)
    (source / "excluded").symlink_to(target=outside)
    (source / ".git").symlink_to(target=outside)
    with prepare_source(
        directory=source, file=None, excludes=("excluded",)
    ) as prepared:
        assert prepared.files == (".gitignore", "main.py")
        assert prepared.directory is not None
        assert tuple(
            path.name for path in sorted(prepared.directory.iterdir())
        ) == (".gitignore", "main.py")


@pytest.mark.parametrize(argnames="mode", argvalues=["directory", "file"])
def test_symlink_ancestor_rejected(mode: str, tmp_path: Path) -> None:
    """An ancestor symlink cannot bypass the source boundary."""
    actual = tmp_path / "actual"
    actual.mkdir()
    _ = (actual / "main.py").write_text(data="pass")
    alias = tmp_path / "alias"
    alias.symlink_to(target=actual, target_is_directory=True)
    directory = alias if mode == "directory" else None
    source_file = alias / "main.py" if mode == "file" else None
    with (
        pytest.raises(expected_exception=ValueError, match="Symbolic links"),
        prepare_source(directory=directory, file=source_file, excludes=()),
    ):
        pytest.fail(reason="Preparation must reject the ancestor link.")


def test_no_source() -> None:
    """The preparation API also rejects absent sources."""
    with (
        pytest.raises(expected_exception=ValueError, match="exactly one"),
        prepare_source(directory=None, file=None, excludes=()),
    ):
        pytest.fail(reason="Preparation must reject absent sources.")


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no POSIX FIFO"
)
def test_special_file_rejected(tmp_path: Path) -> None:
    """Reject pipes before copying, avoiding a blocking read."""
    os.mkfifo(path=tmp_path / "pipe")
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            "--directory",
            str(object=tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert "Only regular files are supported" in result.output
    assert transport.requests == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
@pytest.mark.parametrize(argnames="mode", argvalues=["directory", "file"])
def test_unreadable_file(mode: str, tmp_path: Path) -> None:
    """A real permissions failure prevents credentials and mutation."""
    source = tmp_path / "main.py"
    _ = source.write_text(data="pass")
    original = stat.S_IMODE(source.stat().st_mode)
    source.chmod(mode=0)
    try:
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
            ],
            env={"HACKERRANK_API_TOKEN": None},
        )
        assert result.exit_code == 1
        assert (
            result.output
            == "Error: Could not prepare upload files (PermissionError).\n"
        )
        assert transport.requests == []
    finally:
        source.chmod(mode=original)


def test_ancestor_and_deeper_negations(tmp_path: Path) -> None:
    """Deeper negations override root matches for nested uploads."""
    root = tmp_path / "repo"
    write_files(
        root=root,
        files={
            ".git/config": b"synthetic",
            ".gitignore": b"*.tmp\nignored/\n!ignored/\n",
            "project/.gitignore": b"!keep.tmp\n",
            "project/keep.tmp": b"keep",
            "project/drop.tmp": b"drop",
            "project/ignored/keep.py": b"pass",
        },
    )
    with prepare_source(
        directory=root / "project", file=None, excludes=()
    ) as source:
        assert source.files == (".gitignore", "ignored/keep.py", "keep.tmp")


def test_device_rejected() -> None:
    """Exercise the special-file boundary using the OS null device."""
    with pytest.raises(
        expected_exception=ValueError, match="Only regular files"
    ):
        require_regular_file(path=Path(os.devnull))


@pytest.mark.parametrize(
    argnames="upload_path", argvalues=["project", "project/nested"]
)
def test_ignored_upload_ancestor(upload_path: str, tmp_path: Path) -> None:
    """Nested upload roots cannot revive files below an ignored
    ancestor.
    """
    root = tmp_path / "repo"
    write_files(
        root=root,
        files={
            ".git/config": b"synthetic",
            ".gitignore": b"project/\n",
            "project/.gitignore": b"!nested/\n!main.py\n",
            "project/main.py": b"pass",
            "project/nested/main.py": b"pass",
        },
    )
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "upload",
            "123456",
            "--directory",
            str(object=root / upload_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert result.output == "Error: No files selected for upload.\n"
    assert transport.requests == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
@pytest.mark.parametrize(argnames="mode", argvalues=["directory", "file"])
def test_executable_mode_preserved(mode: str, tmp_path: Path) -> None:
    """Project archives retain executable bits for startup scripts."""
    source = tmp_path / "start.sh"
    _ = source.write_bytes(data=b"#!/bin/sh\nexit 0\n")
    source.chmod(mode=0o755)
    transport = recording_transport(status=200, failure=None)
    path = tmp_path if mode == "directory" else source
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=["questions", "upload", "123456", f"--{mode}", str(object=path)],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert result.exit_code == 0, result.output
    [(_, _, _, files)] = transport.requests
    assert files is not None
    with ZipFile(file=BytesIO(initial_bytes=files["file"][1])) as archive:
        expected_mode = 0o755
        assert (
            stat.S_IMODE(archive.getinfo(name="start.sh").external_attr >> 16)
            == expected_mode
        )
        assert archive.read(name="start.sh") == b"#!/bin/sh\nexit 0\n"


@pytest.mark.parametrize(argnames="marker", argvalues=[".git", ".GIT"])
@pytest.mark.parametrize(argnames="mode", argvalues=["directory", "file"])
def test_explicit_git_metadata_rejected(
    marker: str, mode: str, tmp_path: Path
) -> None:
    """An explicit source cannot bypass the Git metadata exclusion."""
    metadata = tmp_path / marker
    metadata.mkdir()
    source = metadata / "config"
    _ = source.write_text(data="synthetic private configuration")
    path = metadata if mode == "directory" else source
    transport = recording_transport(status=200, failure=None)
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
    )
    assert result.exit_code == 1
    assert "Git metadata cannot be uploaded" in result.output
    assert transport.requests == []
