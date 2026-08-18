@echo off
title AVIS - Monitor de Oneways : Instalacion
rem ---------------------------------------------------------------
rem  Se instala para el USUARIO actual: NO hace falta ser administrador
rem  y Windows NO debe pedir permisos en ningun momento.
rem  Por eso NO se usa un .exe autoextraible: Windows aplica su
rem  "deteccion de instaladores" a los .exe sin manifiesto y saca el
rem  aviso de administrador. Un .bat nunca eleva.
rem ---------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
