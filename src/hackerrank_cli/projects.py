"""Compatibility helpers for the native project configuration API."""

from dataclasses import dataclass

from hackerrank.project_configuration import (
    ProjectConfiguration as SDKProjectConfiguration,
)
from hackerrank.project_configuration import (
    configure_project_archive,
    validate_project_configuration,
)

__all__ = [
    "ProjectConfiguration",
    "configure_project_archive",
    "validate_project_configuration",
]


@dataclass(frozen=True, kw_only=True)
class ProjectConfiguration:
    """Support the original flat configuration constructor."""

    has_webserver: bool
    readonly_paths: list[str]
    scoring_command: str
    scoring_files: list[str]
    default_open_files: list[str]
    project_menu: dict[str, str]

    def to_yaml(self) -> bytes:
        """Render a UTF-8 native configuration document."""
        return SDKProjectConfiguration(
            version=1.0,
            configuration={
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
        ).to_yaml()
