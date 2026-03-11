import os
from pathlib import Path
import time
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import MultiPoint
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

EPSG_DEFAULT = int(cfg["crs"]["epsg_default"])

DATASET_DIR = str((PROJECT_ROOT / cfg["paths"]["dataset_dir"]).resolve())
DIVISION_DIR = str((PROJECT_ROOT / cfg["paths"]["division_dir"]).resolve())
TIF_PATH = str((PROJECT_ROOT / cfg["paths"]["tif_path"]).resolve())
TIF_NAME = os.path.splitext(os.path.basename(TIF_PATH))[0]

DEFAULT_YEARS = list(cfg["run"]["years"])
DEFAULT_QUARTERS = list(cfg["run"]["quarters"])
MUNICIPIOS = list(cfg.get("municipios", []))

DIST_ID_COL = cfg.get("districts", {}).get("id_col", "id_distrito")
DIST_NAME_COL = cfg.get("districts", {}).get("name_col", "nombre_distrito")

# landuse/leisure macroclases
LANDUSE_URBAN = list(cfg["landuse_classes"]["landuse_urban"])
LANDUSE_GREEN = list(cfg["landuse_classes"]["landuse_green"])
LANDUSE_LEISURE = list(cfg["landuse_classes"]["landuse_leisure"])
LEISURE_LEISURE = list(cfg["landuse_classes"]["leisure_leisure"])
LANDUSE_WATER = list(cfg["landuse_classes"]["landuse_water"])
LANDUSE_SPECIAL = list(cfg["landuse_classes"]["landuse_special"])
URBAN_LANDUSE = list(cfg["landuse_classes"]["urban_landuse"])

# features a calcular
POI_GROUPS = list(cfg.get("features", {}).get("poi_groups", []))
NEAREST_DISTANCES = list(cfg.get("features", {}).get("nearest_distances", []))
LINE_GROUPS = list(cfg.get("features", {}).get("line_groups", []))



# Utilidades básicas

def to_utm(gdf, epsg: int = EPSG_DEFAULT):
    if gdf is None or len(gdf) == 0:
        return gdf
    if gdf.crs is None or gdf.crs.to_epsg() != epsg:
        return gdf.to_crs(epsg)
    return gdf


def load_vector(path, layer=None, epsg: int = EPSG_DEFAULT):
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    return to_utm(gdf, epsg)



# PUNTOS: conteo por distrito (robusto, sin merges peligrosos)

def count_points_by_polygon(polys_gdf, points_gdf, where=None, col_name="n_pts"):
    pts = to_utm(points_gdf)
    out = polys_gdf.copy()

    out[col_name] = 0

    if pts is None or pts.empty or out.empty:
        return out

    if callable(where):
        pts = pts[where(pts)]
    elif isinstance(where, str) and where.strip():
        pts = pts.query(where)

    if pts.empty:
        return out

    j = gpd.sjoin(
        pts[["geometry"]],
        out[["__did__", "geometry"]],
        how="left",
        predicate="within",
    )

    counts = j.dropna(subset=["__did__"]).groupby("__did__").size()
    out[col_name] = out["__did__"].map(counts).fillna(0).astype("int64")
    return out



# DISTANCIA: centroide distrito -> POI más cercano

def dist_to_nearest_from_centroid(polys_gdf, target_gdf, where=None, col_name="dist_nearest_m"):
    tgt = to_utm(target_gdf)
    out = polys_gdf.copy()
    out[col_name] = np.nan

    if tgt is None or tgt.empty or out.empty:
        return out

    if isinstance(where, str) and where.strip():
        tgt = tgt.query(where).copy()
    if tgt.empty:
        return out

    if not tgt.geom_type.isin(["Point"]).all():
        tgt = tgt.copy()
        tgt["geometry"] = tgt.geometry.centroid

    mp = MultiPoint([g for g in tgt.geometry.values if g is not None and not g.is_empty])
    if mp.is_empty:
        return out

    cent = out.geometry.centroid.values
    out[col_name] = [float(c.distance(mp)) if (c is not None and not c.is_empty) else np.nan for c in cent]
    return out



# LÍNEAS: longitud dentro de distrito

def line_length_in_polygons(polys_gdf, lines_gdf, where=None, col_name="len_m"):
    ln = to_utm(lines_gdf)
    out = polys_gdf.copy()
    out[col_name] = 0.0

    if ln is None or ln.empty or out.empty:
        return out

    if isinstance(where, str) and where.strip():
        ln = ln.query(where).copy()
    if ln.empty:
        return out

    cand = gpd.sjoin(
        out[["__did__", "geometry"]],
        ln[["geometry"]],
        how="left",
        predicate="intersects",
    ).rename(columns={"geometry": "poly_geom"})

    cand["line_geom"] = cand["index_right"].map(ln.geometry)
    cand = cand.dropna(subset=["line_geom"])
    if cand.empty:
        return out

    recs = {}
    for did, sub in cand.groupby("__did__"):
        poly = sub.iloc[0].poly_geom
        total = 0.0
        for g in sub["line_geom"].values:
            inter = poly.intersection(g)
            if not inter.is_empty:
                total += inter.length
        recs[did] = float(total)

    out[col_name] = out["__did__"].map(recs).fillna(0.0)
    return out


def line_length_by_group(polys_gdf, lines_gdf, group_col="line_group", groups=None, prefix="len_"):
    ln = to_utm(lines_gdf)
    out = polys_gdf.copy()

    if ln is None or ln.empty or group_col not in ln.columns:
        return out

    if groups is None:
        groups = sorted(ln[group_col].dropna().astype(str).unique().tolist())

    for gname in groups:
        out = line_length_in_polygons(
            out,
            ln,
            where=f"{group_col} == '{gname}'",
            col_name=f"{prefix}{gname}",
        )
    return out


# POLÍGONOS: cobertura por distrito con UNION de intersecciones

def polygon_union_area_in_polygons(
    districts_gdf,
    poly_gdf,
    mask=None,
    where=None,
    col_area="area_m2",
    col_pct="pct",
):
    d = districts_gdf.copy()
    if col_area not in d.columns:
        d[col_area] = 0.0
    if col_pct not in d.columns:
        d[col_pct] = 0.0

    p = to_utm(poly_gdf)
    if p is None or p.empty or d.empty:
        d[col_area] = d[col_area].fillna(0.0)
        d[col_pct] = d[col_pct].fillna(0.0)
        return d

    if callable(mask):
        p = p[mask(p)].copy()
    if isinstance(where, str) and where.strip():
        p = p.query(where).copy()
    if p.empty:
        d[col_area] = d[col_area].fillna(0.0)
        d[col_pct] = d[col_pct].fillna(0.0)
        return d

    cand = gpd.sjoin(
        d[["__did__", "geometry", "district_area_m2"]],
        p[["geometry"]],
        how="left",
        predicate="intersects",
    ).rename(columns={"geometry": "dist_geom"})

    cand["poly_geom"] = cand["index_right"].map(p.geometry)
    cand = cand.dropna(subset=["poly_geom"])
    if cand.empty:
        d[col_area] = d[col_area].fillna(0.0)
        d[col_pct] = d[col_pct].fillna(0.0)
        return d

    rec_area = {}
    rec_pct = {}

    for did, sub in cand.groupby("__did__"):
        dist = sub.iloc[0].dist_geom
        dist_area = float(sub.iloc[0].district_area_m2)

        inter_parts = []
        for pg in sub["poly_geom"].values:
            if pg is None or pg.is_empty:
                continue
            inter = dist.intersection(pg)
            if not inter.is_empty:
                inter_parts.append(inter)

        if not inter_parts:
            area = 0.0
        else:
            u = unary_union(inter_parts)
            area = 0.0 if (u is None or u.is_empty) else float(u.area)

        rec_area[did] = area
        rec_pct[did] = (0.0 if dist_area <= 0 else area / dist_area)

    d[col_area] = d["__did__"].map(rec_area).fillna(0.0)
    d[col_pct] = d["__did__"].map(rec_pct).fillna(0.0)
    return d


# EDIFICIOS: conteo por centroides en distrito

def count_buildings_in_districts(districts_gdf, buildings_poly_gdf, col_name="n_buildings"):
    d = districts_gdf.copy()
    d[col_name] = 0

    b = to_utm(buildings_poly_gdf)
    if b is None or b.empty or d.empty:
        return d

    if "building" in b.columns:
        b = b[b["building"].notna()].copy()
    if b.empty:
        return d

    b = b.copy()
    b["geometry"] = b.geometry.centroid

    j = gpd.sjoin(
        b[["geometry"]],
        d[["__did__", "geometry"]],
        how="left",
        predicate="within",
    )

    counts = j.dropna(subset=["__did__"]).groupby("__did__").size()
    d[col_name] = d["__did__"].map(counts).fillna(0).astype("int64")
    return d


# Pipeline distrito

def build_district_features(muni_districts_path, pts, lns, polys, mults, out_gpkg, out_csv):
    dists = load_vector(muni_districts_path)
    if dists.empty:
        raise ValueError(f"No hay distritos en {muni_districts_path}")

    dists = dists.reset_index(drop=True)
    if DIST_ID_COL not in dists.columns:
        dists[DIST_ID_COL] = dists.index + 1
    if DIST_NAME_COL not in dists.columns:
        dists[DIST_NAME_COL] = "Distrito_" + dists[DIST_ID_COL].astype(str)

    dists["__did__"] = dists[DIST_ID_COL].astype(str)

    dists["district_area_m2"] = dists.geometry.area
    dists["district_area_km2"] = dists["district_area_m2"] / 1e6

    pts_gdf = load_vector(pts)
    lns_gdf = load_vector(lns)

    poly_build = load_vector(polys, layer="poly_buildings")
    poly_act = load_vector(polys, layer="poly_activity")
    poly_land = load_vector(polys, layer="poly_landcover_base")
    poly_infra = load_vector(polys, layer="poly_infra")
    poly_her = load_vector(polys, layer="poly_heritage")
    _ = load_vector(mults) if (mults and os.path.isfile(mults)) else None

    g = dists.copy()

    # PUNTOS
    print("Puntos: total y por grupo…")
    g = count_points_by_polygon(g, pts_gdf, col_name="n_poi_total")

    if "poi_group" in pts_gdf.columns and POI_GROUPS:
        for pg in POI_GROUPS:
            g = count_points_by_polygon(
                g,
                pts_gdf,
                where=lambda df, pg=pg: df["poi_group"].astype(str).eq(pg).fillna(False),
                col_name=f"n_poi_{pg}",
            )

        if NEAREST_DISTANCES:
            print("Distancias (centroide distrito) a POIs clave…")
            for item in NEAREST_DISTANCES:
                where = item.get("where", "")
                out_col = item.get("out", "")
                if where and out_col:
                    g = dist_to_nearest_from_centroid(g, pts_gdf, where=where, col_name=out_col)


    if ("amenity" in pts_gdf.columns) or ("highway" in pts_gdf.columns):
        print("Amenities clave…")

        def filtro_amenities(df):
            amen = (
                df["amenity"].isin(["school", "hospital", "pharmacy", "supermarket", "bus_station"]).fillna(False)
                if "amenity" in df.columns
                else False
            )
            bus = df["highway"].eq("bus_stop").fillna(False) if "highway" in df.columns else False
            return amen | bus

        g = count_points_by_polygon(g, pts_gdf, where=filtro_amenities, col_name="amen_key")


    # BUILDINGS
    print("Buildings: área/pct + conteo…")
    g = polygon_union_area_in_polygons(g, poly_build, col_area="area_building_m2", col_pct="pct_building")
    g = count_buildings_in_districts(g, poly_build, col_name="n_buildings")

    if "building_group" in poly_build.columns:
        for bg in ["residential", "commercial", "public", "industrial", "other_building"]:
            g = polygon_union_area_in_polygons(
                g,
                poly_build,
                mask=lambda df, bg=bg: df["building_group"].astype(str).eq(bg).fillna(False),
                col_area=f"area_building_{bg}_m2",
                col_pct=f"pct_building_{bg}",
            )


    # ACTIVITY
    print("Activity: área/pct…")
    g = polygon_union_area_in_polygons(g, poly_act, col_area="area_activity_m2", col_pct="pct_activity")

    if "activity_group" in poly_act.columns:
        act_groups = [
            "food_drink", "education", "health", "finance", "public_services",
            "culture_leisure", "parking_mobility", "utilities",
            "tourism_accommodation", "tourism_attraction", "tourism_other",
            "shop", "office", "craft", "other_amenity",
        ]
        for ag in act_groups:
            g = polygon_union_area_in_polygons(
                g,
                poly_act,
                mask=lambda df, ag=ag: df["activity_group"].astype(str).eq(ag).fillna(False),
                col_area=f"area_act_{ag}_m2",
                col_pct=f"pct_act_{ag}",
            )

    # LANDCOVER
    print("Landcover macro…")
    if "landuse" in poly_land.columns:
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: df["landuse"].isin(LANDUSE_URBAN).fillna(False),
            col_area="area_urban_landuse_m2",
            col_pct="pct_urban_landuse",
        )
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: df["landuse"].isin(LANDUSE_GREEN).fillna(False),
            col_area="area_green_landuse_m2",
            col_pct="pct_green_landuse",
        )
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: df["landuse"].isin(LANDUSE_SPECIAL).fillna(False),
            col_area="area_special_m2",
            col_pct="pct_special",
        )
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: df["landuse"].isin(LANDUSE_WATER).fillna(False),
            col_area="area_landuse_water_m2",
            col_pct="pct_landuse_water",
        )

    has_landuse = "landuse" in poly_land.columns
    has_leisure = "leisure" in poly_land.columns
    if has_landuse or has_leisure:
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: (
                (df["landuse"].isin(LANDUSE_LEISURE).fillna(False) if has_landuse else False)
                | (df["leisure"].isin(LEISURE_LEISURE).fillna(False) if has_leisure else False)
            ),
            col_area="area_leisure_m2",
            col_pct="pct_leisure",
        )

    has_natural = "natural" in poly_land.columns
    has_watercol = "water" in poly_land.columns
    if has_landuse or has_natural or has_watercol:
        g = polygon_union_area_in_polygons(
            g,
            poly_land,
            mask=lambda df: (
                (df["landuse"].isin(LANDUSE_WATER).fillna(False) if has_landuse else False)
                | (df["natural"].eq("water").fillna(False) if has_natural else False)
                | (df["water"].notna().fillna(False) if has_watercol else False)
            ),
            col_area="area_water_m2",
            col_pct="pct_water",
        )


    # URBANIZADO total
    print("Urbanizado total…")
    urban_parts = []

    if poly_build is not None and not poly_build.empty:
        urban_parts.append(poly_build[["geometry"]].copy())

    if "landuse" in poly_land.columns and not poly_land.empty:
        landuse_u = poly_land[poly_land["landuse"].isin(URBAN_LANDUSE).fillna(False)][["geometry"]].copy()
        if not landuse_u.empty:
            urban_parts.append(landuse_u)

    if urban_parts:
        both_urban = pd.concat(urban_parts, ignore_index=True)
        both_urban = gpd.GeoDataFrame(both_urban, geometry="geometry", crs=g.crs)
        g = polygon_union_area_in_polygons(g, both_urban, col_area="area_urbanized_m2", col_pct="pct_urbanized")
    else:
        g["area_urbanized_m2"] = 0.0
        g["pct_urbanized"] = 0.0


    # INFRA + HERITAGE
    print("Infra y Heritage…")
    g = polygon_union_area_in_polygons(g, poly_infra, col_area="area_infra_m2", col_pct="pct_infra")
    g = polygon_union_area_in_polygons(g, poly_her, col_area="area_heritage_m2", col_pct="pct_heritage")


    # LÍNEAS
    print("Líneas…")
    if "line_group" in lns_gdf.columns and LINE_GROUPS:
        g = line_length_by_group(g, lns_gdf, group_col="line_group", groups=LINE_GROUPS, prefix="len_")
    else:
        g = line_length_in_polygons(
            g,
            lns_gdf,
            where="highway in ['motorway','trunk','primary','secondary']",
            col_name="len_road_major",
        )


    # Ratios/densidades
    print("Ratios/densidades…")
    eps = 1e-6

    g["green_to_building"] = g.get("area_green_landuse_m2", 0.0) / (g.get("area_building_m2", 0.0) + eps)
    g["water_to_building"] = g.get("area_water_m2", 0.0) / (g.get("area_building_m2", 0.0) + eps)
    g["activity_per_building_m2"] = g.get("area_activity_m2", 0.0) / (g.get("area_building_m2", 0.0) + eps)

    g["noise_proxy_len"] = g.get("len_road_major", 0.0) + g.get("len_rail", 0.0)

    km2 = g["district_area_km2"].replace(0, np.nan)
    g["poi_per_km2"] = g.get("n_poi_total", 0) / km2
    g["buildings_per_km2"] = g.get("n_buildings", 0) / km2

    if "len_road_major" in g.columns:
        g["roads_km_per_km2"] = (g["len_road_major"] / 1000.0) / km2
    else:
        g["roads_km_per_km2"] = np.nan

    # Guardar
    if os.path.exists(out_gpkg):
        os.remove(out_gpkg)

    g.to_file(out_gpkg, layer="distritos_features", driver="GPKG")
    cols_no_geom = [c for c in g.columns if c != "geometry"]
    pd.DataFrame(g[cols_no_geom]).to_csv(out_csv, index=False, encoding="utf-8")

    print(f" GPKG: {out_gpkg}")
    print(f" CSV : {out_csv}")

    return g



# MAIN
if __name__ == "__main__":
    start_total = time.perf_counter()

    if not MUNICIPIOS:
        raise ValueError("No hay 'municipios' definidos en config.yaml")

    for muni_name in MUNICIPIOS:
        muni_districts_path = os.path.join(DIVISION_DIR, muni_name, f"{muni_name}.gpkg")
        if not os.path.isfile(muni_districts_path):
            print(f"[WARN] No existe el municipio/distritos: {muni_districts_path} (se salta)")
            continue

        for anho in DEFAULT_YEARS:
            out_year_dir = os.path.join(DIVISION_DIR, muni_name, str(anho))
            os.makedirs(out_year_dir, exist_ok=True)

            for tri in DEFAULT_QUARTERS:
                base_q_dir = os.path.join(DATASET_DIR, f"geometrias{anho}_{TIF_NAME}", tri)

                pts_path = os.path.join(base_q_dir, f"points_{anho}_{tri}_recortado_preprocessed.gpkg")
                lns_path = os.path.join(base_q_dir, f"lines_{anho}_{tri}_recortado_preprocessed.gpkg")
                polys_path = os.path.join(base_q_dir, f"multipolygons_{anho}_{tri}_recortado_preprocessed.gpkg")
                mults_path = os.path.join(base_q_dir, f"multilinestrings_{anho}_{tri}_recortado_preprocessed.gpkg")

                missing = [p for p in [pts_path, lns_path, polys_path] if not os.path.isfile(p)]
                if missing:
                    print(f"[WARN] {muni_name} {anho} {tri}: faltan inputs -> {missing} (se salta)")
                    continue

                out_gpkg = os.path.join(out_year_dir, f"{muni_name}_distritos_features_{anho}_{tri}.gpkg")
                out_csv = out_gpkg.replace(".gpkg", ".csv")

                print(f"Municipio: {muni_name} | Año: {anho} | Trimestre: {tri}")
                print(f"Out: {out_gpkg}")

                build_district_features(
                    muni_districts_path=muni_districts_path,
                    pts=pts_path,
                    lns=lns_path,
                    polys=polys_path,
                    mults=mults_path,
                    out_gpkg=out_gpkg,
                    out_csv=out_csv,
                )

    end_total = time.perf_counter()
    elapsed = end_total - start_total

    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = elapsed % 60

    print("TIEMPO TOTAL DE EJECUCIÓN")
    print(f"{h:02d}:{m:02d}:{s:05.2f} (hh:mm:ss)")