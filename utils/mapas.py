"""Mapas folium com uma camada GeoJSON por grupo (mais leve que um marcador por linha)."""
import html

import folium
import numpy as np
from folium.plugins import HeatMap

AZUL = "#0988C3"
VERMELHO = "#D7191C"
CORES_QUARTIL = {1: "#2C7BB6", 2: "#1A9641", 3: "#FDAE61", 4: "#D7191C"}  # azul, verde, laranja, vermelho (Manual)


def _pontos(df, col_valor, nome_valor, extras=()):
    feats = []
    for r in df.itertuples(index=False):
        props = {
            "Segmento": html.escape(str(r.segmento_id)),
            nome_valor: f"{getattr(r, col_valor):.2f}",
            "Crítico": "Sim" if bool(r.Critico) else "Não",
        }
        for col, rotulo in extras:
            v = getattr(r, col, None)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                props[rotulo] = html.escape(str(v))
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [float(r.longitude), float(r.latitude)]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def _camada(fc, cor, raio, nome):
    campos = list(fc["features"][0]["properties"].keys()) if fc["features"] else []
    return folium.GeoJson(
        fc, name=nome,
        marker=folium.CircleMarker(radius=raio, weight=1, fill=True, fill_opacity=0.85),
        style_function=lambda _f, c=cor: {"color": c, "fillColor": c},
        popup=folium.GeoJsonPopup(fields=campos) if campos else None,
    )


def _base(df, largura=900, altura=480):
    """Centro e zoom calculados aqui (e não com fit_bounds), porque o mapa de uma aba oculta
    é criado com tamanho zero e o Leaflet erraria o enquadramento."""
    lat_min, lat_max = df["latitude"].min(), df["latitude"].max()
    lon_min, lon_max = df["longitude"].min(), df["longitude"].max()
    z_lon = np.log2(largura / 256 * 360 / max(lon_max - lon_min, 1e-3))
    z_lat = np.log2(altura / 256 * 180 / max(lat_max - lat_min, 1e-3))
    zoom = int(np.clip(np.floor(min(z_lon, z_lat)), 3, 15))
    return folium.Map(location=[(lat_min + lat_max) / 2, (lon_min + lon_max) / 2], zoom_start=zoom,
                      tiles="OpenStreetMap", control_scale=True)


def mapa_criticos(df, col_valor, nome_valor):
    """Pontos azuis (não críticos) e vermelhos (críticos)."""
    df_geo = df.dropna(subset=["latitude", "longitude", col_valor])
    if df_geo.empty:
        return None
    m = _base(df_geo)
    extras = [("rodovia", "Rodovia"), ("sentido", "Sentido")]
    nao = df_geo[~df_geo["Critico"].astype(bool)]
    sim = df_geo[df_geo["Critico"].astype(bool)]
    if len(nao):
        _camada(_pontos(nao, col_valor, nome_valor, extras), AZUL, 3, "Não críticos").add_to(m)
    if len(sim):
        _camada(_pontos(sim, col_valor, nome_valor, extras), VERMELHO, 5, "Críticos").add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def mapa_kde(df):
    """Segmentos coloridos pelo quartil da densidade (como no código R do Manual) e,
    em camada opcional, o mapa de calor apenas ilustrativo do Leaflet."""
    df_geo = df.dropna(subset=["latitude", "longitude", "densidade"])
    if df_geo.empty:
        return None
    m = _base(df_geo)
    HeatMap(df_geo[["latitude", "longitude", "UPS"]].to_numpy().tolist(), radius=15,
            name="Mapa de calor (ilustrativo)", show=False).add_to(m)
    nomes = {1: "1º quartil (menor densidade)", 2: "2º quartil", 3: "3º quartil", 4: "4º quartil (crítico)"}
    for nivel in (1, 2, 3, 4):
        parte = df_geo[df_geo["nivel_densidade"] == nivel]
        if len(parte):
            fc = _pontos(parte, "indice_densidade", "Índice de densidade (0-100)", [("UPS", "UPS")])
            _camada(fc, CORES_QUARTIL[nivel], 5 if nivel == 4 else 3, nomes[nivel]).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m
