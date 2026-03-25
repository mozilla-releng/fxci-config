# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys

sys.path.insert(0, os.path.abspath("./src"))
sys.path.insert(0, os.path.abspath("."))

from expand import expand_all  # noqa: E402

expand_all()

from ciadmin.boot import boot  # noqa: E402

boot()
