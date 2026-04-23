@echo off
:: Ensure python\ folder exists with embedded Python + pip + packages
cd /d "%~dp0"

if exist "python\python.exe" goto :install_deps

echo Downloading Python embeddable...
set PYVER=3.12.9
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip' -OutFile python-embed.zip; Expand-Archive python-embed.zip -DestinationPath python; Remove-Item python-embed.zip"
echo Enabling site-packages...
powershell -Command "$f = Get-ChildItem python -Filter 'python*._pth'; $c = Get-Content $f.FullName; $c = $c -replace '#import site','import site'; $c += \"`n..\"; Set-Content $f.FullName $c"
echo Installing pip...
powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile get-pip.py"
python\python.exe get-pip.py --no-warn-script-location
del get-pip.py

:install_deps
python\python.exe -m pip install -q -r requirements.txt
