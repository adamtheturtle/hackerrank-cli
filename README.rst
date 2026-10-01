hackerrank-cli
==============

Upload starter files to an existing HackerRank for Work project question using
the ``hackerrank`` Python SDK.
This independent CLI replaces only the project archive, preserving the
question's name, problem statement, environment, scoring settings, and other
metadata.

The initial scope is project questions such as fullstack, frontend, and backend
projects.
Language-specific coding-question stubs are outside this CLI's initial scope.

Requires Python 3.13 or later.
No package release has been published yet.
Install the checkout for now:

.. code-block:: console

   uv sync --locked
   uv run hackerrank --help
   uv run python -m hackerrank_cli --version

After the first PyPI release, install with ``uv tool install hackerrank-cli``
or ``pip install hackerrank-cli``.

Usage
-----

Use synthetic question ID ``123456`` below in place of your own question ID.
Exactly one content source is required:

.. code-block:: console

   hackerrank questions upload 123456 --directory ./starter --dry-run
   hackerrank questions upload 123456 --directory ./starter --exclude '*.zip'
   hackerrank questions upload 123456 --file ./starter.py

Real uploads read ``HACKERRANK_API_TOKEN`` from the environment.
Get a key from the HackerRank for Work API tokens page.
Missing, empty, and whitespace-only keys fail clearly.
Dry runs need no key and make no network requests.

Exactly one of ``--directory`` or ``--file`` is required.
Both replace the entire project archive.
``--file`` creates a one-file project using the source's basename; it does not
update a language-specific code stub or upload a prebuilt ZIP as the project
archive.

All file bytes are preserved exactly, including binary files, CRLF, blank
lines, trailing whitespace, UTF-8 BOMs, and documentation markers.
Empty single files are valid.
Neither paths nor IDs are inferred from repository configuration.
Inputs are fully read, staged, and archived before credentials are read or a
mutation is issued.
POSIX executable bits are preserved.
Errors exit nonzero.
API response bodies and credentials are never printed.
The default retry count is zero, matching the released SDK.
Set ``--retries 3`` to delegate retries and backoff to the SDK for this
repeatable upload.
The CLI adds no separate retry loop.
Each attempt uses the same prepared archive bytes.

Offline archives
----------------

Export the same project ZIP locally without a question ID, credentials, or
network access:

.. code-block:: console

   hackerrank questions archive --directory ./starter --exclude '*.zip' --output ./starter.zip
   hackerrank questions archive --file ./starter.py --output - > ./starter.zip

``--output`` is required.
A file destination must not already exist; ``-`` writes only ZIP bytes to
standard output.
Shell redirection controls whether its destination is overwritten.
Source validation and packaging finish before the output is opened.
The source options, ignore rules, file contents, and executable permissions
match ``questions upload``.
Consumers can extract this archive for local checks, then send its bytes with
the SDK's ``questions.upload_project_zip`` method.

Directory selection
-------------------

* Both Git and non-Git directories work.
  Paths are relative to the current working directory.
  A Git worktree's ``.git`` file also identifies its root.
* In a Git repository, rules are inherited from the nearest Git root down to
  the upload directory.
  Outside Git, rules start at the upload directory; unrelated parent
  ``.gitignore`` files are not used.
* Each traversed directory adds its own ``.gitignore`` rules.
  Later matching rules override earlier ones, and deeper files override
  ancestor rules.
  Patterns are relative to their owning directory.
  Directory-only rules and negations follow Gitignore semantics.
  Excluded directories are pruned, so a child cannot re-include itself unless
  its parent is re-included first.
  This also applies to ancestors of an explicitly selected nested upload root.
* Ignore rules apply to tracked files too.
  Global Git excludes and ``.git/info/exclude`` are not read.
  Hidden files, including ``.gitignore``, are uploaded unless excluded.
* ``.git`` files and directories are always excluded at every depth.
  Explicit source paths inside Git metadata are rejected, including an upload
  rooted at a ``.git`` directory.
  Repeatable ``--exclude PATTERN`` options form a final Gitignore rule layer,
  relative to the upload root.
  This layer can exclude files re-included by ``.gitignore``; its own later
  negations can undo its earlier patterns.
  It cannot re-include a file excluded by ``.gitignore`` or Git metadata.
* ZIP files are included by default.
  Use ``--exclude '*.zip'`` to omit them.
  Add other exclusions explicitly, such as ``--exclude node_modules/``.
* Selected symlinks (including directory, broken, and external links) and
  symlinks in the source path are rejected rather than dereferenced.
  Ignored links are skipped.
  Symlinked ``.gitignore`` files are rejected when their rules would be read.
  Special files are rejected.
  Empty selections fail.
  Selected files are copied to a temporary directory without dereferencing
  links.
  The CLI packages these prepared files with Python's standard ZIP library.
  The released SDK handles multipart serialization, authentication, network
  requests, response decoding, and retries.

Development and distribution
----------------------------

Development checks, release setup, and build instructions for Docker, Nix, and
standalone binaries are in ``docs/source/development.rst``.
The generated CLI reference is in ``docs/source/cli.rst``.
There are no prebuilt artifacts yet.

See ``docs/source/migration.rst`` for migrating an existing shell uploader and
keeping repository-specific snippet preparation outside this CLI.
