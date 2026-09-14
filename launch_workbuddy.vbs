' WorkBuddy launcher: start WorkBuddy (with CDP for handle/API integration) + monitor GUI
Set sh = CreateObject("WScript.Shell")

' Start WorkBuddy main program with remote debugging port (for API balance read / model select)
sh.Run """C:\Program Files\WorkBuddy\WorkBuddy.exe"" --remote-debugging-port=9222", 1, False

' Start monitor GUI (pythonw, no console window)
sh.Run """F:\ANACONDA\1\pythonw.exe"" ""C:\Users\UserX\Documents\Codex\2026-09-09\hi\outputs\workbuddy-monitor\workbuddy_gui.py""", 0, False
