@echo off
cd /d "C:\Users\ander\PROJECTS\AI_supervision\Arbiter"
"C:\Users\ander\AppData\Local\Python\bin\python.exe" -m arbiter.app --task-file "_task.txt" "C:\Users\ander\PROJECTS\AI_supervision\mafra-rionegro-dashboard" --rounds 3 --stop-score 9.0
pause
