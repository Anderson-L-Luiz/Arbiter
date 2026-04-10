@echo off
cd /d "C:\Users\ander\PROJECTS\AI_supervision\Arbiter"
set PYTHONIOENCODING=utf-8
"C:\Users\ander\AppData\Local\Python\bin\python.exe" -c "import sys,os; sys.argv=['headless', r'C:\Users\ander\PROJECTS\AI_supervision\mafra-rionegro-dashboard', open(r'C:\Users\ander\PROJECTS\AI_supervision\Arbiter\_task.txt','r',encoding='utf-8').read(), '2', '9.0']; from arbiter.headless import main; main()" > "C:\Users\ander\PROJECTS\AI_supervision\Arbiter\_arbiter.out" 2>&1
