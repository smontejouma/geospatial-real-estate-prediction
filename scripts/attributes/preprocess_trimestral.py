import argparse
import os
import re
import glob
from pathlib import Path

import pandas as pd
import geopandas as gpd
import yaml 



# Localiza config.yaml 
def find_project_root(start: Path, config_name: str = "config.yaml") -> Path:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / config_name).is_file():
            return p
    raise FileNotFoundError(f"No encontré {config_name} subiendo desde: {start}")


PROJECT_ROOT = find_project_root(Path(__file__).parent)
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

#config general
QGIS_PREFIX_PATH = cfg.get("qgis", {}).get("prefix_path", "")  # no se usa en este script ahora mismo
EPSG_DEFAULT = int(cfg["crs"]["epsg_default"])

DATASET_DIR = str((PROJECT_ROOT / cfg["paths"]["dataset_dir"]).resolve())
TIF_PATH = str((PROJECT_ROOT / cfg["paths"]["tif_path"]).resolve())

DEFAULT_YEARS = list(cfg["run"]["years"])
DEFAULT_QUARTERS = list(cfg["run"]["quarters"])

POINTS_EXTRACT_KEYS = tuple(cfg["preprocess"]["points_extract_keys"])
POINTS_DROP_ALWAYS = list(cfg["preprocess"]["points_drop_always"])
VALID_ROUTES = set(cfg["preprocess"]["multilines_valid_routes"])

POLY_BAD_BOUNDARIES = set(cfg["polygons"]["bad_boundaries"])
POLY_NEEDED_COLUMNS = list(cfg["polygons"]["needed_columns"])


# Grupos grandes (groups.py)

from groups import (
    _norm,
    PUBLIC_TRANSPORT_GROUP,
    HIGHWAY_GROUP,
    AMENITY_GROUP,
    LEISURE_SPORT_VALUES,
    RAILWAY_CONTROL_VALUES,
    HIGHWAY_LINE_GROUP,
    WATERWAY_LINE_GROUP,
    RAILWAY_LINE_GROUP,
    AERIALWAY_LINE_GROUP,
    BARRIER_LINE_GROUP,
    MANMADE_LINE_GROUP,
)



# Utilidades generales

def _extract_tag(series: pd.Series, key: str) -> pd.Series:
    s = series.fillna("").astype(str)
    pat = rf'"{re.escape(key)}"\s*=>\s*"([^"]+)"'
    return s.str.extract(pat, expand=False)

def to_utm(gdf: gpd.GeoDataFrame, epsg: int = EPSG_DEFAULT) -> gpd.GeoDataFrame:
    if gdf.crs is None or gdf.crs.to_epsg() != epsg:
        return gdf.to_crs(epsg)
    return gdf

def _dedup_paths(paths):
    seen = set()
    out = []
    for p in paths:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out

def _should_run(flag_selected: bool, out_path: str, force: bool) -> bool:
    if not flag_selected:
        return False
    return force or (not os.path.exists(out_path))



# Mapeos POI 

def _amenity_to_group(v: str) -> str:
    v = _norm(v)
    if not v:
        return ""
    return AMENITY_GROUP.get(v, "other_amenity")

def _public_transport_to_group(v: str) -> str:
    v = _norm(v)
    if not v:
        return ""
    return PUBLIC_TRANSPORT_GROUP.get(v, "pt_other")

def _highway_to_group(v: str) -> str:
    v = _norm(v)
    if not v:
        return ""
    return HIGHWAY_GROUP.get(v, "highway_other")

def _leisure_to_group(v: str) -> str:
    v = _norm(v)
    if not v:
        return ""
    return "leisure_sport" if v in LEISURE_SPORT_VALUES else "leisure_access"

def _natural_to_group(_: str) -> str:
    return "nature"

def _choose_domain_value_group(row):
    # 1) public_transport
    pt = _norm(row.get("public_transport", ""))
    if pt:
        return "public_transport", pt, _public_transport_to_group(pt)

    # 2) railway / metro
    rw = _norm(row.get("railway", ""))
    st = _norm(row.get("station", ""))
    sb = _norm(row.get("subway", ""))

    if rw == "subway_entrance":
        return "railway", "subway_entrance", "pt_entrance"

    if rw == "station" and (st == "subway" or sb == "yes"):
        return "railway", "subway_station", "pt_station"

    if rw in ("station", "halt"):
        return "railway", rw, "pt_station"
    if rw == "tram_stop":
        return "railway", rw, "pt_stop"

    if rw in RAILWAY_CONTROL_VALUES or rw == "level_crossing":
        return "railway", rw, "traffic_control"

    # 3) amenity
    am = _norm(row.get("amenity", ""))
    if am:
        return "amenity", am, _amenity_to_group(am)

    # 4) healthcare / shop / tourism
    hc = _norm(row.get("healthcare", ""))
    if hc:
        return "healthcare", hc, "healthcare"

    sh = _norm(row.get("shop", ""))
    if sh:
        return "shop", sh, "shop"

    tu = _norm(row.get("tourism", ""))
    if tu:
        return "tourism", tu, "tourism"

    # 5) office
    off = _norm(row.get("office", ""))
    if off:
        if off == "government":
            gov = _norm(row.get("government", ""))
            return "office", f"government:{gov}" if gov else "government", "public_services"
        return "office", off, "office_services"

    # 6) playground=*
    pg = _norm(row.get("playground", ""))
    if pg:
        return "playground", pg, "leisure_access"

    # 7) emergency / power
    em = _norm(row.get("emergency", ""))
    if em:
        return "emergency", em, "utilities"

    pw = _norm(row.get("power", ""))
    if pw:
        return "power", pw, "utilities"

    # 8) leisure
    le = _norm(row.get("leisure", ""))
    if le:
        return "leisure", le, _leisure_to_group(le)

    # 9) historic
    hi = _norm(row.get("historic", ""))
    if hi:
        return "historic", hi, "culture_leisure"

    # 10) natural
    na = _norm(row.get("natural", ""))
    if na:
        return "natural", na, _natural_to_group(na)

    # 11) traffic_calming
    tc = _norm(row.get("traffic_calming", ""))
    if tc:
        return "traffic_calming", tc, "traffic_control"

    # 12) highway
    hwy = _norm(row.get("highway", ""))
    if hwy:
        return "highway", hwy, _highway_to_group(hwy)

    # 13) man_made / place
    mm = _norm(row.get("man_made", ""))
    if mm:
        return "man_made", mm, "man_made"

    pl = _norm(row.get("place", ""))
    if pl:
        return "place", pl, "place"

    # 14) ford
    fd = _norm(row.get("ford", ""))
    if fd:
        return "ford", fd, "road_infra"

    # 15) sport
    sp = _norm(row.get("sport", ""))
    if sp:
        return "sport", sp, "culture_leisure"

    ts = _norm(row.get("traffic_sign", ""))
    if ts:
        return "traffic_sign", ts, "traffic_control"

    ti = _norm(row.get("traffic_island", ""))
    if ti:
        return "traffic_island", ti, "traffic_control"

    return "unknown", "", "unknown"



# PREPROCESADO PUNTOS

def preprocess_points(points_path, out_path, epsg: int = EPSG_DEFAULT):

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception as e:
            raise RuntimeError(
                f"No pude sobrescribir {out_path}. Cierra QGIS u otro programa que lo use. Error: {e}"
            )

    gdf = gpd.read_file(points_path)
    gdf = to_utm(gdf, epsg)

    # extraer tags de other_tags si faltan
    if "other_tags" in gdf.columns:
        for k in POINTS_EXTRACT_KEYS:
            if k not in gdf.columns or gdf[k].isna().all():
                gdf[k] = _extract_tag(gdf["other_tags"], k)
    else:
        for k in POINTS_EXTRACT_KEYS:
            if k not in gdf.columns:
                gdf[k] = pd.NA

    for col in POINTS_DROP_ALWAYS:
        if col in gdf.columns:
            gdf = gdf.drop(columns=[col])

    # drop columnas 100% nulas
    for col in list(gdf.columns):
        if col != "geometry" and gdf[col].isna().all():
            gdf = gdf.drop(columns=[col])

    # derivadas
    tmp = gdf.apply(_choose_domain_value_group, axis=1, result_type="expand")
    tmp.columns = ["poi_domain", "poi_value", "poi_group"]
    gdf = pd.concat([gdf, tmp], axis=1)

    # address points (addr:*)
    if "other_tags" in gdf.columns:
        has_addr = gdf["other_tags"].fillna("").astype(str).str.contains('\"addr:', regex=False)
        is_unknown = gdf["poi_group"].fillna("") == "unknown"
        mask = has_addr & is_unknown
        gdf.loc[mask, "poi_domain"] = "address"
        gdf.loc[mask, "poi_value"] = "addr:*"
        gdf.loc[mask, "poi_group"] = "address_point"

    for c in ["poi_domain", "poi_value", "poi_group"]:
        gdf[c] = gdf[c].astype(str)

    gdf.to_file(out_path, driver="GPKG")
    print(f" Points preprocesados: {out_path}")



# PREPROCESADO LÍNEAS

def _map_line_group(v: str, mapping: dict, default: str):
    v = _norm(v)
    if not v:
        return ""
    return mapping.get(v, default)

def _choose_line_domain_value_group(row):
    hwy = _norm(row.get("highway", ""))
    if hwy:
        return "highway", hwy, _map_line_group(hwy, HIGHWAY_LINE_GROUP, "road_other")

    rw = _norm(row.get("railway", ""))
    if rw:
        return "railway", rw, _map_line_group(rw, RAILWAY_LINE_GROUP, "rail_other")

    ww = _norm(row.get("waterway", ""))
    if ww:
        return "waterway", ww, _map_line_group(ww, WATERWAY_LINE_GROUP, "water_other")

    aw = _norm(row.get("aerialway", ""))
    if aw:
        return "aerialway", aw, _map_line_group(aw, AERIALWAY_LINE_GROUP, "aerialway")

    br = _norm(row.get("barrier", ""))
    if br:
        return "barrier", br, _map_line_group(br, BARRIER_LINE_GROUP, "barrier_line")

    mm = _norm(row.get("man_made", ""))
    if mm:
        return "man_made", mm, _map_line_group(mm, MANMADE_LINE_GROUP, "manmade_other")

    return "unknown", "", "other_line"

def preprocess_lines(lines_path, out_path, epsg: int = EPSG_DEFAULT):
    gdf = gpd.read_file(lines_path)
    gdf = to_utm(gdf, epsg)

    tmp = gdf.apply(_choose_line_domain_value_group, axis=1, result_type="expand")
    tmp.columns = ["line_domain", "line_value", "line_group"]
    gdf = pd.concat([gdf, tmp], axis=1)

    for c in ["line_domain", "line_value", "line_group"]:
        gdf[c] = gdf[c].astype(str)

    gdf.to_file(out_path, driver="GPKG")
    print(f" Lines preprocesadas: {out_path}")



# PREPROCESADO MULTILINESTRINGS

def preprocess_multilines(multilines_path, out_path, epsg: int = EPSG_DEFAULT):
    gdf = gpd.read_file(multilines_path)
    gdf = to_utm(gdf, epsg)

    # 1) Mantener solo route
    if "type" in gdf.columns:
        gdf = gdf[gdf["type"].fillna("") == "route"]

    # 2) Extraer route y otras tags
    if "other_tags" in gdf.columns:
        if "route" not in gdf.columns or gdf["route"].isna().all():
            gdf["route"] = _extract_tag(gdf["other_tags"], "route")

        for k in ("ref", "network", "operator"):
            if k not in gdf.columns or gdf[k].isna().all():
                gdf[k] = _extract_tag(gdf["other_tags"], k)
    else:
        if "route" not in gdf.columns:
            gdf["route"] = pd.NA

    # 3) Filtrar rutas relevantes (desde config)
    gdf = gdf[gdf["route"].fillna("").isin(VALID_ROUTES)].copy()

    # 4) Agrupar
    def _route_group(v: str) -> str:
        v = _norm(v)
        if v == "bus":
            return "pt_bus_route"
        if v in ("train", "railway", "light_rail", "tram", "subway"):
            return "pt_rail_route"
        if v == "ferry":
            return "pt_ferry_route"
        return "pt_other_route"

    gdf["route_group"] = gdf["route"].apply(_route_group).astype(str)

    # 5) eliminar columnas 100% nulas
    for col in list(gdf.columns):
        if col != "geometry" and gdf[col].isna().all():
            gdf = gdf.drop(columns=[col])

    gdf.to_file(out_path, driver="GPKG")
    print(f" MultiLineStrings preprocesadas: {out_path}")



# PREPROCESADO POLÍGONOS

def _write_layer(gdf, out_path, layer_name, first=False):
    if gdf is None or len(gdf) == 0:
        print(f"[i] Layer vacía, se omite: {layer_name}")
        return
    mode = "w" if first else "a"
    gdf.to_file(out_path, layer=layer_name, driver="GPKG", mode=mode)
    print(f"[OK] -> {out_path} | layer={layer_name} | n={len(gdf)}")

def preprocess_polygons(multipolygons_path, out_path, epsg: int = EPSG_DEFAULT):
    """
    Crea un GPKG con layers separadas:
      - poly_buildings
      - poly_activity
      - poly_landcover_base
      - poly_infra
      - poly_boundary
      - poly_heritage
      - poly_other
    y elimina boundary=administrative (configurable en config.yaml)
    """

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception as e:
            raise RuntimeError(
                f"No pude sobrescribir {out_path}. Cierra QGIS u otro programa que lo use. Error: {e}"
            )

    gdf = gpd.read_file(multipolygons_path)
    gdf = to_utm(gdf, epsg)

    # asegurar columnas necesarias (desde config)
    for c in POLY_NEEDED_COLUMNS:
        if c not in gdf.columns:
            gdf[c] = pd.NA

    # quitar boundaries no deseadas (desde config)
    gdf = gdf[~gdf["boundary"].fillna("").astype(str).str.strip().isin(POLY_BAD_BOUNDARIES)].copy()

    def _clean_col(colname: str) -> pd.Series:
        s = gdf[colname].fillna("").astype(str).str.strip()
        return s.where(~s.str.upper().isin(["NULL", "<NA>"]), "")

    def _has(colname: str) -> pd.Series:
        return _clean_col(colname) != ""

    def _s(val) -> str:
        if val is None or pd.isna(val):
            return ""
        return str(val).strip()

    # máscaras principales
    m_building  = _has("building")
    m_activity  = _has("amenity") | _has("shop") | _has("tourism") | _has("office") | _has("craft")
    m_landcover = _has("landuse") | _has("leisure") | _has("natural") | _has("water")
    m_infra     = _has("man_made") | _has("aeroway") | _has("barrier") | _has("power") | _has("military")
    m_boundary  = _has("boundary")
    m_heritage  = _has("historic")

    # 1) buildings
    BUILDING_RES = {
        "house","apartments","residential","detached","terrace","bungalow",
        "semidetached_house","semi_detached","semi","yes;apartments","static_caravan"
    }
    BUILDING_COMM = {"commercial","retail","supermarket","kiosk","office","hotel","accommodation"}
    BUILDING_PUBLIC = {
        "school","university","college","hospital","kindergarten","civic",
        "fire_station","public","religious","church","chapel","cathedral","mosque","temple","monastery","museum","theatre"
    }
    BUILDING_IND = {"industrial","warehouse","hangar","storage_tank","silo","farm","farm_auxiliary"}

    b = gdf[m_building].copy()
    bval = b["building"].fillna("").astype(str).str.strip().str.lower()

    def _building_group(v: str) -> str:
        v = (v or "").strip().lower()
        if v in BUILDING_RES:
            return "residential"
        if v in BUILDING_COMM:
            return "commercial"
        if v in BUILDING_PUBLIC or ("church" in v) or ("chapel" in v):
            return "public"
        if v in BUILDING_IND:
            return "industrial"
        return "other_building"

    b["poly_domain"] = "building"
    b["poly_value"] = b["building"].fillna("").astype(str)
    b["poly_group"] = "buildings"
    b["building_group"] = bval.map(_building_group)

    # 2) activity
    def _amenity_group(v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        return AMENITY_GROUP.get(v, "other_amenity")

    def _tourism_group(v: str) -> str:
        v = (v or "").strip().lower()
        if v in {
            "hotel","hostel","guest_house","motel","chalet","apartment","self_catering",
            "self_catering_apartment","self_catering_house","rural_house","camp_site","caravan_site"
        }:
            return "tourism_accommodation"
        if v in {"museum","theme_park","zoo","aquarium","attraction","artwork","viewpoint"}:
            return "tourism_attraction"
        return "tourism_other"

    def _activity_group(row) -> str:
        t = _s(row.get("tourism"))
        if t:
            return _tourism_group(t)

        a = _s(row.get("amenity"))
        if a:
            return _amenity_group(a)

        s_ = _s(row.get("shop"))
        if s_:
            return "shop"

        o = _s(row.get("office"))
        if o:
            return "office"

        c = _s(row.get("craft"))
        if c:
            return "craft"

        return "activity_other"

    def _activity_value(row) -> str:
        for k in ["tourism","amenity","shop","office","craft"]:
            v = _s(row.get(k))
            if v:
                return f"{k}:{v}"
        return ""

    act = gdf[m_activity].copy()
    act["poly_domain"] = "activity"
    act["poly_value"]  = act.apply(_activity_value, axis=1)
    act["poly_group"]  = "activity"
    act["activity_group"] = act.apply(_activity_group, axis=1)

    # 3) infra 
    infra = gdf[m_infra].copy()

    def _infra_value(row) -> str:
        for k in ["aeroway","man_made","power","barrier","military"]:
            v = _s(row.get(k))
            if v:
                return f"{k}:{v}"
        return ""

    infra["poly_domain"] = "infra"
    infra["poly_value"] = infra.apply(_infra_value, axis=1)
    infra["poly_group"] = "infra"

    # 4) boundary 
    boundary = gdf[m_boundary].copy()
    boundary["poly_domain"] = "boundary"
    boundary["poly_value"] = boundary["boundary"].fillna("").astype(str)
    boundary["poly_group"] = "boundary"

    # 5) heritage 
    her = gdf[m_heritage].copy()
    her["poly_domain"] = "historic"
    her["poly_value"] = her["historic"].fillna("").astype(str)
    her["poly_group"] = "heritage"

    #  6) landcover_base 
    covered = m_building | m_activity | m_infra | m_boundary | m_heritage
    land_base = gdf[m_landcover & (~covered)].copy()

    def _land_value(row) -> str:
        for k in ["landuse","natural","leisure","water"]:
            v = _s(row.get(k))
            if v:
                return f"{k}:{v}"
        return ""

    land_base["poly_domain"] = "landcover"
    land_base["poly_value"]  = land_base.apply(_land_value, axis=1)
    land_base["poly_group"]  = "landcover_base"

    # 7) other 
    any_known = m_building | m_activity | m_infra | m_boundary | m_heritage | m_landcover
    other = gdf[~any_known].copy()
    other["poly_domain"] = "other"
    other["poly_value"] = ""
    other["poly_group"] = "other"

    # escribir layers 
    first = True
    _write_layer(land_base, out_path, "poly_landcover_base", first=first); first = False
    _write_layer(boundary,   out_path, "poly_boundary", first=first)
    _write_layer(infra,      out_path, "poly_infra", first=first)
    _write_layer(act,        out_path, "poly_activity", first=first)
    _write_layer(her,        out_path, "poly_heritage", first=first)
    _write_layer(b,          out_path, "poly_buildings", first=first)
    _write_layer(other,      out_path, "poly_other", first=first)

    print(f" Polygons preprocesados (capas separadas): {out_path}")



# MAIN CLI

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocesado OSM por años/trimestres con selección de geometrías.")
    parser.add_argument("--all", action="store_true", help="Ejecuta points + lines + multilines + polygons.")
    parser.add_argument("--points", action="store_true", help="Preprocesa puntos.")
    parser.add_argument("--lines", action="store_true", help="Preprocesa líneas.")
    parser.add_argument("--multilines", action="store_true", help="Preprocesa multilinestrings.")
    parser.add_argument("--polygons", action="store_true", help="Preprocesa multipolygons (sin boundary=administrative).")
    parser.add_argument("--force", action="store_true", help="Fuerza reprocesar aunque exista *_preprocessed.gpkg.")
    parser.add_argument("--years", nargs="*", type=int, default=None, help="Años a procesar (ej: --years 2024 2023).")
    parser.add_argument("--quarters", nargs="*", default=None, help="Trimestres a procesar (ej: --quarters Q1 Q4).")
    args = parser.parse_args()

    if not (args.all or args.points or args.lines or args.multilines or args.polygons):
        args.all = True

    run_points = args.all or args.points
    run_lines = args.all or args.lines
    run_multilines = args.all or args.multilines
    run_polygons = args.all or args.polygons

    anhos = args.years if args.years is not None else DEFAULT_YEARS
    trimestres = args.quarters if args.quarters is not None else DEFAULT_QUARTERS

    tif_name = os.path.splitext(os.path.basename(TIF_PATH))[0]

    for anho in anhos:
        for tri in trimestres:
            folder = os.path.abspath(os.path.join(DATASET_DIR, f"geometrias{anho}_{tif_name}", tri))
            if not os.path.isdir(folder):
                print(f"[WARN] No existe carpeta: {folder} (se salta)")
                continue

            print("\n==============================")
            print(f"Preprocesando {anho} {tri} ({folder})")
            print("==============================")

            # 1) Polygons
            if run_polygons:
                polys = _dedup_paths(glob.glob(os.path.join(folder, "**", f"multipolygons*{anho}*{tri}*_recortado.gpkg"), recursive=True))
                if not polys:
                    print(f"[i] No encontré multipolygons para {anho} {tri}")
                for poly_in in polys:
                    out_pre = os.path.splitext(poly_in)[0] + "_preprocessed.gpkg"
                    if _should_run(True, out_pre, args.force):
                        preprocess_polygons(poly_in, out_pre)
                    else:
                        print(f"[SKIP] Polygons ya existen: {out_pre}")

            # 2) Points
            if run_points:
                pts = _dedup_paths(glob.glob(os.path.join(folder, "**", f"points*{anho}*{tri}*_recortado.gpkg"), recursive=True))
                if not pts:
                    print(f"[i] No encontré points para {anho} {tri}")
                for pts_in in pts:
                    out_pre = os.path.splitext(pts_in)[0] + "_preprocessed.gpkg"
                    if _should_run(True, out_pre, args.force):
                        preprocess_points(pts_in, out_pre)
                    else:
                        print(f"[SKIP] Points ya existen: {out_pre}")

            # 3) Lines
            if run_lines:
                lns = _dedup_paths(glob.glob(os.path.join(folder, "**", f"lines*{anho}*{tri}*_recortado.gpkg"), recursive=True))
                if not lns:
                    print(f"[i] No encontré lines para {anho} {tri}")
                for lns_in in lns:
                    out_pre = os.path.splitext(lns_in)[0] + "_preprocessed.gpkg"
                    if _should_run(True, out_pre, args.force):
                        preprocess_lines(lns_in, out_pre)
                    else:
                        print(f"[SKIP] Lines ya existen: {out_pre}")

            # 4) MultiLineStrings
            if run_multilines:
                mls = _dedup_paths(glob.glob(os.path.join(folder, "**", f"multilinestrings*{anho}*{tri}*_recortado.gpkg"), recursive=True))
                if not mls:
                    print(f"[i] No encontré multilinestrings para {anho} {tri} (ok si no lo usas)")
                for mls_in in mls:
                    out_pre = os.path.splitext(mls_in)[0] + "_preprocessed.gpkg"
                    if _should_run(True, out_pre, args.force):
                        preprocess_multilines(mls_in, out_pre)
                    else:
                        print(f"[SKIP] MultiLines ya existen: {out_pre}")



# CÓMO USAR EL SCRIPT
#
# Este script permite seleccionar QUÉ geometrías preprocesar
# y EVITAR reprocesar datos que ya existen.
#
# -----------------------
# EJECUCIÓN BÁSICA
# -----------------------
#
# 1) Ejecutar TODO (comportamiento por defecto):
#    python preprocess.py
#
#    Equivale a:
#    python preprocess.py --all
#
#    Procesa:
#      - points
#      - lines
#      - multilinestrings
#      - polygons (quitando boundary=administrative)
#
# -----------------------
# SELECCIONAR GEOMETRÍAS
# -----------------------
#
# 2) Solo puntos:
#    python preprocess.py --points
#
# 3) Solo líneas:
#    python preprocess.py --lines
#
# 4) Solo multilíneas:
#    python preprocess.py --multilines
#
# 5) Solo polígonos (multipolygons sin administrative):
#    python preprocess.py --polygons
#
# 6) Combinaciones:
#    python preprocess.py --points --lines
#    python preprocess.py --lines --polygons
#
# -----------------------
# CONTROL DE REPROCESADO
# -----------------------
#
# Por defecto:
#   - Si existe *_preprocessed.gpkg → NO se reprocesa (se hace SKIP)
#
# 7) Forzar reprocesado aunque exista el archivo:
#    python preprocess.py --points --force
#
#
# -----------------------
# FILTRAR AÑOS Y TRIMESTRES
# -----------------------
#
# 8) Procesar solo ciertos años:
#    python preprocess.py --points --years 2024 2023
#
# 9) Procesar solo ciertos trimestres:
#    python preprocess.py --lines --quarters Q1 Q4
#
# 10) Combinar filtros:
#     python preprocess.py --all --years 2024 --quarters Q1
#
# -----------------------
# NOTAS IMPORTANTES
# -----------------------
#
# - Si NO se pasa ningún flag (--points, --lines, etc.),
#   el script asume --all automáticamente.
#
# - QGIS solo se inicializa si se procesan polígonos
#   (para ahorrar tiempo y evitar dependencias innecesarias).

