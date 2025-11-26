@ECHO OFF
for %%f in (*.*uml) DO (
    echo %%f
    C:\Users\richa\plantuml\plantuml-1.2025.9.jar -teps "%%f"
)  
pause