Migrating existing uploaders
============================

Keep question IDs, source-path mappings, builds, configuration updates,
interview-template management, and upload-on-push orchestration in the
repository that owns the questions.
This CLI uploads starter files to an existing project question.
It never creates questions or updates metadata.

After the first PyPI release, pin a released ``hackerrank-cli`` version in that
repository.
Replace each project archive upload with:

.. code-block:: shell

   hackerrank questions upload 123456 --directory ./starter --exclude '*.zip' --dry-run
   hackerrank questions upload 123456 --directory ./starter --exclude '*.zip' --retries 3

Convert that repository's existing exclusion list into repeatable ``--exclude``
options and inspect the dry-run file list first.
Do not carry company-specific exclusions into this public CLI.
Keep metadata updates and snippet preparation as separate steps when the
repository needs them.

``--retries 3`` delegates retry decisions and backoff to the SDK.
The default is zero, matching the released SDK.
Uploads use immutable archive bytes so retries send the same content.
Do not enable live uploads until the file list and project behavior have been
reviewed in the owning repository.
