import os
import glob
from pathlib import Path
import unicodedata
import time
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


DIVISION_DIR = str((PROJECT_ROOT / cfg["paths"]["division_dir"]).resolve())

# districts columns
DIST_ID_COL = cfg.get("districts", {}).get("id_col", "id_distrito")
DIST_NAME_COL = cfg.get("districts", {}).get("name_col", "nombre_distrito")

# prices
prices_cfg = cfg.get("prices", {})
PRICES_XLSX = str((PROJECT_ROOT / prices_cfg.get("xlsx_path", "prices_template_districts_filled.xlsx")).resolve())
PRICES_SHEET = prices_cfg.get("sheet_name", "LONG_INPUT")

# patrones de entrada/salida
CSV_GLOB = prices_cfg.get("csv_glob", os.path.join(DIVISION_DIR, "*", "*", "*_distritos_features_*_Q*.csv"))
OUT_REPLACE_FROM = prices_cfg.get("out_replace_from", "_distritos_features_")
OUT_REPLACE_TO = prices_cfg.get("out_replace_to", "_distritos_features_with_price_")


ENABLE_NAME_TO_ID_FALLBACK = bool(prices_cfg.get("enable_name_to_id_fallback", False))
PRICES_DISTRICT_NAME_COL = prices_cfg.get("prices_district_name_col", "distrito")  



# Utilidades

def norm(s: str) -> str:
    """Normaliza para emparejar nombres (acentos, espacios, mayúsculas)."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = " ".join(s.split())
    return s


def build_district_name_to_id_map() -> dict:
    """
    Construye:
      maps[cod_mun][norm(nombre_distrito)] = id_distrito

    Lee todos los gpkg: division/<mun>/<mun>.gpkg
    """
    maps = {}

    muni_gpkgs = glob.glob(os.path.join(DIVISION_DIR, "*", "*.gpkg"))
    for gpkg_path in muni_gpkgs:
        mun_folder = os.path.basename(os.path.dirname(gpkg_path))

        try:
            dists = gpd.read_file(gpkg_path)
        except Exception as e:
            print(f"[WARN] No pude leer {gpkg_path}: {e}")
            continue

        if "cod_mun" not in dists.columns:
            print(f"[WARN] {gpkg_path}: falta columna 'cod_mun' (se salta mapeo para {mun_folder})")
            continue
        if DIST_ID_COL not in dists.columns or DIST_NAME_COL not in dists.columns:
            print(f"[WARN] {gpkg_path}: faltan '{DIST_ID_COL}' o '{DIST_NAME_COL}' (se salta mapeo para {mun_folder})")
            continue

        cod_vals = dists["cod_mun"].dropna().unique()
        if len(cod_vals) == 0:
            print(f"[WARN] {gpkg_path}: cod_mun vacío (se salta)")
            continue

        for cod in cod_vals:
            cod = int(cod)
            maps.setdefault(cod, {})
            sub = dists[dists["cod_mun"] == cod]

            for _, row in sub.iterrows():
                name = norm(row[DIST_NAME_COL])
                did = row[DIST_ID_COL]
                if pd.isna(did) or name == "":
                    continue
                maps[cod][name] = int(did)

    return maps



# 1) Leer precios

start_total = time.perf_counter()

if not os.path.isfile(PRICES_XLSX):
    raise FileNotFoundError(f"No existe el Excel de precios: {PRICES_XLSX}")

precios = pd.read_excel(PRICES_XLSX, sheet_name=PRICES_SHEET)

required = {"cod_mun", "year", "quarter", "price_m2"}
missing_req = required - set(precios.columns)
if missing_req:
    raise ValueError(f"En {PRICES_SHEET} faltan columnas obligatorias: {missing_req}")

# tipos / limpieza
precios["cod_mun"] = pd.to_numeric(precios["cod_mun"], errors="coerce").astype("Int64")
precios["year"] = pd.to_numeric(precios["year"], errors="coerce").astype("Int64")
precios["quarter"] = precios["quarter"].astype(str).str.upper().str.replace(" ", "")
precios["price_m2"] = pd.to_numeric(precios["price_m2"], errors="coerce")

# quitar filas sin claves o sin precio
precios = precios.dropna(subset=["cod_mun", "year", "quarter", "price_m2"]).copy()
precios["cod_mun"] = precios["cod_mun"].astype(int)
precios["year"] = precios["year"].astype(int)


# 1.b) Asegurar id_distrito en precios

if "id_distrito" not in precios.columns or precios["id_distrito"].isna().all():
    print("[INFO] En el Excel no viene 'id_distrito' (o está vacío).")

    if not ENABLE_NAME_TO_ID_FALLBACK:
        raise ValueError(
            "Falta 'id_distrito' en el Excel y el fallback nombre->id está desactivado.\n"
            "Actívalo en config.yaml: prices.enable_name_to_id_fallback: true"
        )

    if PRICES_DISTRICT_NAME_COL not in precios.columns:
        raise ValueError(
            f"No hay columna '{PRICES_DISTRICT_NAME_COL}' en {PRICES_SHEET} y no puedo derivar id_distrito."
        )

    print("[INFO] Intento derivar id_distrito desde los GPKG de /division usando nombre de distrito...")
    name_to_id = build_district_name_to_id_map()
    if not name_to_id:
        raise RuntimeError(
            "No he podido construir el mapeo de distritos "
            "(revisa que tus GPKG tengan cod_mun, id_distrito, nombre_distrito)."
        )

    precios["distrito_key"] = precios[PRICES_DISTRICT_NAME_COL].map(norm)

    def lookup_id(row):
        cm = row["cod_mun"]
        dk = row["distrito_key"]
        return name_to_id.get(cm, {}).get(dk, pd.NA)

    precios["id_distrito"] = precios.apply(lookup_id, axis=1).astype("Int64")

    n_missing = int(precios["id_distrito"].isna().sum())
    if n_missing > 0:
        cols = [c for c in ["cod_mun", "municipio", PRICES_DISTRICT_NAME_COL] if c in precios.columns]
        sample = precios.loc[precios["id_distrito"].isna(), cols].head(15)
        print(f"[WARN] No he podido asignar id_distrito a {n_missing} filas. Ejemplos:\n{sample}")

    precios = precios.drop(columns=["distrito_key"])
else:
    precios["id_distrito"] = pd.to_numeric(precios["id_distrito"], errors="coerce").astype("Int64")

# quitar filas sin id_distrito
precios = precios.dropna(subset=["id_distrito"]).copy()
precios["id_distrito"] = precios["id_distrito"].astype(int)

precios_join = precios[["cod_mun", "id_distrito", "year", "quarter", "price_m2"]].copy()



# 2) Localizar CSVs agregados por distrito (trimestral)

csvs = glob.glob(CSV_GLOB)
print(f"Encontrados {len(csvs)} CSVs de agregados")

for path in csvs:
    df = pd.read_csv(path)

    if "cod_mun" not in df.columns:
        print(f"[WARN] {path}: falta columna 'cod_mun' (se salta).")
        continue
    if "id_distrito" not in df.columns:
        print(f"[WARN] {path}: falta columna 'id_distrito' (se salta).")
        continue


    parts = os.path.normpath(path).split(os.sep)
    try:
        year_from_path = int(parts[-2])  # .../division/<mun>/<año>/file.csv
    except Exception:
        year_from_path = None

    fname = os.path.basename(path).replace(".csv", "")
    quarter_from_name = fname.split("_")[-1].upper()

    df["cod_mun"] = pd.to_numeric(df["cod_mun"], errors="coerce").astype("Int64")
    df["id_distrito"] = pd.to_numeric(df["id_distrito"], errors="coerce").astype("Int64")

    if "year" not in df.columns:
        df["year"] = year_from_path
    if "quarter" not in df.columns:
        df["quarter"] = quarter_from_name

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["quarter"] = df["quarter"].astype(str).str.upper().str.replace(" ", "")

    df = df.dropna(subset=["cod_mun", "id_distrito", "year", "quarter"]).copy()
    df["cod_mun"] = df["cod_mun"].astype(int)
    df["id_distrito"] = df["id_distrito"].astype(int)
    df["year"] = df["year"].astype(int)

    out = df.merge(precios_join, on=["cod_mun", "id_distrito", "year", "quarter"], how="left")

    if out["price_m2"].isna().all():
        print(f"[WARN] Sin match de precios: {path}")

    out_path = path.replace(OUT_REPLACE_FROM, OUT_REPLACE_TO)
    out.to_csv(out_path, index=False, encoding="utf-8")
    print(f"OK -> {out_path}")

end_total = time.perf_counter()
elapsed = end_total - start_total

h = int(elapsed // 3600)
m = int((elapsed % 3600) // 60)
s = elapsed % 60

print("TIEMPO TOTAL DE EJECUCIÓN")
print(f"{h:02d}:{m:02d}:{s:05.2f} (hh:mm:ss)")