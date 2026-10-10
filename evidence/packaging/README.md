# Installer and isolated-wheel acceptance

`installer-real-native-acceptance.json` records the 2026-10-10 acceptance of the
packaged `warband-kit-install` interface against this machine's real user-owned
Native module. The command created a new 84 MB module and private runtime root in
an exact temporary directory; `warband-agent-host --check` then loaded the
generated catalog, build manifest and four credentials and reported `ready`.

No game or external model was launched. No credential value is retained here.
The temporary output, including the generated module with its embedded game
credential, was moved to desktop trash after validation and remains recoverable
until the user empties trash.

The live run proves compatibility with the installed Native data and the complete
generated host/module contract. `test_installer.py` separately proves
byte-for-byte Native preservation, secret-free planning and receipts, rejection
of existing targets and exact rollback after a failed patch-seam validation.
`test_packaging.py` builds the sdist-derived wheel, installs it outside the
checkout, runs the installed installer against a synthetic Native tree and checks
the generated host through the installed command.

This is packaging evidence, not game-runtime evidence. Hardware-rendered game
acceptance and final interaction videos remain separate release gates.
