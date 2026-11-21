"""Ren'Py built-in symbols and screen actions.

Single source of truth for the Ren'Py runtime-provided namespaces and
screen-action classes that Senpy treats as ``declared`` without an
explicit ``define`` / ``default`` from the user. Extracted out of
``core/constants.py`` so the rest of the codebase can import a single,
focused module, and so ``senpy.toml [tool.senpy].additional_builtins``
/ ``.additional_actions`` can extend them at runtime.

Contents
--------
``BUILTIN_SYMBOLS`` — the runtime-provided *names* Ren'Py makes available
in the ``store`` namespace before any user ``define`` / ``default`` runs.
Includes:
    - The mutable namespaces (``persistent``, ``config``, ``gui``, ``style``,
      ``store``, ``audio``, ``layout``, ``ui``, ``im`` …).
    - Ren'Py-specific globals (``renpy``, ``main_menu``, ``_return``,
      ``_in_replay``, ``_window_during_functions``, ``_history_list``,
      ``_restart``, ``currentuser``, ``name``, ``player``, ``theme``,
      ``who``, ``what``, ``prefix_``, ``Action``, ``Preferences``).
    - Built-in transition aliases (``dissolve``, ``fade``, ``pixellate``,
      ``vpunch``, ``hpunch``, ``pushleft`` …).
    - Standard positions / base transforms (``center``, ``left``,
      ``topleft`` …) and transition classes that take parameters
      (``Dissolve(1.0)``, ``Fade(...)``).
    - Python's ``builtins`` (``len``, ``range``, ``True`` …).
    - The ``achievement`` namespace (Ren'Py ships ``achievement`` as a
      runtime-provided object — see
      https://www.renpy.org/doc/html/achievements.html — so users can write
      ``if achievement.steam:`` without a ``default``). Previously missed
      here, causing RPY202 false positives on the ``developers_info``
      screen.
    - **Auto-extracted namespace roots from ``renpy_api_generated.json``**
      (added in 0.9.2): the top-level namespaces that have entries in the
      generated JSON — ``config``, ``gui``, ``build``, ``renpy``,
      ``persistent``, ``preferences`` — are merged in at module import
      time. When Ren'Py adds a new namespace (e.g. ``renpy.clipboard`` in
      8.6), the next ``scripts/fetch_renpy_docs.py`` run adds it to the
      JSON, and the namespace root appears in ``BUILTIN_SYMBOLS``
      automatically — no manual edit needed here. This closes the class
      of FP where Ren'Py adds a new runtime namespace and Senpy's RPY202
      starts firing on it before the maintainer notices. (Specific
      leaf-level entries like ``config.developer`` are NOT auto-added —
      the namespace root is enough for RPY202 to recognise
      ``config.developer.foo`` as a declared name.)

``BUILTIN_ACTIONS`` — the documented Ren'Py screen-action classes that can
be called with ``()`` in the ``action`` slot of a screen button (i.e. they
return an Action object — calling them is the documented usage, **not**
"executes immediately during screen render"). Sourced from
https://www.renpy.org/doc/html/screen_actions.html. Includes:

    - The historical set (``SetVariable``, ``Show``, ``Jump``, ``Return``,
      ``Function``, ``Play`` …).
    - The full extended action library (``FilePagePrevious``,
      ``CycleDict``, ``IncrementField`` …) — added because RPY206 was
      firing false positives on legitimate patterns like
      ``action FilePagePrevious()``.
    - ``GamepadCalibrate`` — documented action that invokes the gamepad
      calibration routine. Previously missed here, causing RPY206 false
      positives on ``textbutton "Calibrate" action GamepadCalibrate()``.

Configurable extension
----------------------
``senpy.toml`` may extend both sets at runtime via::

    [tool.senpy]
    additional_builtins = ["my_custom_namespace", "iap"]
    additional_actions = ["MyCustomAction"]

These are merged with the defaults in ``SymbolTable`` (for
``BUILTIN_SYMBOLS``) and ``ScreenChecker`` (for ``BUILTIN_ACTIONS``) — see
``SenpyAnalyzer.__init__`` for the loading path. The defaults here stay a
plain ``set`` so the existing contract (``isinstance(BUILTIN_SYMBOLS, set)``
in tests/core/test_imports.py) is preserved.
"""

from __future__ import annotations

import builtins

from senpy.core.logging import get_logger

_logger = get_logger("renpy_builtins")


# =============================================================================
# Auto-extracted namespace roots from renpy_api_generated.json
# =============================================================================
# These are the top-level names that Ren'Py ships as runtime-provided
# namespaces (each has at least one entry in renpy_api_generated.json under
# ``config.*`` / ``gui.*`` / ``build.*`` / ``renpy.*`` / ``persistent.*`` /
# ``preferences.*``). RPY202 / RPY103 / RPY104 then treat them as declared
# without a user ``default`` / ``define`` — same as ``audio`` or ``store``.
#
# Why auto-extract: Ren'Py regularly adds new namespaces (``renpy.clipboard``
# in 8.6 is the latest example). Before this auto-extraction, each new
# namespace needed a manual edit here + a release — and RPY202 fired on
# every usage until then. By deriving the set from the JSON that
# ``scripts/fetch_renpy_docs.py`` already regenerates on each Ren'Py pin
# bump, new namespaces appear automatically on the next pin bump.
#
# Why only roots: adding ``config.developer`` etc. here would be redundant
# — RPY202 already accepts ``config.X`` when ``config`` is in
# ``BUILTIN_SYMBOLS`` (the rule checks the namespace root, not every leaf).
# Adding leaves would also balloon the set from ~120 to ~800 entries with
# no observable benefit.
def _extract_namespace_roots_from_json() -> set[str]:
    """Return the set of top-level namespace roots found in the generated JSON.

    Walks every entry name in ``renpy_api_generated.json``. For each name
    that contains a ``.``, the part before the first ``.`` is a candidate
    namespace root. Names without a ``.`` (e.g. ``AddToSet``, ``Call``)
    are skipped — they are class/function names, not namespaces, and are
    already covered by ``BUILTIN_ACTIONS`` or the manual entries below.

    Failures (missing file, corrupt JSON, etc.) log a WARNING and return
    an empty set so the rest of ``BUILTIN_SYMBOLS`` still loads.
    """
    try:
        from senpy.domain.renpy_api_generated import RENPY_API_DOCS_GENERATED
    except ImportError as e:
        _logger.warning(
            "cannot import renpy_api_generated for BUILTIN_SYMBOLS auto-extraction: %s. "
            "Falling back to manual list — RPY202 may fire on newly-added Ren'Py namespaces.",
            e,
        )
        return set()

    roots: set[str] = set()
    for name in RENPY_API_DOCS_GENERATED:
        if "." in name:
            root = name.split(".", 1)[0]
            # Filter out obviously non-namespace roots: a namespace root is
            # a Python identifier (so ``config``, ``gui``, ``renpy`` all
            # pass; ``__main__`` would too but does not appear in the JSON).
            # Single-letter roots are extremely unlikely to be real
            # namespaces and would over-broaden BUILTIN_SYMBOLS, so require
            # length >= 2.
            if root.isidentifier() and len(root) >= 2:
                roots.add(root)
    return roots


# =============================================================================
# Runtime-provided names — recognized as "declared" without user default/define
# =============================================================================
# Manual entries that are NOT in renpy_api_generated.json:
#   - Mutable namespaces without their own JSON entries (``store``, ``audio``,
#     ``layout``, ``ui``, ``im``, ``style``).
#   - Ren'Py globals that are not documented as ``namespace.*`` entries
#     (``main_menu``, ``_return``, ``_in_replay``, ``name``, ``player``,
#     ``theme``, ``who``, ``what``, ``prefix_``, ``Action``, ``Preferences``,
#     ``currentuser``, ``_window_during_functions``, ``_history_list``,
#     ``_restart``, ``achievement``).
#   - Transition aliases (``dissolve``, ``fade``, ``vpunch``, …).
#   - Standard positions and base transforms (``center``, ``left``,
#     ``topleft``, ``reset``, ``default``, …).
#   - Transition classes that take parameters (``Dissolve(1.0)``, ``Fade(...)``).
#
# Auto-extracted entries (added at module load via _extract_namespace_roots_from_json):
#   - Namespace roots from the JSON: ``config``, ``gui``, ``build``,
#     ``renpy``, ``persistent``, ``preferences`` (and any future ones).
_MANUAL_BUILTIN_SYMBOLS: set[str] = {
    # Mutable runtime namespaces (no JSON entries of their own).
    "store",
    "audio",
    "layout",
    "ui",
    "im",
    "style",
    # Ren'Py special names.
    "Action",
    "Preferences",
    "main_menu",
    "_return",
    "_in_replay",
    "_window_during_functions",
    "_history_list",
    "_restart",
    "name",
    "player",
    "theme",
    "who",
    "what",
    "prefix_",
    "currentuser",
    # Built-in transition aliases.
    "dissolve",
    "fade",
    "pixellate",
    "vpunch",
    "hpunch",
    "pushright",
    "pushleft",
    "pushup",
    "pushdown",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "zoomin",
    "zoomout",
    "zoominout",
    "blinds",
    "squares",
    "irisin",
    "irisout",
    # Standard Ren'Py positions and base transforms.
    "center",
    "truecenter",
    "left",
    "right",
    "top",
    "topleft",
    "topright",
    "offscreenleft",
    "offscreenright",
    # NOTE: ``"reset"`` was previously listed here under the comment
    # "Standard Ren'Py positions and base transforms", but it is a
    # transform PROPERTY (used in ATL like ``transform: reset``), not a
    # position name — removed in 0.9.2. RPY103/RPY202 now correctly flag
    # reassignment of ``reset``.
    #
    # ``"default"`` stays — it is BOTH a Ren'Py keyword (``default x = 5``)
    # AND a valid position name (``show layer master at default`` — see
    # tests/cli/test_show_layer.py::test_show_layer_is_not_an_image_tag).
    # Removing it would cause a false-positive RPY502 on the legitimate
    # ``at default`` pattern. The keyword/position duality is fine:
    # ``$ default = 5`` is rare in real code and the rule checkers already
    # treat ``default``/``define`` as keywords in declaration contexts
    # (RPY104/RPY105) without consulting BUILTIN_SYMBOLS.
    "default",
    # Built-in Ren'Py transition classes (for calls with parameters:
    # Dissolve(1.0), Fade(...)).
    "Dissolve",
    "Fade",
    "Pixellate",
    "MoveTransition",
    "MultipleTransition",
    "CropMove",
    "PushMove",
    "ImageDissolve",
    "AlphaDissolve",
    "ComposeTransition",
    "Pause",
    # Ren'Py ships `achievement` as a runtime-provided object
    # (https://www.renpy.org/doc/html/achievements.html) — users
    # can write `if achievement.steam:` without a `default`.
    "achievement",
}

BUILTIN_SYMBOLS: set[str] = _MANUAL_BUILTIN_SYMBOLS | _extract_namespace_roots_from_json()
# Python's builtins (len, range, True, ...). Splatted at the end so the set is
# constructed in one call.
BUILTIN_SYMBOLS |= set(dir(builtins))


# =============================================================================
# Screen-action classes — callable with `()` in the `action` slot
# =============================================================================
BUILTIN_ACTIONS: set[str] = {
    # Original set (kept as-is — historical and still valid).
    "SetVariable",
    "SetField",
    "SetScreenVariable",
    "ToggleVariable",
    "ToggleField",
    "ToggleScreenVariable",
    "Show",
    "Hide",
    "Jump",
    "Return",
    "Function",
    "Play",
    "Stop",
    "Queue",
    "PauseAudio",
    "NullAction",
    "Call",
    "Notify",
    "Confirm",
    "Preference",
    "FileSave",
    "FileLoad",
    "FileDelete",
    "FileAction",
    "QuickSave",
    "QuickLoad",
    "Rollback",
    "Skip",
    "Help",
    "Quit",
    "OpenURL",
    "SelectedIf",
    "SensitiveIf",
    "With",
    "HideInterface",
    "ShowMenu",
    "MainMenu",
    "Start",
    "EndReplay",
    "If",
    "Language",
    "ShowTransient",
    "FilePage",
    # Extended to cover the complete screen action library documented at
    # https://www.renpy.org/doc/html/screen_actions.html. Without these,
    # RPY206 fires false positives on legitimate Ren'Py patterns like
    # `action FilePagePrevious()`. Each entry is a callable that returns
    # an Action object — calling it with `()` in the `action` slot is
    # the documented usage, not "executes immediately during screen
    # render".
    "FilePageNext",
    "FilePagePrevious",
    "FileTakeScreenshot",
    "ToggleScreen",
    "SetLocalVariable",
    "ToggleLocalVariable",
    "CycleDict",
    "CycleField",
    "CycleLocalVariable",
    "CycleScreenVariable",
    "CycleVariable",
    "IncrementDict",
    "IncrementField",
    "IncrementLocalVariable",
    "IncrementScreenVariable",
    "IncrementVariable",
    "SetDict",
    "ToggleDict",
    "AddToSet",
    "RemoveFromSet",
    "ToggleSetMembership",
    "Continue",
    "DownloadSync",
    "UploadSync",
    "GetMixer",
    "SetMixer",
    "SetMute",
    "ToggleMute",
    "CaptureFocus",
    "ClearFocus",
    "GetFocusRect",
    "ToggleFocus",
    "InvertSelected",
    "CopyToClipboard",
    "DisableAllInputValues",
    "EditFile",
    "ExecJS",
    "MouseMove",
    "OpenDirectory",
    "QueueEvent",
    "RestartStatement",
    "RollForward",
    "RollbackToIdentifier",
    "Screenshot",
    "Scroll",
    # `GamepadCalibrate` — documented Ren'Py action that invokes the
    # gamepad calibration routine
    # (https://www.renpy.org/doc/html/screen_actions.html).
    # Previously missed here, causing RPY206 false positives on
    # `textbutton "Calibrate" action GamepadCalibrate()`.
    "GamepadCalibrate",
}
