"""The image's own checks: what its Containerfiles, scripts and workflows
hold that a green build would not show.

Test modules import as ``tests.<name>``, so ``just test`` runs
``unittest discover -t .`` from the repository root.
"""

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_script(relpath, name=None):
    """Import an extension-less script, e.g. ``security/module-autoload-block``.

    The scripts guard execution behind ``if __name__ == "__main__"``, so
    importing one under any other name runs only its top-level imports.
    `name` defaults to the filename with dashes turned into underscores.
    """
    path = REPO_ROOT / relpath
    name = name or path.name.replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
