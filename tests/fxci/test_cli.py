# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import subprocess
import sys
from pathlib import Path

root = Path(__file__).parents[2]
fxci = Path(sys.executable).parent / "fxci"


def test_invalidates_hooks():
    """The command line `taskcluster/scripts/redeploy-on-tcyml-change.py` builds.

    That script runs this as a subprocess, so renaming the command or either of
    its options breaks the redeploy hook with nothing to catch it.
    """
    result = subprocess.run(
        [fxci, "invalidates-hooks", "octocat/hello-world", "main"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    assert result.stdout == "false\n"
