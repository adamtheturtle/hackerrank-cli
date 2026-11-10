"""Author native project configuration and add it to prepared archives."""

from dataclasses import dataclass
from io import BytesIO
from typing import TypeIs
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import yaml


@dataclass(frozen=True, kw_only=True)
class ProjectConfiguration:
    """Explicit values for HackerRank's native project configuration.

    All fields are required so callers choose their own project policy.
    """

    has_webserver: bool
    readonly_paths: list[str]
    scoring_command: str
    scoring_files: list[str]
    default_open_files: list[str]
    project_menu: dict[str, str]

    def to_yaml(self) -> bytes:
        """Render a UTF-8 native configuration document."""
        document = {
            "version": 1.0,
            "configuration": {
                "has_webserver": self.has_webserver,
                "readonly_paths": self.readonly_paths,
                "scoring": {
                    "command": self.scoring_command,
                    "files": self.scoring_files,
                },
                "ide_config": {
                    "default_open_files": self.default_open_files,
                    "project_menu": self.project_menu,
                },
            },
        }
        return yaml.safe_dump(data=document, sort_keys=False).encode(
            encoding="utf-8"
        )


def _is_mapping(value: object, /) -> TypeIs[dict[object, object]]:
    """Check whether a YAML root is a dictionary."""
    return isinstance(value, dict)


def validate_project_configuration(*, configuration: bytes) -> None:
    """Require a native version-one mapping without limiting future
    keys.
    """
    try:
        document: object = yaml.safe_load(
            stream=configuration.decode(encoding="utf-8")
        )
    except (UnicodeError, yaml.YAMLError):
        message = "Project configuration must contain valid UTF-8 YAML."
        raise ValueError(message) from None
    if (
        not _is_mapping(document)
        or isinstance(document.get("version"), bool)
        or document.get("version") != 1.0
        or not isinstance(document.get("configuration"), dict)
    ):
        message = (
            "Project configuration requires version 1.0 "
            "and a configuration mapping."
        )
        raise ValueError(message)


def configure_project_archive(
    *, archive: bytes, configuration: bytes
) -> bytes:
    """Replace the root native configuration, preserving other ZIP entries.

    Return a ZIP containing one root ``hackerrank.yml`` entry with the
    supplied UTF-8 configuration bytes. Other entries keep their contents
    and metadata. Invalid YAML, invalid ZIPs, and repeated names raise
    ValueError.
    """
    validate_project_configuration(configuration=configuration)
    with BytesIO() as buffer:
        try:
            with (
                ZipFile(file=BytesIO(initial_bytes=archive)) as original,
                ZipFile(
                    file=buffer, mode="w", compression=ZIP_DEFLATED
                ) as output,
            ):
                names = original.namelist()
                if len(names) != len(set(names)):
                    message = "Project archive contains duplicate entries."
                    raise ValueError(message)
                for entry in original.infolist():
                    if entry.filename != "hackerrank.yml":
                        output.writestr(
                            zinfo_or_arcname=entry,
                            data=original.read(name=entry),
                        )
                output.writestr(
                    zinfo_or_arcname="hackerrank.yml", data=configuration
                )
        except BadZipFile:
            message = "Project archive must be a valid ZIP file."
            raise ValueError(message) from None
        return buffer.getvalue()
