"""Keep public help text and the binary entry point stable."""

import runpy
from pathlib import Path

import pytest
from click.testing import CliRunner
from pytest_regressions.file_regression import FileRegressionFixture

from hackerrank_cli import main


@pytest.mark.parametrize(
    argnames="arguments",
    argvalues=[[], ["questions"], ["questions", "upload"]],
    ids=["root", "questions", "upload"],
)
def test_help(
    arguments: list[str], file_regression: FileRegressionFixture
) -> None:
    """Compare all command help text with reviewed snapshots."""
    result = CliRunner().invoke(
        cli=main,
        args=[*arguments, "--help"],
        catch_exceptions=False,
        color=True,
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    file_regression.check(contents=result.output)


def test_wrapper_does_not_run_on_import() -> None:
    """Importing the binary wrapper must not execute the command."""
    wrapper = Path(__file__).parent.parent / "bin" / "hackerrank_wrapper.py"
    namespace = runpy.run_path(
        path_name=str(object=wrapper), run_name="not_main"
    )
    assert namespace["main"] is main
