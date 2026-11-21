from __future__ import annotations

from dataclasses import dataclass

from senpy.core.analyzer import SenpyAnalyzer
from senpy.core.file_discovery import _find_tl_dir_index


@dataclass
class LanguageStats:
    language: str
    total_strings: int = 0
    translated_strings: int = 0
    empty_strings: int = 0

    @property
    def coverage_percent(self) -> float:
        if self.total_strings == 0:
            return 100.0
        return round((self.translated_strings / self.total_strings) * 100, 1)


def calculate_translation_coverage(project_path: str) -> dict[str, LanguageStats]:
    """
    Scans game/tl/ and returns translation statistics for each found language.
    """
    analyzer = SenpyAnalyzer(project_path)
    _, tl_files = analyzer._get_rpy_files()

    stats_by_lang: dict[str, LanguageStats] = {}

    for file_path in tl_files:
        norm_path = file_path.replace("\\", "/")
        rel_parts = norm_path.split("/")

        # Determine the language: the folder right after the canonical
        # ``tl`` directory. Use ``_find_tl_dir_index`` instead of
        # ``rel_parts.index("tl")`` — the latter returns the FIRST ``tl``
        # in the path, which on a backup layout like
        # ``game/tl/old_backup/tl/russian/file.rpy`` resolves to
        # ``old_backup`` instead of the real language ``russian``. The
        # helper returns the LAST ``tl`` inside the canonical
        # ``game/tl/`` subtree, so the language folder after it is the
        # real one.
        tl_idx = _find_tl_dir_index(rel_parts)
        if tl_idx is None:
            continue
        if tl_idx + 1 >= len(rel_parts):
            continue

        lang = rel_parts[tl_idx + 1]
        # Skip the Ren'Py engine 'None' service language
        if lang.lower() == "none":
            continue

        if lang not in stats_by_lang:
            stats_by_lang[lang] = LanguageStats(language=lang)

        try:
            with open(file_path, encoding="utf-8", newline="") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError):
            continue

        pairs = SenpyAnalyzer._parse_tl_pairs(lines)
        for old_txt, _, new_txt, _ in pairs:
            stats_by_lang[lang].total_strings += 1
            if new_txt.strip():
                stats_by_lang[lang].translated_strings += 1
            else:
                stats_by_lang[lang].empty_strings += 1

    return stats_by_lang
