# Export main for pyproject.toml entry point, to avoid AttributeError
# when importing the subpackage in isolation (without side-effects from root __init__.py)
from senpy.cli.main import main  # noqa: F401
