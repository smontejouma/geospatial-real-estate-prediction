@echo off
setlocal enabledelayedexpansion

REM Snapshots trimestrales OSM Andalucia

SET OSMIUM=osmium
SET OUTPUT_DIR=.\dataset\osmium
SET INPUT_FILE=%OUTPUT_DIR%\andalucia-internal.osh.pbf

REM Crear carpeta si no existe
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo INICIO DEL PROCESO

echo Archivo fuente: %INPUT_FILE%
echo Carpeta salida: %OUTPUT_DIR%
echo.

REM Guardar hora inicio total
set START_TOTAL=%TIME%

FOR %%Y IN (2015 2016 2017 2018 2019 2020 2021 2022 2023 2024) DO (

    echo ------------------------------------------
    echo Procesando ANHO %%Y
    echo ------------------------------------------
    set START_YEAR=!TIME!

    echo [%%Y Q1] Generando snapshot 31 Marzo...
    %OSMIUM% time-filter "%INPUT_FILE%" %%Y-03-31T23:59:59Z -o "%OUTPUT_DIR%\andalucia_%%Y_Q1.osm.pbf"
    %OSMIUM% cat "%OUTPUT_DIR%\andalucia_%%Y_Q1.osm.pbf" -o "%OUTPUT_DIR%\andalucia_%%Y_Q1.osm"

    echo [%%Y Q2] Generando snapshot 30 Junio...
    %OSMIUM% time-filter "%INPUT_FILE%" %%Y-06-30T23:59:59Z -o "%OUTPUT_DIR%\andalucia_%%Y_Q2.osm.pbf"
    %OSMIUM% cat "%OUTPUT_DIR%\andalucia_%%Y_Q2.osm.pbf" -o "%OUTPUT_DIR%\andalucia_%%Y_Q2.osm"

    echo [%%Y Q3] Generando snapshot 30 Septiembre...
    %OSMIUM% time-filter "%INPUT_FILE%" %%Y-09-30T23:59:59Z -o "%OUTPUT_DIR%\andalucia_%%Y_Q3.osm.pbf"
    %OSMIUM% cat "%OUTPUT_DIR%\andalucia_%%Y_Q3.osm.pbf" -o "%OUTPUT_DIR%\andalucia_%%Y_Q3.osm"

    echo [%%Y Q4] Generando snapshot 31 Diciembre...
    %OSMIUM% time-filter "%INPUT_FILE%" %%Y-12-31T23:59:59Z -o "%OUTPUT_DIR%\andalucia_%%Y_Q4.osm.pbf"
    %OSMIUM% cat "%OUTPUT_DIR%\andalucia_%%Y_Q4.osm.pbf" -o "%OUTPUT_DIR%\andalucia_%%Y_Q4.osm"

    echo Finalizado anho %%Y
    echo Tiempo aproximado anho %%Y: !START_YEAR! -^> !TIME!
    echo.
)

echo TODOS LOS SNAPSHOTS GENERADOS

echo Archivos guardados en: %OUTPUT_DIR%
echo Hora inicio: %START_TOTAL%
echo Hora fin: %TIME%

pause