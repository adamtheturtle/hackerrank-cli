"""Upload project starter code using the released HackerRank SDK."""

import os
from collections.abc import Generator
from contextlib import contextmanager
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import click
import httpx
import httpx2
from hackerrank.client import HackerRank
from hackerrank.exceptions import HackerRankError
from hackerrank.transports import Transport

from hackerrank_cli._sources import PreparedSource, prepare_source


def create_cli(*, transport: Transport | None = None) -> click.Group:
    """Create the CLI, optionally using a supported SDK transport."""

    @click.group(name="hackerrank")
    @click.version_option(
        version=version(distribution_name="hackerrank-cli"),
        prog_name="hackerrank",
    )
    def cli() -> None:
        """Upload starter files to existing HackerRank project
        questions.
        """

    @cli.group()
    def questions() -> None:
        """Manage project-question starter files."""

    @click.argument("question_id")
    @click.option(
        "--directory",
        type=click.Path(path_type=Path, readable=False),
        help="Project directory.",
    )
    @click.option(
        "--file",
        "source_file",
        type=click.Path(path_type=Path, readable=False),
        help="One starter file, uploaded as a single-file project archive.",
    )
    @click.option(
        "--exclude",
        multiple=True,
        help="Additional Gitignore pattern at the upload root. Repeatable.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Validate and list files without credentials or network access.",
    )
    @click.option(
        "--retries",
        type=click.IntRange(min=0),
        default=0,
        show_default=True,
        help="Retry count delegated to the SDK for this repeatable upload.",
    )
    def upload(  # noqa: PLR0913 - Click command options.
        question_id: str,
        directory: Path | None,
        source_file: Path | None,
        exclude: tuple[str, ...],
        retries: int,
        *,
        dry_run: bool,
    ) -> None:
        """Replace project starter files while preserving question
        metadata.
        """
        _upload(
            question_id=question_id,
            directory=directory,
            source_file=source_file,
            exclude=exclude,
            retries=retries,
            dry_run=dry_run,
            transport=transport,
        )

    @click.option(
        "--directory",
        type=click.Path(path_type=Path, readable=False),
        help="Project directory.",
    )
    @click.option(
        "--file",
        "source_file",
        type=click.Path(path_type=Path, readable=False),
        help="One starter file, packaged as a single-file project archive.",
    )
    @click.option(
        "--exclude",
        multiple=True,
        help="Additional Gitignore pattern at the upload root. Repeatable.",
    )
    @click.option(
        "--output",
        type=click.File(mode="xb", lazy=True),
        required=True,
        help=(
            "New ZIP file, or - for binary standard output. "
            "Never overwrites files."
        ),
    )
    def archive(
        directory: Path | None,
        source_file: Path | None,
        exclude: tuple[str, ...],
        output: BinaryIO,
    ) -> None:
        """Export a project ZIP without credentials or network access."""
        _validate_source(
            directory=directory, source_file=source_file, exclude=exclude
        )
        with (
            _preparation_errors(),
            prepare_source(
                directory=directory, file=source_file, excludes=exclude
            ) as source,
        ):
            contents = _project_zip(source=source)
            _ = output.write(contents)

    _ = questions.command()(archive)
    _ = questions.command()(upload)
    return cli


def _validate_source(
    directory: Path | None,
    source_file: Path | None,
    exclude: tuple[str, ...],
) -> None:
    """Validate the shared archive and upload source options."""
    if (directory is None) == (source_file is None):
        msg = "Provide exactly one of --directory or --file."
        raise click.UsageError(message=msg)
    if len(exclude) > 0 and directory is None:
        msg = "--exclude requires --directory."
        raise click.UsageError(message=msg)


def _api_key() -> str:
    """Read a nonempty API token without printing its value."""
    api_key = os.environ.get(key="HACKERRANK_API_TOKEN")
    if api_key is None or api_key.strip() == "":
        msg = (
            "HACKERRANK_API_TOKEN is missing or empty. "
            "Set it in the environment."
        )
        raise click.ClickException(message=msg)
    return api_key


def _project_zip(source: PreparedSource) -> bytes:
    """Package prepared starter files for the released SDK's ZIP API."""
    with BytesIO() as buffer:
        with ZipFile(
            file=buffer, mode="w", compression=ZIP_DEFLATED
        ) as archive:
            if source.directory is None:
                info = ZipInfo(filename=Path(source.files[0]).name)
                info.external_attr = source.file_mode << 16
                archive.writestr(
                    zinfo_or_arcname=info,
                    data=source.contents,
                    compress_type=ZIP_DEFLATED,
                )
            else:
                for name in source.files:
                    archive.write(
                        filename=source.directory / name, arcname=name
                    )
        return buffer.getvalue()


def _send_upload(
    question_id: str,
    archive: bytes,
    retries: int,
    transport: Transport | None,
) -> None:
    """Delegate communication and retries to the SDK; report safe
    errors.
    """
    api_key = _api_key()
    try:
        with HackerRank(
            api_key=api_key, transport=transport, retries=retries
        ) as client:
            _ = client.questions.upload_project_zip(
                question_id=question_id, file=archive
            )
    except HackerRankError as error:
        # Response bodies can contain secrets; only report the status.
        msg = f"HackerRank rejected the upload (HTTP {error.status_code})."
        raise click.ClickException(message=msg) from None
    except (httpx.TransportError, httpx2.TransportError):
        msg = "Could not reach HackerRank. Check your network connection."
        raise click.ClickException(message=msg) from None
    except (ValueError, TypeError):
        msg = (
            "HackerRank returned an invalid response. The upload may have "
            "succeeded; check the question before trying again."
        )
        raise click.ClickException(message=msg) from None


def _upload(  # noqa: PLR0913 - Click options plus the SDK transport boundary.
    question_id: str,
    directory: Path | None,
    source_file: Path | None,
    exclude: tuple[str, ...],
    retries: int,
    *,
    dry_run: bool,
    transport: Transport | None,
) -> None:
    """Prepare every byte before credentials or a network mutation."""
    _validate_source(
        directory=directory,
        source_file=source_file,
        exclude=exclude,
    )
    if (
        not question_id.isascii()
        or not question_id.isdecimal()
        or int(question_id) < 1
    ):
        msg = "QUESTION_ID must be a positive decimal integer."
        raise click.BadParameter(message=msg, param_hint="QUESTION_ID")
    with (
        _preparation_errors(),
        prepare_source(
            directory=directory, file=source_file, excludes=exclude
        ) as source,
    ):
        archive = _project_zip(source=source)
        target = f"HackerRank project question {question_id}"
        if dry_run:
            click.echo(message=f"Would update {target}")
            for path in source.files:
                click.echo(message=f"  {path}")
            return
        _send_upload(
            question_id=question_id,
            archive=archive,
            retries=retries,
            transport=transport,
        )
        click.echo(message=f"Updated {target}")


@contextmanager
def _preparation_errors() -> Generator[None]:
    """Report source and archive errors consistently for both commands."""
    try:
        yield
    except UnicodeError:
        msg = ".gitignore files must be valid UTF-8."
        raise click.ClickException(message=msg) from None
    except OSError as error:
        msg = f"Could not prepare upload files ({type(error).__name__})."
        raise click.ClickException(message=msg) from None
    except ValueError as error:
        raise click.ClickException(message=str(object=error)) from None


main: click.Group = create_cli()
