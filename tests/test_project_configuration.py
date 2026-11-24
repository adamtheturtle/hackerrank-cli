"""Native configuration is shared by archive exports and uploads."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from click.testing import CliRunner

from hackerrank_cli import create_cli
from tests.test_cli import recording_transport

_NATIVE = (
    b"version: 1.0\nconfiguration:\n"
    b"  has_webserver: false\n  future_setting: keep\n"
)


@pytest.mark.parametrize(
    argnames="contents",
    argvalues=[
        b"\xff",
        b"[broken",
        b"null",
        b"[]",
        b"version: true\nconfiguration: {}",
        b"version: 2\nconfiguration: {}",
        b"version: 1\nconfiguration: []",
        b"version: 1",
        b"configuration: {}",
    ],
)
def test_invalid_configuration_is_local(
    tmp_path: Path, contents: bytes
) -> None:
    """Malformed native documents fail without credentials or an output
    ZIP.
    """
    source = tmp_path / "solution.py"
    _ = source.write_text(data="pass")
    config = tmp_path / "configuration.yml"
    _ = config.write_bytes(data=contents)
    destination = tmp_path / "project.zip"
    transport = recording_transport(status=200, failure=None)
    result = CliRunner().invoke(
        cli=create_cli(transport=transport),
        args=[
            "questions",
            "archive",
            "--file",
            str(object=source),
            "--configuration-file",
            str(object=config),
            "--output",
            str(object=destination),
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 1
    assert "Project configuration" in result.stderr
    assert not destination.exists()
    assert transport.requests == []


@pytest.mark.parametrize(argnames="single_file", argvalues=[False, True])
@pytest.mark.parametrize(argnames="existing", argvalues=[False, True])
def test_export_upload_and_dry_run(
    tmp_path: Path, *, single_file: bool, existing: bool
) -> None:
    """Exports and uploads contain the same configured project files."""
    source = tmp_path / "source"
    source.mkdir()
    script = source / "solution.py"
    _ = script.write_bytes(data=b"pass\n")
    if existing:
        _ = (source / "hackerrank.yml").write_bytes(data=b"old")
    config = tmp_path / "native.yml"
    _ = config.write_bytes(data=_NATIVE)
    options = [
        "--file" if single_file else "--directory",
        str(object=script if single_file else source),
        "--configuration-file",
        str(object=config),
    ]
    destination = tmp_path / "project.zip"
    transport = recording_transport(status=200, failure=None)
    cli = create_cli(transport=transport)
    runner = CliRunner()
    result = runner.invoke(
        cli=cli,
        args=[
            "questions",
            "archive",
            *options,
            "--output",
            str(object=destination),
        ],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert result.exit_code == 0, result.output
    dry_run = runner.invoke(
        cli=cli,
        args=["questions", "upload", "123456", *options, "--dry-run"],
        env={"HACKERRANK_API_TOKEN": None},
    )
    assert dry_run.exit_code == 0, dry_run.output
    assert dry_run.output.count("hackerrank.yml") == 1
    assert transport.requests == []
    uploaded = runner.invoke(
        cli=cli,
        args=["questions", "upload", "123456", *options],
        env={"HACKERRANK_API_TOKEN": "synthetic-secret"},
    )
    assert uploaded.exit_code == 0, uploaded.output
    [(_, _, _, files)] = transport.requests
    assert files is not None
    with (
        ZipFile(
            file=BytesIO(initial_bytes=destination.read_bytes())
        ) as exported,
        ZipFile(file=BytesIO(initial_bytes=files["file"][1])) as sent,
    ):
        expected = {"solution.py": b"pass\n", "hackerrank.yml": _NATIVE}
        assert {
            name: exported.read(name=name) for name in exported.namelist()
        } == expected
        assert {
            name: sent.read(name=name) for name in sent.namelist()
        } == expected
