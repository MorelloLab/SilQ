@ECHO OFF

pushd %~dp0

REM Command file for Sphinx documentation

if "%SPHINXBUILD%" == "" (
	set SPHINXBUILD=python -msphinx
)
set SOURCEDIR=.
set BUILDDIR=../../SilQ-documentation
set SPHINXPROJ=SilQ

if "%1" == "" goto help

%SPHINXBUILD% >NUL 2>NUL
if errorlevel 9009 (
	echo.
	echo.The Sphinx module was not found. Make sure you have Sphinx installed,
	echo.then set the SPHINXBUILD environment variable to point to the full
	echo.path of the 'sphinx-build' executable. Alternatively you may add the
	echo.Sphinx directory to PATH.
	echo.
	echo.If you don't have Sphinx installed, grab it from
	echo.http://sphinx-doc.org/
	exit /b 1
)


if "%1" == "gh-pages" (
    echo.Updating gh-pages
    set currentdir=%cd%
    echo current dir is %currentdir%
    cd ../
    echo 1
    git checkout gh-pages
    echo 2
    cd %currentdir%
    echo 3
    xcopy /ys "%BUILDDIR%/html" ..
    echo 4
    git add -A
    git commit -m "Updating gh-pages"
    git push
    cd ../
    git checkout master
    cd %currentdir%
    goto end
)

sphinx-apidoc -o _modules ../silq

%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%

goto end

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%

:end
popd
