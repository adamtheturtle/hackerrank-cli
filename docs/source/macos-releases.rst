macOS releases
==============

The standalone macOS release binary needs a Developer ID Application signature
and Apple notarization. These steps follow the ``coderpad-cli``
release workflow inspected at ``cf613fc21b457ff85fc13f89daf99ff0e9625ecf``.
Installing the Python wheel with uv or pip does not use this binary.

The release workflow calls ``binaries.yml`` with ``notarize: true`` and passes
five repository secrets. Missing secrets stop the build before importing a
certificate. PR and ordinary branch builds use an ad-hoc signature and do not
use these credentials. Their artifacts are development builds.

Signing and verification
------------------------

The certificate import action creates a temporary keychain and removes it in
its post step. The PKCS#12 export must contain exactly one Developer ID
Application identity. An ambiguous identity fails the build.

PyInstaller receives ``--codesign-identity "Developer ID Application"`` so
that it signs embedded libraries before packing the one-file archive, as well
as the outer executable. It enables the hardened runtime and secure timestamp.
This keeps library validation enabled without an entitlement exception.
The workflow verifies the signature and runs help and version commands after
signing to check that the bundled Python libraries still load.

The signed binary is zipped with ``ditto`` and submitted with ``notarytool``.
The workflow requires an explicit ``Accepted`` status and retrieves Apple's
diagnostic log on rejection. It then retries
``codesign -vvvv -R="notarized" --check-notarization`` to verify that Apple's
online ticket is available before uploading the artifact. PyPI publication
and GitHub Release creation both wait for these binary checks.

A ticket cannot be stapled to a bare Mach-O executable. Gatekeeper uses its
online ticket. ``spctl --assess --type exec`` can reject standalone code as
not being an app, so it is not the release check. A future signed installer
package or disk image could carry a stapled ticket for offline distribution.

See `Apple's notarization workflow
<https://developer.apple.com/documentation/security/customizing-the-notarization-workflow>`_
and `PyInstaller's code-signing documentation
<https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing>`_.

Credential setup
----------------

Use repository secrets, which the caller explicitly passes to the reusable
binary workflow. The ``release`` environment on the PyPI job does not supply
secrets to that separate job.

* ``DEVELOPER_ID_APP_CERT_P12_BASE64``: the base64-encoded Developer ID
  Application PKCS#12 export, including its private key.
* ``DEVELOPER_ID_APP_CERT_PASSWORD``: the export's password.
* ``APPLE_ID``: the Apple account used for notarization.
* ``APPLE_TEAM_ID``: the team matching the signing identity.
* ``APPLE_APP_PASSWORD``: an Apple app-specific password for that account.

Supply values directly through standard input to avoid writing credentials
into repository files or shell arguments:

.. code-block:: shell

   base64 -i /path/to/developer-id-application.p12 | gh secret set DEVELOPER_ID_APP_CERT_P12_BASE64 --repo adamtheturtle/hackerrank-cli
   gh secret set DEVELOPER_ID_APP_CERT_PASSWORD --repo adamtheturtle/hackerrank-cli < /path/to/export-password.txt
   gh secret set APPLE_ID --repo adamtheturtle/hackerrank-cli
   gh secret set APPLE_TEAM_ID --repo adamtheturtle/hackerrank-cli
   gh secret set APPLE_APP_PASSWORD --repo adamtheturtle/hackerrank-cli

Existing encrypted GitHub secrets in another repository cannot be read back
or copied through the GitHub API. Configure these values from the owner's
original credentials. Renew the signing certificate before its expiry.
Secure timestamps keep previously signed releases valid after expiry.

Before the first release, run the signing and notarization path with the
configured credentials and inspect the downloaded artifact. Local signature
checks and unsigned CI alone do not prove Apple's acceptance. No package
release or live HackerRank upload is needed to test the CLI itself.

After the workflow is merged, dispatch it from ``main`` to test notarization
without publishing a release:

.. code-block:: shell

   gh workflow run binaries.yml --repo adamtheturtle/hackerrank-cli --ref main -f notarize=true

Signing is allowed only from ``main`` or a release tag. The ordinary unsigned
workflow can still run on branches and pull requests.
