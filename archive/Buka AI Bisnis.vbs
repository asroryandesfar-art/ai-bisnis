Option Explicit

Dim shell, testMode, projectDir, command, attempts, port, dashboardUrl
Set shell = CreateObject("WScript.Shell")
testMode = WScript.Arguments.Named.Exists("test")
projectDir = "C:\Users\asror\OneDrive\Dokumen\ai bisnis"

Function HttpReady(url)
  On Error Resume Next
  Dim http
  Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
  http.SetTimeouts 2000, 2000, 2000, 2000
  http.Open "GET", url, False
  http.Send
  HttpReady = (Err.Number = 0 And http.Status >= 200 And http.Status < 400)
  Err.Clear
  On Error GoTo 0
End Function

Function FindReadyPort()
  Dim candidate
  FindReadyPort = 0

  For Each candidate In Array(8000, 8001, 8002, 8010)
    If HttpReady("http://127.0.0.1:" & candidate & "/health") And HttpReady("http://127.0.0.1:" & candidate & "/dashboard") Then
      FindReadyPort = candidate
      Exit Function
    End If
  Next
End Function

port = FindReadyPort()
If port = 0 Then
  command = "cmd.exe /d /c cd /d """ & projectDir & """ && call start_bg.cmd"
  shell.Run command, 0, False
End If

For attempts = 1 To 120
  port = FindReadyPort()
  If port <> 0 Then
    dashboardUrl = "http://127.0.0.1:" & port & "/dashboard"
    If testMode Then
      WScript.Echo "READY " & dashboardUrl
    Else
      shell.Run dashboardUrl, 1, False
    End If
    WScript.Quit 0
  End If
  WScript.Sleep 1000
Next

If testMode Then
  WScript.Echo "FAILED: AI Bisnis did not become ready. Check run_server.err.log."
Else
  shell.Popup "AI Bisnis belum dapat dibuka. Periksa run_server.err.log.", 10, "AI Bisnis", 48
End If

WScript.Quit 1
