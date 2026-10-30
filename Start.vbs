Option Explicit
Dim shell, fs, base, runtime, command
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
base = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
runtime = base & "\runtime\pythonw.exe"
If Not fs.FileExists(runtime) Then runtime = base & "\.venv\Scripts\pythonw.exe"
If Not fs.FileExists(runtime) Then
    MsgBox "Python runtime missing. Please see docs/DESKTOP.md.", 48, "StyleMate"
    WScript.Quit 1
End If
command = Chr(34) & runtime & Chr(34) & " " & Chr(34) & base & "\desktop.py" & Chr(34)
shell.Run command, 0, False
