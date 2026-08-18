@echo off
title AVIS - Monitor de Oneways : Desinstalar
echo.
echo   Se va a quitar el Monitor de Oneways de este equipo:
echo     - la tarea programada diaria
echo     - la escucha de comandos de Telegram
echo     - los accesos directos
echo     - la carpeta del programa
echo.
echo   NO se toca nada de Rentway.
echo.
set /p R=  Continuar? (S/N):
if /I not "%R%"=="S" goto :fin

echo.
echo   Quitando la tarea programada...
schtasks /Delete /TN "AVIS - Monitor de Oneways (diario)" /F >nul 2>&1

echo   Cerrando el programa si estuviera abierto...
taskkill /F /IM AvisMonitorOneways.exe >nul 2>&1

echo   Borrando accesos directos...
del "%USERPROFILE%\Desktop\AVIS Monitor de Oneways.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\AVIS Monitor de Oneways.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AVIS Monitor - escucha Telegram.lnk" >nul 2>&1

echo   Borrando la carpeta del programa...
rmdir /s /q "%LOCALAPPDATA%\AvisMonitorOneways" >nul 2>&1

echo.
echo   Hecho.
echo   Si este era el equipo que vigilaba y usabais carpeta compartida
echo   (senal.txt), borra alli motor_activo.json para que otro portatil
echo   tome el relevo sin esperar 15 minutos.
echo.
:fin
pause
