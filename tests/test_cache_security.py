"""Безопасность кэша: cache.pkl не должен исполнять код.

.senpy_cache/cache.pkl лежит ВНУТРИ проекта Ren'Py и переезжает вместе
с проектом (шаринг, скачивание, моды) — это файл из недоверенного
источника. Plain pickle.load на нём = RCE через __reduce__.

Фикс: SafeCacheUnpickler с белым списком модулей (по образцу
SafeRPAUnpickler из rpa.py); мусор/чужие объекты -> None -> кэш
пересобирается, как при обычной коррупции.
"""
import pickle

from senpy.analyzer import SenpyAnalyzer
from senpy.cache import CacheManager, CacheManifest
from senpy.constants import SENPY_VERSION


def test_malicious_cache_does_not_execute_code(tmp_path):
    """RED-драйвер: подложенный pickle с __reduce__ не должен исполниться."""
    marker = tmp_path / "pwned.txt"
    cache_dir = tmp_path / ".senpy_cache"
    cache_dir.mkdir()

    class _Pwned:
        def __reduce__(self):
            # При plain pickle.load исполнится и создаст marker-файл.
            return (eval, (f"open(r'{marker}', 'w').write('pwned')",))

    (cache_dir / "cache.pkl").write_bytes(pickle.dumps(_Pwned()))

    cm = CacheManager(str(tmp_path))
    assert cm.load_manifest() is None
    assert not marker.exists(), "pickle исполнил код из cache.pkl — RCE!"


def test_legit_cache_still_loads(tmp_path):
    """Замок: белый список не должен сломать легитимный кэш (tier-2 hit)."""
    root = tmp_path / "proj"
    (root / "game").mkdir(parents=True)
    (root / "game" / "script.rpy").write_text(
        'label start:\n'
        '    "Hello"\n'
        '    jump chapter_2\n'
        '    return\n'
        '\n'
        'label chapter_2:\n'
        '    "The end"\n'
        '    return\n',
        encoding="utf-8",
    )

    SenpyAnalyzer(str(root)).run(quiet=True)  # холодный прогон пишет кэш

    cm = CacheManager(str(root))
    manifest = cm.load_manifest()
    assert isinstance(manifest, CacheManifest)
    assert manifest.version == SENPY_VERSION
    assert manifest.files


def test_garbage_and_foreign_pickle_rejected(tmp_path):
    """Замок: мусор и легальные pickle'ы чужих классов -> None без краша."""
    cache_dir = tmp_path / ".senpy_cache"
    cache_dir.mkdir()
    cm = CacheManager(str(tmp_path))

    # 1) вовсе не pickle
    (cache_dir / "cache.pkl").write_bytes(b"definitely not a pickle\x00\x80")
    assert cm.load_manifest() is None

    # 2) валидный pickle класса вне белого списка
    import datetime
    (cache_dir / "cache.pkl").write_bytes(pickle.dumps(datetime.datetime(2020, 1, 1)))  # noqa: DTZ001
    assert cm.load_manifest() is None

    # 3) валидный pickle функции из builtins
    (cache_dir / "cache.pkl").write_bytes(pickle.dumps(len))
    assert cm.load_manifest() is None