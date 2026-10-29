# Экспорт main для entry point в pyproject.toml, чтобы избежать AttributeError
# при изолированном импорте субпакета (без side-effect из корневого __init__.py)
from senpy.cli.main import main  # noqa: F401
