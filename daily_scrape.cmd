@echo off
rem Daily PC Hunt scrape (run by the Windows task "PC Hunt daily scrape"), then publish the website to GitHub Pages.
rem Log: data\logs\<date>.log, console output: data\logs\task.out
cd /d "%~dp0"
"%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" -X utf8 -m pchunt.scrape >> "data\logs\task.out" 2>&1
"%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" -X utf8 -m pchunt.publish >> "data\logs\task.out" 2>&1
