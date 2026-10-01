"""Prepare local sources before handing them to the SDK."""

import stat
from collections.abc import Generator, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile, copymode
from tempfile import TemporaryDirectory

from pathspec import GitIgnoreSpec


def reject_symlinks(path: Path) -> None:
    """Reject symlinks in the path and its ancestors before resolving it."""
    for component in (path, *path.parents):
        if component.is_symlink():
            msg = f"Symbolic links are not supported: {component}"
            raise ValueError(msg)


def _rules(directory: Path) -> tuple[tuple[Path, GitIgnoreSpec], ...]:
    """Read one directory's ignore rules without following symlinks."""
    ignore_file = directory / ".gitignore"
    if ignore_file.is_symlink():
        reject_symlinks(ignore_file)
    if ignore_file.is_file():
        return (
            (
                directory,
                GitIgnoreSpec.from_lines(
                    ignore_file.read_text(encoding="utf-8").splitlines(),
                ),
            ),
        )
    return ()


def _inherited_rules(
    directory: Path,
) -> tuple[tuple[Path, GitIgnoreSpec], ...] | None:
    """Inherit rules from the nearest Git root, or start at the source."""
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            bases = [directory]
            while bases[-1] != candidate:
                bases.append(bases[-1].parent)
            rules: list[tuple[Path, GitIgnoreSpec]] = []
            for base in reversed(bases):
                if _is_ignored(base, rules, suffix="/"):
                    return None
                rules.extend(_rules(base))
            return tuple(rules)
    return _rules(directory)


def _is_ignored(
    path: Path,
    rules: Sequence[tuple[Path, GitIgnoreSpec]],
    *,
    suffix: str,
) -> bool:
    """Apply the last matching rule from the deepest matching ignore file."""
    ignored = False
    for base, spec in rules:
        match = spec.check_file(path.relative_to(base).as_posix() + suffix)
        if match.include is not None:
            ignored = match.include
    return ignored


def require_regular_file(path: Path) -> None:
    """Reject devices, pipes, and other special files before reading."""
    if not stat.S_ISREG(path.stat().st_mode):
        msg = f"Only regular files are supported: {path}"
        raise ValueError(msg)


def selected_files(
    directory: Path, excludes: tuple[str, ...]
) -> tuple[Path, ...]:
    """Select regular files using layered Git ignores and final exclusions."""
    exclusion_spec = GitIgnoreSpec.from_lines(excludes)

    def walk(
        parent: Path, rules: tuple[tuple[Path, GitIgnoreSpec], ...]
    ) -> Iterator[Path]:
        for path in sorted(parent.iterdir()):
            if path.name.casefold() == ".git":
                continue
            is_directory = path.is_dir()
            suffix = "/" if is_directory else ""
            relative = path.relative_to(directory).as_posix() + suffix
            if exclusion_spec.match_file(relative):
                continue
            if _is_ignored(path, rules, suffix=suffix):
                continue
            reject_symlinks(path)
            if is_directory:
                yield from walk(path, (*rules, *_rules(path)))
            else:
                require_regular_file(path)
                yield path.relative_to(directory)

    inherited = _inherited_rules(directory)
    if inherited is None:
        return ()
    return tuple(walk(directory, inherited))


@dataclass(frozen=True)
class PreparedSource:
    """Validated bytes or an isolated directory for ZIP preparation."""

    contents: bytes
    directory: Path | None
    files: tuple[str, ...]
    file_mode: int


@contextmanager
def prepare_source(
    *, directory: Path | None, file: Path | None, excludes: tuple[str, ...]
) -> Generator[PreparedSource]:
    """Read or stage everything before allowing a network mutation."""
    if file is not None:
        reject_symlinks(file.absolute())
        if not file.is_file():
            msg = f"Not a regular file: {file}"
            raise ValueError(msg)
        # Preserve source bytes, including non-UTF-8 files.
        contents = file.read_bytes()
        yield PreparedSource(contents, None, (str(file),), file.stat().st_mode)
        return
    if directory is None:
        msg = "Provide exactly one of --directory or --file."
        raise ValueError(msg)
    reject_symlinks(directory.absolute())
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        msg = f"Not a directory: {directory}"
        raise ValueError(msg)
    files = selected_files(directory, excludes)
    if len(files) == 0:
        msg = "No files selected for upload."
        raise ValueError(msg)
    with TemporaryDirectory(prefix="hackerrank-cli-") as temporary:
        staged = Path(temporary).resolve() / "project"
        staged.mkdir()
        for relative in files:
            source = directory / relative
            reject_symlinks(source)
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # Never dereference a symlink introduced after selection.
            # Validate the copied path before packaging its bytes.
            _ = copyfile(source, target, follow_symlinks=False)
            reject_symlinks(target)
            copymode(source, target, follow_symlinks=False)
        yield PreparedSource(
            b"", staged, tuple(path.as_posix() for path in files), 0
        )
