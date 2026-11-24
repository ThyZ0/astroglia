import sys

# Fast path: the file hook runs after every Read/Edit/Write, so it must not import the CLI stack.
if sys.argv[1:3] == ["hook", "post-tool"]:
    from .anchors import run

    sys.exit(run())
if sys.argv[1:3] == ["hook", "failure"]:
    from .dejavu import run

    sys.exit(run())

from .cli import main

sys.exit(main())
