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
---------------------
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

# =============================================================================
# Runtime-provided names — recognized as "declared" without user default/define
# =============================================================================
BUILTIN_SYMBOLS: set[str] = {
    # Mutable runtime namespaces.
    "config",
    "persistent",
    "renpy",
    "audio",
    "currentuser",
    "gui",
    "layout",
    "store",
    "ui",
    "im",
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
    "style",
    "who",
    "what",
    "prefix_",
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
    "reset",
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
    # Python's builtins (len, range, True, ...). Splatted at the end
    # so the set is constructed in one call — same shape as before
    # the extraction.
    *dir(builtins),
}


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
