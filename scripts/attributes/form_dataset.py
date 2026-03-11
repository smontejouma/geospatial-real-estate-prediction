import re
from pathlib import Path
import time
import numpy as np
import pandas as pd
import yaml



# Load config.yaml

def find_project_root(start: Path, config_name: str = "config.yaml") -> Path:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / config_name).is_file():
            return p
    raise FileNotFoundError(f"No encontré {config_name} subiendo desde: {start}")


PROJECT_ROOT = find_project_root(Path(__file__).parent)
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

DIVISION_DIR = (PROJECT_ROOT / cfg["paths"]["division_dir"]).resolve()

dataset_cfg = cfg.get("dataset_final", {})
OUT_DIR = (PROJECT_ROOT / dataset_cfg.get("out_dir", "./dataset_final")).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

fname_re_str = dataset_cfg.get(
    "filename_regex",
    r"^(?P<mun>.+)_distritos_features_with_price_(?P<year>\d{4})_(?P<q>Q[1-4])\.csv$",
)
FNAME_RE = re.compile(fname_re_str, re.IGNORECASE)

KEY_COLS = dataset_cfg.get("key_cols", ["municipio", "id_distrito", "year", "quarter"])

exclude_text_cols = set(dataset_cfg.get("exclude_text_cols", ["nombre_distrito", "distrito"]))
encoding_primary = dataset_cfg.get("encoding_primary", "utf-8")
encoding_fallback = dataset_cfg.get("encoding_fallback", "latin1")

# outputs
out_csv_name = dataset_cfg.get("out_csv", "dataset_distritos_long.csv")
out_parquet_name = dataset_cfg.get("out_parquet", "dataset_distritos_long.parquet")
out_report_name = dataset_cfg.get("out_report", "report_build_dataset.csv")



# HELPERS

def read_csv_robust(path: Path) -> pd.DataFrame:

    try:
        return pd.read_csv(path, encoding=encoding_primary)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding=encoding_fallback)


def ensure_cols(df: pd.DataFrame, municipio: str, year: int, quarter: str) -> pd.DataFrame:
    """Asegura municipio/year/quarter y columnas esperables."""
    df = df.copy()

    if "municipio" not in df.columns:
        df["municipio"] = municipio
    else:
        df["municipio"] = df["municipio"].fillna(municipio)
        df.loc[df["municipio"].astype(str).str.strip().eq(""), "municipio"] = municipio

    df["year"] = year
    df["quarter"] = quarter

    if "id_distrito" not in df.columns:
        raise ValueError("Falta columna 'id_distrito' en el CSV.")

    df["id_distrito"] = pd.to_numeric(df["id_distrito"], errors="coerce").astype("Int64")
    return df


def coerce_numeric_columns(df: pd.DataFrame, exclude: set) -> pd.DataFrame:

    df = df.copy()
    for c in df.columns:
        if c in exclude:
            continue
        if df[c].dtype == object:
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().any():
                df[c] = conv
    return df


def pick_most_complete_row(group: pd.DataFrame) -> pd.DataFrame:
    """Si hay duplicados por KEY_COLS, elige la fila con más valores no nulos."""
    nn = group.notna().sum(axis=1)
    best_idx = nn.idxmax()
    return group.loc[[best_idx]]



# BUILD DATASET

def build_dataset_long(base_div: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    report = []

    for p in base_div.rglob("*.csv"):
        m = FNAME_RE.match(p.name)
        if not m:
            continue

        municipio = m.group("mun")
        year = int(m.group("year"))
        quarter = m.group("q").upper()

        try:
            df = read_csv_robust(p)
            df = ensure_cols(df, municipio, year, quarter)

            df = coerce_numeric_columns(
                df,
                exclude=set(KEY_COLS) | exclude_text_cols
            )
            rows.append(df)

        except Exception as e:
            report.append({
                "file": str(p),
                "status": "ERROR_READING_OR_SCHEMA",
                "error": str(e)
            })

    if not rows:
        raise RuntimeError(
            f"No se encontraron CSV válidos en {base_div} con el patrón configurado.\n"
            f"Regex actual: {fname_re_str}"
        )

    data = pd.concat(rows, ignore_index=True)

    # Orden 
    data = data.sort_values(["municipio", "id_distrito", "year", "quarter"], kind="mergesort")

    # Duplicados por clave
    dup_mask = data.duplicated(subset=KEY_COLS, keep=False)
    if dup_mask.any():
        dups = data.loc[dup_mask, KEY_COLS].value_counts().reset_index(name="n")
        for _, r in dups.head(50).iterrows():
            report.append({
                "file": "",
                "status": "DUPLICATE_KEY",
                "error": f"Key={tuple(r[c] for c in KEY_COLS)} appears {int(r['n'])} times"
            })

        # resolver duplicados: fila más completa
        data = (
            data.groupby(KEY_COLS, dropna=False, as_index=False)
                .apply(pick_most_complete_row)
                .reset_index(drop=True)
        )

    if data["id_distrito"].isna().any():
        n = int(data["id_distrito"].isna().sum())
        report.append({"file": "", "status": "WARN_ID_DISTRITO_NA", "error": f"{n} filas con id_distrito NA"})

    return data, pd.DataFrame(report)


def main():
    data, report_df = build_dataset_long(DIVISION_DIR)

    out_csv = OUT_DIR / out_csv_name
    out_parquet = OUT_DIR / out_parquet_name
    out_report = OUT_DIR / out_report_name

    data.to_csv(out_csv, index=False, encoding="utf-8")
    try:
        data.to_parquet(out_parquet, index=False)
    except Exception:
        pass

    report_df.to_csv(out_report, index=False, encoding="utf-8")

    print(" Dataset LONG generado:")
    print(f" - {out_csv}")
    if out_parquet.exists():
        print(f" - {out_parquet}")
    print(" Report:")
    print(f" - {out_report}")
    print(f"Filas: {len(data):,} | Columnas: {data.shape[1]}")


if __name__ == "__main__":
    start_total = time.perf_counter()
    main()
    end_total = time.perf_counter()
    elapsed = end_total - start_total

    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = elapsed % 60

    print("TIEMPO TOTAL DE EJECUCIÓN")
    print(f"{h:02d}:{m:02d}:{s:05.2f} (hh:mm:ss)")