Development and releases
========================

This standalone repository follows ``coderpad-cli`` main at
``cf613fc21b457ff85fc13f89daf99ff0e9625ecf``.
It adapts the src layout, Click entry points, setuptools-scm versions, uv
lockfile, strict checks, 100% branch coverage, Sphinx, Towncrier, and
distribution workflows.
The SDK baseline is the released ``hackerrank==2026.9.16`` in ``uv.lock``.
Python 3.13 or later is required by the SDK.

The released SDK exposes ``questions.upload_project_zip``.
Its newer ``upload_project_directory`` helper is not yet released.
This CLI prepares filtered ZIPs with the standard library and uses the public
released SDK for multipart serialization and all API communication.
It does not import private SDK helpers or install an unreleased Git dependency.

.. code-block:: shell

   uv sync --locked --group dev
   uv run pytest
   uv run prek run --all-files
   uv run prek run --all-files --stage pre-push
   uv run sphinx-build -W --keep-going -b html docs/source docs/build/html
   uv build
   uv run twine check dist/*
   uv run check-wheel-contents dist/*.whl

Tests use the real SDK with its public ``Transport`` interface and default
HTTPX transport.
No SDK methods are replaced and no live questions are mutated.
RESPX intercepts the HTTP boundary and fails closed for unregistered requests.
Tests inspect the actual multipart body and ZIP bytes, assert the absence of
metadata updates, preserve text, binary contents and executable bits, and
exercise SDK retries with immutable archive bytes.

The SDK's checked-in Swagger specification does not describe the
``upload_project_zip`` endpoint.
The upload tests so assert the released SDK's actual wire behavior instead of
inventing an OpenAPI schema.
No separate mock-spec repository is needed for this scope.

Add a Towncrier feature or bugfix fragment in Markdown for each user-visible
change, such as ``newsfragments/123.bugfix.md``.

Versions derive from Git tags using setuptools-scm.
Untagged builds have a development version.
Use date-based tags such as ``2026.10.7`` for releases.
Before tagging a release, assemble notes with
``uv run towncrier build --yes --version VERSION``, commit the generated notes
in ``docs/source/changelog/VERSION.md``, then write the same version to
``VERSION``, commit it, then tag the commit.
Pushing a tag is the explicit publication trigger.
The release workflow builds and checks packages, builds three standalone
binaries, and then publishes to PyPI, GitHub Releases, and GHCR.

Towncrier writes a separate Markdown file for each release.
Sphinx reads those files through MyST and lists them in the changelog.
The release workflow uploads the tagged version's file directly as its GitHub
release notes.
Pull requests check that the notes for ``VERSION`` exist.
Review the generated Markdown before pushing a release tag.

Local builds
------------

.. code-block:: shell

   uv run --group binary pyinstaller --clean --onefile --copy-metadata hackerrank-cli --name hackerrank bin/hackerrank_wrapper.py
   ./dist/hackerrank --help
   docker build -t hackerrank-cli .
   docker run --rm hackerrank-cli --help
   nix flake check
   nix build
   nix run . -- --help

The Docker image builds a wheel from this checkout rather than depending on an
unpublished PyPI artifact.
Mount content read-only and forward the existing environment variable for an
upload:

.. code-block:: shell

   docker run --rm -e HACKERRANK_API_TOKEN -v "$PWD/starter:/starter:ro" hackerrank-cli questions upload 123456 --directory /starter --dry-run

The Nix flake uses uv2nix and the committed lockfiles.
Its build injects an SCM version because Git metadata is unavailable in Nix
source snapshots.
The standalone-binary workflow runs for releases and manual builds.
Unsigned macOS builds use PyInstaller's ad-hoc signature.
Distribution signing and notarization are required by the release workflow.
See :doc:`macos-releases` for signing, notarization, and credential setup.

External setup
--------------

* Register a PyPI trusted publisher for project ``hackerrank-cli``, owner
  ``adamtheturtle``, repository ``hackerrank-cli``, workflow ``release.yml``,
  environment ``release``.
  That GitHub environment already exists.
  No PyPI token is stored in the repository.
* GitHub Pages is already enabled with the GitHub Actions source.
  Manually run ``publish-site.yml`` from ``main`` to redeploy documentation.
  Ordinary CI builds documentation without deploying it.
* Allow Actions to create GitHub Releases and publish the repository's GHCR
  package.
  Make the GHCR package public after the first release if needed.
* Configure the five macOS signing and notarization repository secrets in
  :doc:`macos-releases` before releasing.
  A missing credential fails the build; releases cannot fall back to an
  unsigned macOS binary.
* No Homebrew tap, winget manifest, package-manager registration, or TestPyPI
  configuration has been created.
  Do not advertise those installation paths until they exist.

The default branch requires 13 Actions checks: tests on Python 3.13 and 3.14
across Linux, macOS, and Windows, lint on Linux and Windows, documentation,
packaging, two Nix builds, and autofix.
The public repository's tests and builds do not need a HackerRank token.

Quality checks
--------------

The quality configuration follows Literalizer at commit
``30b54d2199171429ba44baa61467df14bcf87a68``.
Run the fast checks before committing and the type checks before pushing.
Pylint and documentation builders also run in CI.
Install the Enchant library and the US English dictionary for spelling checks
(``brew install enchant`` on macOS).

.. code-block:: shell

   uv run --locked prek run --all-files --stage pre-commit
   uv run --locked prek run --all-files --stage pre-push
   uv run --locked prek run --all-files --stage manual --group pylint
   uv run --locked prek run --all-files --stage manual --group docs

Checks cover dependency declarations, dead code, package metadata, docstrings,
keyword-only parameters, documentation examples, shell commands, and Actions
security alongside the four strict type checkers and branch coverage.
Generated version files are excluded from source checks.
The SDK owns its HTTP client and models.

Literalizer CLI check parity
----------------------------

Additional checks follow ``literalizer-cli`` at commit
``cf435b8ee67dd9900d795a8438622ad02aaaf730``.
The dedicated ``uv-lock`` hook checks that dependency metadata and the lockfile
agree.
All Python source files are checked, including documentation and binary
wrappers.
Tests run in parallel and check runtime types in the public package, tests, and
fixtures.
Help text for every command is compared with committed regression snapshots.
Review any help change before updating snapshots:

.. code-block:: shell

   uv run --locked pytest tests/test_help.py --regen-all --no-cov

CI runs all hook stages on Linux and Windows and runs daily on ``main``.
The existing stricter lint, documentation, and workflow security checks remain
enabled.
