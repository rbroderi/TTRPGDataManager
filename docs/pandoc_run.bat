pushd %~dp0
pandoc --pdf-engine lualatex homework1.tex -o homework1.docx
popd
pause