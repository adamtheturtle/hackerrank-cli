"""Expose every documented API operation through the SDK catalogue."""

import json
import os
from dataclasses import asdict, dataclass
from typing import TextIO

import click
import httpx
import httpx2
from hackerrank.api import (
    api_catalogue,
    api_operations,
    parse_api_object,
    prepare_operation,
)
from hackerrank.client import HackerRank
from hackerrank.exceptions import HackerRankError
from hackerrank.transports import Transport
from hackerrank.types import JSONValue


@dataclass(frozen=True, kw_only=True)
class APICommandRequest:
    """The request inputs supplied to the API command."""

    operation: str
    path_json: str
    query_json: str
    body_file: TextIO | None


def create_api_cli(*, transport: Transport | None) -> click.Group:
    """Create catalogue, schema and execution commands with an injectable
    transport.
    """

    @click.group(name="api")
    def api() -> None:
        """Call every documented v3, ATS and SCIM operation."""

    def operations() -> None:
        """List operation names, methods, paths and summaries without
        credentials.
        """
        rows = [
            {
                "operation": value.id,
                "method": value.method,
                "path": value.path,
                "summary": value.summary,
                "group": value.group,
            }
            for value in api_operations().values()
        ]
        click.echo(message=json.dumps(obj=rows, indent=2))

    @click.argument("operation")
    def describe(operation: str) -> None:
        """Show an operation's parameters, body schema and referenced
        definitions.
        """
        selected = api_operations().get(operation)
        if selected is None:
            raise click.BadParameter(
                message="Unknown API operation.", param_hint="OPERATION"
            )
        click.echo(
            message=json.dumps(
                obj={
                    "operation": asdict(obj=selected),
                    "definitions": api_catalogue()["definitions"],
                },
                indent=2,
            )
        )

    @click.argument("operation")
    @click.option(
        "--path",
        "path_json",
        default="{}",
        help="JSON object of path parameters.",
    )
    @click.option(
        "--query",
        "query_json",
        default="{}",
        help="JSON object of query fields; arrays use CSV encoding.",
    )
    @click.option(
        "--body-file",
        type=click.File(mode="r", encoding="utf-8"),
        help="JSON request body file, or - for stdin.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Validate without credentials or network access.",
    )
    def call(
        operation: str,
        path_json: str,
        query_json: str,
        body_file: TextIO | None,
        *,
        dry_run: bool,
    ) -> None:
        """Execute OPERATION and print status, headers and complete JSON
        data.
        """
        _call_api(
            request=APICommandRequest(
                operation=operation,
                path_json=path_json,
                query_json=query_json,
                body_file=body_file,
            ),
            dry_run=dry_run,
            transport=transport,
        )

    _ = api.command(name="operations")(operations)
    _ = api.command(name="describe")(describe)
    _ = api.command(name="call")(call)
    return api


def _path_parameters(*, values: dict[str, JSONValue]) -> dict[str, str | int]:
    """Reject structured values before the SDK encodes path segments."""
    result: dict[str, str | int] = {}
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, str | int):
            message = "Path parameters must be strings or integers."
            raise TypeError(message)
        result[name] = value
    return result


def _call_api(
    *,
    request: APICommandRequest,
    dry_run: bool,
    transport: Transport | None,
) -> None:
    """Prepare a request before credential access, then execute it through
    the SDK.
    """
    operation = request.operation
    path_json = request.path_json
    query_json = request.query_json
    body_file = request.body_file
    try:
        path_values = parse_api_object(text=path_json)
        path_parameters = _path_parameters(values=path_values)
        query = parse_api_object(text=query_json)
        body = (
            None
            if body_file is None
            else parse_api_object(text=body_file.read())
        )
        selected, path, _ = prepare_operation(
            operation=operation,
            path_parameters=path_parameters,
            query=query,
            body=body,
        )
    except (ValueError, TypeError, OSError) as error:
        raise click.BadParameter(
            message=f"Invalid API input: {error}"
        ) from None
    if dry_run:
        click.echo(message=f"Would call {selected.method} {path}")
        return
    variable = (
        "HACKERRANK_SCIM_API_TOKEN"
        if selected.scim
        else "HACKERRANK_API_TOKEN"
    )
    credential = os.environ.get(key=variable, default="")
    if not bool(credential.strip()):
        raise click.ClickException(
            message=f"Set {variable} to a nonblank API token."
        )
    try:
        with HackerRank(
            api_key="scim-only" if selected.scim else credential,
            transport=transport,
        ) as client:
            response = client.api.call(
                operation=operation,
                path_parameters=path_parameters,
                query=query,
                body=body,
                scim_api_key=credential if selected.scim else None,
            )
    except HackerRankError as error:
        raise click.ClickException(
            message=f"HackerRank request failed (HTTP {error.status_code})."
        ) from None
    except (httpx.TransportError, httpx2.TransportError):
        raise click.ClickException(
            message="Could not reach HackerRank."
        ) from None
    click.echo(message=json.dumps(obj=asdict(obj=response), indent=2))
