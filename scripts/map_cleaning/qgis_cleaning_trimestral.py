import os
import sys
import glob
from typing import Dict
from pathlib import Path
import yaml 

# Leer config.yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

QGIS_PREFIX_PATH = cfg["qgis"]["prefix_path"]

TIF_PATH = str((PROJECT_ROOT / cfg["paths"]["tif_path"]).resolve())
OSM_FOLDER = str((PROJECT_ROOT / cfg["paths"]["osm_folder"]).resolve())
OUTPUT_BASE = str((PROJECT_ROOT / cfg["paths"]["output_base"]).resolve())

BUFFER_M = float(cfg["run"]["buffer_m"])
ANHOS = list(cfg["run"]["years"])
TRIMESTRES = list(cfg["run"]["quarters"])

OSM_LAYERS = dict(cfg["osm_layers"])


def setup_qgis(prefix_path: str):
    """Configura entorno PyQGIS (standalone en Windows) e inicializa QgsApplication."""
    sys.path.append(os.path.join(prefix_path, "apps", "qgis", "python"))
    sys.path.append(os.path.join(prefix_path, "apps", "qgis", "python", "plugins"))

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(prefix_path, "apps", "Qt5", "plugins")
    os.environ["PATH"] += ";" + os.path.join(prefix_path, "bin")
    os.environ["PATH"] += ";" + os.path.join(prefix_path, "apps", "qgis", "bin")

    from qgis.core import QgsApplication
    qgs = QgsApplication([], False)
    qgs.initQgis()

    from osgeo import gdal
    gdal.PushErrorHandler("CPLQuietErrorHandler")

    from processing.core.Processing import Processing
    Processing.initialize()

    return qgs


def load_osm_layers(osm_path: str) -> Dict[str, "QgsVectorLayer"]:
    """Carga subcapas estándar del .osm."""
    from qgis.core import QgsVectorLayer

    layers: Dict[str, QgsVectorLayer] = {}
    for alias, layername in OSM_LAYERS.items():
        vl = QgsVectorLayer(f"{osm_path}|layername={layername}", alias, "ogr")
        if vl.isValid():
            layers[alias] = vl
        else:
            print(f"[WARN] Capa OSM no válida: {alias} ({layername})")
    return layers


def build_buffer_layer(raster, buffer_m: float):
    """
    Construye el buffer (extent del raster + buffer) y lo devuelve como layer en memoria.
    """
    from qgis.core import QgsProcessingFeedback
    import processing

    feedback = QgsProcessingFeedback()

    extent_layer = processing.run(
        "qgis:polygonfromlayerextent",
        {"INPUT": raster, "OUTPUT": "memory:extent"},
        feedback=feedback,
    )["OUTPUT"]

    buffer_layer = processing.run(
        "native:buffer",
        {
            "INPUT": extent_layer,
            "DISTANCE": float(buffer_m),
            "SEGMENTS": 5,
            "DISSOLVE": True,
            "END_CAP_STYLE": 0,
            "JOIN_STYLE": 0,
            "MITER_LIMIT": 2,
            "OUTPUT": "memory:buffer",
        },
        feedback=feedback,
    )["OUTPUT"]

    return buffer_layer


def process_osm_with_prebuilt_buffer(
    raster,
    buffer_layer,
    osm_path: str,
    output_folder: str,
    sufijo: str,
) -> None:
    """
    Procesa un OSM usando un buffer_layer ya calculado.
    """
    from qgis.core import QgsProcessingFeedback
    import processing

    feedback = QgsProcessingFeedback()

    capas = load_osm_layers(osm_path)

    if "multipolygons" in capas:
        capas["multipolygons"] = processing.run(
            "qgis:fixgeometries",
            {"INPUT": capas["multipolygons"], "OUTPUT": "memory:multipolygons_fixed"},
            feedback=feedback,
        )["OUTPUT"]

    os.makedirs(output_folder, exist_ok=True)

    crs_target = raster.crs()
    crs_target_id = crs_target.authid()

    for nombre, capa in capas.items():
        # Reproyectar a CRS del raster (si no coincide)
        capa_reproj = processing.run(
            "native:reprojectlayer",
            {"INPUT": capa, "TARGET_CRS": crs_target, "OUTPUT": "memory:osm_reproj"},
            feedback=feedback,
        )["OUTPUT"]

        # Arreglar geometrías antes del clip
        capa_fixed = processing.run(
            "qgis:fixgeometries",
            {"INPUT": capa_reproj, "OUTPUT": "memory:osm_fixed"},
            feedback=feedback,
        )["OUTPUT"]

        out_path = os.path.join(output_folder, f"{nombre}_{sufijo}_recortado.gpkg")
        resultado = processing.run(
            "qgis:clip",
            {"INPUT": capa_fixed, "OVERLAY": buffer_layer, "OUTPUT": out_path},
            feedback=feedback,
        )["OUTPUT"]

        print(f"[OK] {nombre} exportado en {crs_target_id}: {resultado}")


def main() -> None:
    qgs = setup_qgis(QGIS_PREFIX_PATH)
    try:
        from qgis.core import QgsRasterLayer

        tif_name = os.path.splitext(os.path.basename(TIF_PATH))[0]

        # Cargar raster
        raster = QgsRasterLayer(TIF_PATH, "raster")
        if not raster.isValid():
            raise ValueError(f"Raster no válido: {TIF_PATH}")

        # Calcular buffer
        print("[INFO] Calculando buffer del raster (una sola vez)...")
        buffer_layer = build_buffer_layer(raster, BUFFER_M)
        print("[INFO] Buffer calculado.")

        for anho in ANHOS:
            for q in TRIMESTRES:
                patrones = glob.glob(os.path.join(OSM_FOLDER, f"*{anho}*_{q}*.osm"))
                if not patrones:
                    print(f"[WARN] No encontré .osm para {anho} {q} en {OSM_FOLDER}")
                    continue

                for osm_path in patrones:
                    osm_path = os.path.abspath(osm_path)
                    if not os.path.isfile(osm_path):
                        continue

                    output_folder = os.path.join(OUTPUT_BASE, f"geometrias{anho}_{tif_name}", q)
                    print(f"\n[->] Procesando {anho} {q}: {osm_path}")

                    process_osm_with_prebuilt_buffer(
                        raster=raster,
                        buffer_layer=buffer_layer,
                        osm_path=osm_path,
                        output_folder=output_folder,
                        sufijo=f"{anho}_{q}",
                    )
    finally:
        qgs.exitQgis()


if __name__ == "__main__":
    main()
