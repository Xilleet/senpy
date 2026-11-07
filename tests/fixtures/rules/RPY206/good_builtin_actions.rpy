# RPY206: built-in screen action factories must NOT be flagged.
#
# These functions return an Action object when called with `()` in the
# `action` slot — they do not "execute immediately during screen render".
# Reference: https://www.renpy.org/doc/html/screen_actions.html
#
# Originally found as false positives in:
#   corpus/renpy_template/game/screens.rpy:667, 679, 752
#   corpus/learntocode/game/screens.rpy (multiple)
#
# Specifically missing from the allowlist (verified by running senpy
# against the minimal fixture): FilePagePrevious, FilePageNext,
# InvertSelected. The full audit against the Ren'Py screen_actions
# docs page surfaced a longer list of missing entries, all added to
# BUILTIN_ACTIONS in senpy/core/constants.py.

screen file_actions():
    textbutton "Prev" action FilePagePrevious()
    textbutton "Next" action FilePageNext()
    textbutton "Auto" action FilePage("auto")
    textbutton "Quick" action FilePage("quick")
    textbutton "Save" action FileSave(1, page="quick")
    textbutton "Load" action FileLoad(1, page="quick")
    textbutton "Delete" action FileDelete(1, page="quick")
    textbutton "Screenshot" action FileTakeScreenshot()
    textbutton "QSave" action QuickSave()
    textbutton "QLoad" action QuickLoad()

screen navigation_actions():
    textbutton "Main" action MainMenu()
    textbutton "Start" action Start()
    textbutton "Quit" action Quit()
    textbutton "Help" action Help()
    textbutton "Hide UI" action HideInterface()
    textbutton "Open URL" action OpenURL("https://renpy.org")
    textbutton "ShowTransient" action ShowTransient("overlay")
    textbutton "ShowMenu" action ShowMenu("preferences")
    textbutton "Rollback" action Rollback()
    textbutton "Skip" action Skip()
    textbutton "Notify" action Notify("Hello")
    textbutton "Confirm" action Confirm("Are you sure?")
    textbutton "Restart" action RestartStatement()
    textbutton "RollForward" action RollForward()
    textbutton "Screenshot" action Screenshot()

screen data_actions():
    textbutton "Toggle" action ToggleScreenVariable("flag")
    textbutton "SetLocal" action SetLocalVariable("x", 1)
    textbutton "ToggleLocal" action ToggleLocalVariable("x")
    textbutton "Cycle" action CycleVariable("mode", ["a", "b"])
    textbutton "CycleField" action CycleField("obj", "field", ["a", "b"])
    textbutton "Increment" action IncrementVariable("counter", 1)
    textbutton "IncrementField" action IncrementField("obj", "field", 1)
    textbutton "SetDict" action SetDict("d", "key", "value")
    textbutton "ToggleDict" action ToggleDict("d", "key")
    textbutton "AddToSet" action AddToSet("s", "value")

screen audio_actions():
    textbutton "Play" action Play("music", "bgm.ogg")
    textbutton "Stop" action Stop("music")
    textbutton "Queue" action Queue("music", "bgm.ogg")
    textbutton "PauseAudio" action PauseAudio("music", True)
    textbutton "SetMixer" action SetMixer("music", 0.5)
    textbutton "SetMute" action SetMute("music", True)
    textbutton "ToggleMute" action ToggleMute("music")
    textbutton "GetMixer" action GetMixer("music")

screen focus_actions():
    textbutton "Capture" action CaptureFocus("name")
    textbutton "Clear" action ClearFocus()
    textbutton "ToggleFocus" action ToggleFocus("name")

screen selection_actions():
    textbutton "Invert" action InvertSelected()
    textbutton "SelectedIf" action SelectedIf(True)
    textbutton "SensitiveIf" action SensitiveIf(True)
    textbutton "Continue" action Continue()
    textbutton "Scroll" action Scroll("viewport", "vertical")
    textbutton "MouseMove" action MouseMove(100, 200)
    textbutton "QueueEvent" action QueueEvent("test")

screen misc_actions():
    textbutton "Copy" action CopyToClipboard("text")
    textbutton "EditFile" action EditFile("script.rpy")
    textbutton "OpenDir" action OpenDirectory("game")
    textbutton "DisableInput" action DisableAllInputValues()
    textbutton "ExecJS" action ExecJS("alert(1)")
    textbutton "DownloadSync" action DownloadSync()
    textbutton "UploadSync" action UploadSync()
