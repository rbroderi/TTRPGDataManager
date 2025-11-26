pushd %~dp0
call makeUML.bat < NUL
miktex-lualatex proposal.tex
miktex-lualatex proposal.tex
miktex-lualatex proposal.tex
popd
pause