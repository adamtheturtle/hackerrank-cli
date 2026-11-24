"""Compatibility exports for the native configuration API now in the
SDK.
"""

from hackerrank.projects import (
    ProjectConfiguration,
    configure_project_archive,
    validate_project_configuration,
)

__all__ = [
    "ProjectConfiguration",
    "configure_project_archive",
    "validate_project_configuration",
]
