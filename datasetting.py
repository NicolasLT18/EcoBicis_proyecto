"""Carga y limpieza de los datos de Ecobici.

Uso típico desde cualquier notebook o script del proyecto:

    from datasetting import cargar_datos
    viajes, estaciones = cargar_datos()

`viajes` ya viene limpio, con columnas derivadas y filtrado a viajes válidos;
`estaciones` es el catálogo indexado por `num_cicloe`.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# Rutas relativas a este archivo, para que funcionen sin importar desde dónde se ejecute
DATA_DIR = Path(__file__).resolve().parent / "data"
RUTA_VIAJES = DATA_DIR / "viajes_ecobici_092026.csv"
RUTA_ESTACIONES = DATA_DIR / "estaciones_ecobici.csv"

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
RANGOS_EDAD = {
    "bins": [15, 24, 34, 44, 54, 64, 100],
    "labels": ["16-24", "25-34", "35-44", "45-54", "55-64", "65+"],
}

# Filtros por defecto de viaje válido
DURACION_MIN = 1      # minutos
DURACION_MAX = 180    # minutos (3 h)
FECHA_INICIO = "2026-09-01"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def limpiar_id_estacion(serie: pd.Series) -> pd.Series:
    """Convierte IDs de estación a entero.

    Algunas estaciones vienen con número doble ("235-236"); se toma el primero.
    """
    return (
        serie.astype("string")
             .str.strip()
             .replace("", pd.NA)
             .str.split("-").str[0]
             .astype("Float64")
             .astype("Int64")
    )


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en línea recta (km) entre dos puntos o arreglos de puntos."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------------------
# Estaciones
# ---------------------------------------------------------------------------

def cargar_estaciones_raw(ruta=RUTA_ESTACIONES) -> pd.DataFrame:
    """Lee el CSV de estaciones tal cual (utf-8-sig quita el BOM del encabezado)."""
    return pd.read_csv(ruta, encoding="utf-8-sig", dtype={"num_cicloe": "string"})


def limpiar_estaciones(estaciones: pd.DataFrame) -> pd.DataFrame:
    """Catálogo de estaciones limpio e indexado por `num_cicloe`.

    Nota: el CSV original ya trae ñ y acentos perdidos como "�"; no se pueden recuperar.
    """
    est = estaciones.drop(columns=["sistema"], errors="ignore").copy()
    est["num_cicloe"] = limpiar_id_estacion(est["num_cicloe"])
    est = est.dropna(subset=["num_cicloe"]).drop_duplicates("num_cicloe")

    for col in est.select_dtypes(include=["object", "string"]).columns:
        est[col] = est[col].str.strip()

    est["Estacion"] = est["calle_prin"] + " y " + est["calle_secu"]
    return est.set_index("num_cicloe").sort_index()


def cargar_estaciones(ruta=RUTA_ESTACIONES) -> pd.DataFrame:
    return limpiar_estaciones(cargar_estaciones_raw(ruta))


# ---------------------------------------------------------------------------
# Viajes
# ---------------------------------------------------------------------------

def cargar_viajes_raw(ruta=RUTA_VIAJES) -> pd.DataFrame:
    """Lee el CSV de viajes tal cual. Los IDs de estación se leen como texto."""
    return pd.read_csv(
        ruta,
        dtype={"Ciclo_Estacion_Retiro": "string", "Ciclo_EstacionArribo": "string"},
    )


def limpiar_viajes(viajes: pd.DataFrame) -> pd.DataFrame:
    """Tipos correctos: fechas como datetime, estaciones como enteros, nombres de columna uniformes."""
    v = viajes.rename(columns={"Ciclo_EstacionArribo": "Ciclo_Estacion_Arribo"}).copy()

    formato = "%d/%m/%Y %H:%M:%S"
    v["Fecha_Hora_Retiro"] = pd.to_datetime(v["Fecha_Retiro"] + " " + v["Hora_Retiro"], format=formato)
    v["Fecha_Hora_Arribo"] = pd.to_datetime(v["Fecha_Arribo"] + " " + v["Hora_Arribo"], format=formato)
    v = v.drop(columns=["Fecha_Retiro", "Hora_Retiro", "Fecha_Arribo", "Hora_Arribo"])

    v["Ciclo_Estacion_Retiro"] = limpiar_id_estacion(v["Ciclo_Estacion_Retiro"])
    v["Ciclo_Estacion_Arribo"] = limpiar_id_estacion(v["Ciclo_Estacion_Arribo"])
    v["Edad_Usuario"] = v["Edad_Usuario"].astype("Int64")
    v["Genero_Usuario"] = v["Genero_Usuario"].astype("category")

    return v


def agregar_columnas(viajes: pd.DataFrame, estaciones: pd.DataFrame | None = None) -> pd.DataFrame:
    """Agrega columnas derivadas de tiempo y, si se pasa el catálogo, distancia y velocidad."""
    v = viajes.copy()
    retiro = v["Fecha_Hora_Retiro"]

    v["Duracion_min"] = (v["Fecha_Hora_Arribo"] - retiro).dt.total_seconds() / 60
    v["Fecha"] = retiro.dt.normalize()
    v["Hora"] = retiro.dt.hour
    v["Dia_Semana"] = retiro.dt.day_of_week          # 0 = lunes
    v["Fin_de_Semana"] = v["Dia_Semana"] >= 5
    v["Viaje_Circular"] = v["Ciclo_Estacion_Retiro"] == v["Ciclo_Estacion_Arribo"]
    v["Rango_Edad"] = pd.cut(v["Edad_Usuario"], **RANGOS_EDAD)

    if estaciones is not None:
        lat, lon = estaciones["latitud"], estaciones["longitud"]
        v["Alcaldia_Retiro"] = v["Ciclo_Estacion_Retiro"].map(estaciones["alcaldia"])
        v["Alcaldia_Arribo"] = v["Ciclo_Estacion_Arribo"].map(estaciones["alcaldia"])
        v["Distancia_km"] = haversine_km(
            v["Ciclo_Estacion_Retiro"].map(lat).astype(float), v["Ciclo_Estacion_Retiro"].map(lon).astype(float),
            v["Ciclo_Estacion_Arribo"].map(lat).astype(float), v["Ciclo_Estacion_Arribo"].map(lon).astype(float),
        )
        v["Velocidad_kmh"] = v["Distancia_km"] / (v["Duracion_min"] / 60)

    return v


def filtrar_validos(
    viajes: pd.DataFrame,
    dur_min: float = DURACION_MIN,
    dur_max: float = DURACION_MAX,
    desde: str | None = FECHA_INICIO,
    hasta: str | None = None,
) -> pd.DataFrame:
    """Quita viajes con duración fuera de rango o fuera del periodo de análisis."""
    mask = viajes["Duracion_min"].between(dur_min, dur_max)
    mask &= viajes["Ciclo_Estacion_Retiro"].notna() & viajes["Ciclo_Estacion_Arribo"].notna()
    if desde is not None:
        mask &= viajes["Fecha_Hora_Retiro"] >= desde
    if hasta is not None:
        mask &= viajes["Fecha_Hora_Retiro"] < hasta
    return viajes[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Punto de entrada principal
# ---------------------------------------------------------------------------

def cargar_datos(
    validos: bool = True,
    ruta_viajes=RUTA_VIAJES,
    ruta_estaciones=RUTA_ESTACIONES,
    **filtros,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga, limpia y prepara todo. Regresa (viajes, estaciones).

    - validos=True aplica `filtrar_validos` (los kwargs extra se le pasan, p. ej. desde=..., dur_max=...).
    - validos=False regresa todos los viajes limpios, sin filtrar.
    """
    estaciones = cargar_estaciones(ruta_estaciones)
    viajes = limpiar_viajes(cargar_viajes_raw(ruta_viajes))
    viajes = agregar_columnas(viajes, estaciones)
    if validos:
        viajes = filtrar_validos(viajes, **filtros)
    return viajes, estaciones


# ---------------------------------------------------------------------------
# Tablas de análisis frecuentes
# ---------------------------------------------------------------------------

def uso_por_estacion(viajes: pd.DataFrame, estaciones: pd.DataFrame | None = None) -> pd.DataFrame:
    """Retiros, arribos, total y neto (arribos − retiros) por estación."""
    uso = pd.DataFrame({
        "Retiros": viajes["Ciclo_Estacion_Retiro"].value_counts(),
        "Arribos": viajes["Ciclo_Estacion_Arribo"].value_counts(),
    }).fillna(0).astype(int)
    uso.index.name = "num_cicloe"
    uso["Total"] = uso["Retiros"] + uso["Arribos"]
    uso["Neto"] = uso["Arribos"] - uso["Retiros"]
    if estaciones is not None:
        uso.insert(0, "Estacion", uso.index.map(estaciones["Estacion"]))
    return uso


def matriz_od(viajes: pd.DataFrame, incluir_circulares: bool = True, simetrica: bool = False) -> pd.DataFrame:
    """Matriz origen-destino: filas = estación de retiro, columnas = estación de arribo.

    simetrica=True suma ambos sentidos (A→B + B→A).
    """
    v = viajes if incluir_circulares else viajes[~viajes["Viaje_Circular"]]
    m = pd.crosstab(v["Ciclo_Estacion_Retiro"], v["Ciclo_Estacion_Arribo"])
    if simetrica:
        m = m.add(m.T, fill_value=0).astype(int)
    return m


def destinos_por_estacion(viajes: pd.DataFrame, estaciones: pd.DataFrame | None = None) -> dict[int, pd.DataFrame]:
    """Diccionario {estación de origen: tabla de destinos con número de viajes, de mayor a menor}."""
    conteos = (
        viajes.groupby(["Ciclo_Estacion_Retiro", "Ciclo_Estacion_Arribo"])
              .size().rename("Num_Viajes").reset_index()
    )
    if estaciones is not None:
        conteos["Destino"] = conteos["Ciclo_Estacion_Arribo"].map(estaciones["Estacion"])
    return {
        int(est): g.drop(columns="Ciclo_Estacion_Retiro")
                   .sort_values("Num_Viajes", ascending=False)
                   .reset_index(drop=True)
        for est, g in conteos.groupby("Ciclo_Estacion_Retiro")
    }


# ---------------------------------------------------------------------------
# Estilo de gráficas
# ---------------------------------------------------------------------------

def aplicar_estilo():
    """Estilo de matplotlib usado en el proyecto."""
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "axes.prop_cycle": plt.cycler(color=["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                                             "#e87ba4", "#008300", "#6250d6", "#e34948"]),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#e6e5e0",
        "grid.linewidth": 0.8,
        "lines.linewidth": 2,
        "lines.markersize": 5,
    })


if __name__ == "__main__":
    viajes, estaciones = cargar_datos()
    print(f"Viajes válidos: {len(viajes):,}")
    print(f"Estaciones: {len(estaciones):,}")
    print(viajes.dtypes)
