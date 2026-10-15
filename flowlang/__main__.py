"""Lets the compiler run as `python -m flowlang <file.flow>`."""

import sys

from flowlang.main import main

sys.exit(main())
