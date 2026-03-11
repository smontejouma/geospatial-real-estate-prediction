# Geospatial Real Estate Prediction

Pipeline geoespacial y de aprendizaje automático para la construcción de un dataset panel a nivel de distrito y el análisis predictivo de precios de vivienda a partir de datos de **OpenStreetMap** y precios inmobiliarios históricos.

Este repositorio contiene el código desarrollado en el **Trabajo Fin de Máster (TFM)** para generar variables territoriales a partir de datos geoespaciales y utilizarlas en modelos predictivos del mercado inmobiliario.

---

# Descripción del proyecto

El sistema implementa un pipeline completo que permite:

- generar snapshots temporales de OpenStreetMap
- limpiar y recortar datos geoespaciales
- preprocesar entidades geográficas
- calcular variables territoriales agregadas por distrito
- integrar precios históricos de vivienda
- construir un dataset longitudinal
- entrenar modelos predictivos

El dataset final combina **dimensiones espaciales y temporales**, permitiendo analizar la evolución de variables urbanas y precios de vivienda a lo largo del tiempo.

Debido a las limitaciones de tamaño de GitHub, algunos archivos de entrada no se incluyen en el repositorio, aunque se indican los enlaces oficiales para descargarlos.

---

# Estructura del repositorio

El repositorio se organiza de la siguiente manera:

```
TFM/
│
├── config.yaml
├── requirements.txt
│
├── dataset/
│   ├── osmium/
│   ├── geospatial/
│   ├── district_level/
│   └── prices/
│
├── dataset_final/
│
├── resultados/
│
└── scripts/
    ├── map_cleaning/
    ├── attributes/
    ├── analisis/
    └── idealista_scrapping_prices.py
```

### Descripción de las carpetas

**dataset/osmium/**  
Contiene los datos históricos de OpenStreetMap y los snapshots temporales generados durante el proceso.

**dataset/geospatial/**  
Incluye datos ráster y capas geoespaciales utilizadas como referencia espacial para el análisis.

**dataset/district_level/**  
Contiene los datasets agregados por municipio, distrito, año y trimestre generados durante el pipeline.

**dataset/prices/**  
Archivos auxiliares relacionados con los precios históricos de vivienda.

**dataset_final/**  
Dataset longitudinal final utilizado para el análisis y modelado.

**resultados/**  
Resultados del modelado, predicciones y archivos derivados del análisis.

**scripts/**  
Scripts del pipeline de procesamiento y notebooks de análisis.

---

# Datos de entrada necesarios

Para ejecutar completamente el pipeline es necesario disponer de los siguientes archivos de entrada.

## Datos históricos de OpenStreetMap

Archivo histórico de OpenStreetMap para Andalucía:

```
andalucia-internal.osh.pbf
```

Este archivo permite reconstruir el estado de OpenStreetMap en distintos momentos temporales.

Puede descargarse desde:

https://osm-internal.download.geofabrik.de/europe/spain/andalucia.html

Debe colocarse en:

```
dataset/osmium/andalucia-internal.osh.pbf
```

---

## Datos ráster de clasificación territorial

Archivo ráster utilizado como referencia espacial:

```
classification_30SUF.tif
```

Este archivo corresponde al tile **T30SUF** del producto Sentinel-2.

Puede descargarse desde:

https://sentiwiki.copernicus.eu/web/s2-products

Debe colocarse en:

```
dataset/geospatial/classification_30SUF.tif
```

---

## División administrativa por distritos

Capas geoespaciales que definen los límites distritales de los municipios analizados.

Estas capas se encuentran en:

```
dataset/district_level/
```

y se utilizan como unidades espaciales para el cálculo de variables territoriales.

---

# Requisitos

## Dependencias Python

Instalar las dependencias mediante:

```
pip install -r requirements.txt
```

---

## Osmium

La generación de snapshots temporales requiere disponer de **Osmium**.  
Se recomienda instalarlo en un entorno específico de **Conda**.

---

## QGIS / PyQGIS

El proceso de limpieza y recorte espacial utiliza **PyQGIS**, por lo que debe ejecutarse desde:

- **OSGeo4W Shell**, o
- un entorno Python con QGIS correctamente configurado.

---

# Ejecución del pipeline

Todos los comandos deben ejecutarse desde la **carpeta raíz del proyecto**.

---

# 1. Generación de snapshots temporales de OpenStreetMap

Este paso genera snapshots trimestrales a partir del archivo histórico `.osh.pbf`.

Script utilizado:

```
scripts/map_cleaning/generar_osm_trimestral.bat
```

Ejecución desde **Anaconda Prompt**:

```
scripts\map_cleaning\generar_osm_trimestral.bat
```

Salida:

```
dataset/osmium/*.osm
```

Tiempo aproximado de ejecución:

```
~4 minutos
```

---

# 2. Limpieza y recorte espacial

Se realiza la limpieza y recorte de los datos utilizando **QGIS y PyQGIS**.

Ejecución desde **OSGeo4W Shell**:

```
python scripts/map_cleaning/qgis_cleaning_trimestral.py
```

Este proceso genera capas geográficas separadas según su tipo de geometría (puntos, líneas, multilíneas y polígonos), que constituyen la base para el cálculo posterior de variables territoriales.

Tiempo aproximado:

```
~3 horas
```

Esta es la fase más costosa computacionalmente del pipeline.

---

# 3. Preprocesamiento de atributos geográficos

Se limpian y estructuran los atributos de las entidades de OpenStreetMap, extrayendo etiquetas relevantes y clasificando las entidades en distintas categorías funcionales.

Script:

```
python scripts/attributes/preprocess_trimestral.py
```

Ejemplos de ejecución:

Procesar todas las geometrías:

```
python scripts/attributes/preprocess_trimestral.py
```

Procesar solo puntos:

```
python scripts/attributes/preprocess_trimestral.py --points
```

Procesar solo líneas:

```
python scripts/attributes/preprocess_trimestral.py --lines
```

Forzar reprocesado:

```
python scripts/attributes/preprocess_trimestral.py --force
```

Limitar el procesamiento a determinados años o trimestres:

```
python scripts/attributes/preprocess_trimestral.py --years 2024
python scripts/attributes/preprocess_trimestral.py --quarters Q1 Q4
```

Tiempo aproximado:

```
~16 minutos
```

---

# 4. Cálculo de variables agregadas por distrito

En esta etapa se calculan indicadores territoriales agregados a nivel de distrito, incluyendo número de puntos de interés, superficies por tipo de uso del suelo, longitud de infraestructuras, densidades espaciales y otros indicadores urbanos.

Ejecución:

```
python scripts/attributes/var_por_distrito.py
```

Salida:

```
dataset/district_level/
```

Tiempo aproximado:

```
~1 hora y 27 minutos
```

---

# 5. Obtención de precios inmobiliarios históricos

Los precios se obtienen mediante **web scraping del portal Idealista**.

Script:

```
scripts/idealista_scrapping_prices.py
```

Salida:

```
prices_template_districts_filled.xlsx
```

---

# 6. Integración de precios inmobiliarios

Se integran los precios con las variables geoespaciales generadas.

Script:

```
python scripts/attributes/add_price.py
```

Salida:

```
*_features_with_price_*.csv
```

Tiempo aproximado:

```
~8 segundos
```

---

# 7. Construcción del dataset final

Se consolidan todos los archivos generados en un único dataset longitudinal.

Script:

```
python scripts/attributes/form_dataset.py
```

Salida:

```
dataset_final/dataset_distritos_long.csv
dataset_final/dataset_distritos_long.parquet
```

Tiempo aproximado:

```
~2 segundos
```

---

# Análisis y modelado

Los notebooks se encuentran en:

```
scripts/analisis/
```

### analisis.ipynb

Incluye:

- análisis exploratorio de datos
- análisis espacial
- análisis temporal
- ingeniería de variables

### pipeline_modelado.ipynb

Incluye:

- entrenamiento de modelos predictivos
- validación y evaluación
- comparación de algoritmos
- generación del modelo final

---

# Material incluido en el repositorio

El repositorio incluye:

- scripts completos del pipeline
- dataset final generado
- notebooks de análisis y modelado
- resultados del modelado
- modelos entrenados de tamaño manejable

Los archivos de entrada de gran tamaño no se incluyen en el repositorio, pero pueden descargarse desde sus fuentes oficiales siguiendo las instrucciones indicadas.

---

# Reproducibilidad

El pipeline puede reproducirse completamente descargando los datos externos indicados y ejecutando los scripts en el orden descrito.

No obstante, para facilitar la reutilización del trabajo, el repositorio incluye también el **dataset final generado** y los **resultados principales del modelado**, evitando así tener que ejecutar nuevamente las etapas de procesamiento geoespacial más costosas.

---

# Autor

**Sergio Montejouma**  
Trabajo Fin de Máster