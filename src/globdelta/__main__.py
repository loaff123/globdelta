"""Support ``python -m globdelta`` without separate invocation semantics."""
from .cli import main

raise SystemExit(main())
