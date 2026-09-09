' WorkBuddy launcher: start WorkBuddy + monitor GUI (no console window)
Set sh = CreateObject("WScript.Shell")

' Start WorkBuddy main program
sh.Run """C:\Program Files\WorkBuddy\WorkBuddy.exe""", 1, False

' Start monitor GUI (pythonw, no console window)
sh.Run """F:\ANACONDA\1\pythonw.exe"" ""C:\Users\UserX\Documents\Codex\2026-09-09\hi\outputs\workbuddy-monitor\workbuddy_gui.py""", 0, False
