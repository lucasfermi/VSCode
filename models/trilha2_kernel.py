"""Trilha 2 — Densidade Estimada de Kernel (KDE).

Segue o código R do Manual (item 3.3): projeção de Mercator, grade de células de
500 m, núcleo gaussiano truncado em 3 larguras de banda, normalização por
n x 2 x pi x h^2, densidade da célula mais próxima atribuída a cada ponto e
criticidade pelo quartil superior.

Diferença para a v4: em vez de calcular a densidade em todas as células da grade
(milhões de células em escala estadual) e montar uma matriz pontos x células, a
densidade é calculada só nas células que contêm pontos, com busca de vizinhos por
KD-tree. O resultado é o mesmo da v4 até a precisão de máquina.
"""
import itertools

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

R_TERRA = 6378137.0


def projetar_mercator(lat, lon):
    """Projeção de Mercator esférica usada no Manual (item 3.3.2)."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    return R_TERRA * np.radians(lon), R_TERRA * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def densidade_kde(x, y, pesos, bandwidth=1000.0, cell_size=500.0, raio_corte=3.0, bloco=4096):
    """Densidade da célula da grade que contém cada ponto (mesma grade da v4 e do R).

    Pontos sem coordenada recebem NaN. A normalização usa o total de pontos, como na v4.
    Pontos com coordenadas idênticas são somados antes (resultado idêntico) e as células
    são processadas em blocos, o que limita a memória mesmo com centenas de milhares de pontos.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    pesos = np.asarray(pesos, float)
    n_total = len(x)
    dens = np.full(n_total, np.nan)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(pesos)
    if not ok.any():
        return dens
    xo, yo, wo = x[ok], y[ok], pesos[ok]
    x_min, y_min = xo.min() - bandwidth, yo.min() - bandwidth
    # ceil(.) - 1 reproduz o desempate do which.min/argmin (ponto na divisa -> célula de menor índice)
    ix = np.maximum(np.ceil((xo - x_min) / cell_size).astype(np.int64) - 1, 0)
    iy = np.maximum(np.ceil((yo - y_min) / cell_size).astype(np.int64) - 1, 0)
    celulas, inv = np.unique(np.column_stack([ix, iy]), axis=0, return_inverse=True)
    cx = x_min + (celulas[:, 0] + 0.5) * cell_size
    cy = y_min + (celulas[:, 1] + 0.5) * cell_size

    # pontos repetidos (mesma coordenada) viram um ponto com a soma dos pesos
    coords, grupo = np.unique(np.column_stack([xo, yo]), axis=0, return_inverse=True)
    wu = np.bincount(grupo.ravel(), weights=wo, minlength=len(coords))
    arvore = cKDTree(coords)

    dens_cel = np.zeros(len(celulas))
    raio = raio_corte * bandwidth
    for ini in range(0, len(celulas), bloco):
        fim = min(ini + bloco, len(celulas))
        vizinhos = arvore.query_ball_point(np.column_stack([cx[ini:fim], cy[ini:fim]]), r=raio, workers=-1)
        tamanhos = np.fromiter((len(v) for v in vizinhos), dtype=np.int64, count=len(vizinhos))
        if tamanhos.sum() == 0:
            continue
        idx_cel = np.repeat(np.arange(ini, fim), tamanhos)
        idx_pt = np.fromiter(itertools.chain.from_iterable(vizinhos), dtype=np.int64, count=int(tamanhos.sum()))
        dist = np.sqrt((coords[idx_pt, 0] - cx[idx_cel]) ** 2 + (coords[idx_pt, 1] - cy[idx_cel]) ** 2)
        contrib = wu[idx_pt] * np.exp(-0.5 * (dist / bandwidth) ** 2)
        dens_cel[ini:fim] = np.bincount(idx_cel - ini, weights=contrib, minlength=fim - ini)
    dens_cel /= n_total * 2 * np.pi * bandwidth ** 2
    dens[ok] = dens_cel[inv.ravel()]
    return dens


def aplicar_kernel(df, bandwidth=1000.0, cell_size=500.0, percentil=75.0):
    """Aplica a Trilha 2. O peso de cada ponto é a coluna UPS (pesos escolhidos na interface)."""
    df_res = df.copy()
    if "UPS" in df_res:
        df_res["peso"] = df_res["UPS"].astype(float)
    else:  # compatibilidade: pesos padrão do Manual
        df_res["peso"] = df_res["sem_vitima"] * 1 + df_res["com_vitima"] * 4 + df_res["com_obito"] * 28
        df_res["UPS"] = df_res["peso"]

    lat = pd.to_numeric(df_res.get("latitude"), errors="coerce")
    lon = pd.to_numeric(df_res.get("longitude"), errors="coerce")
    validos = lat.notna() & lon.notna()
    if validos.sum() < 2:
        raise ValueError("A Trilha 2 precisa de pelo menos 2 segmentos com latitude e longitude.")
    avisos = []
    if (~validos).any():
        avisos.append(f"{int((~validos).sum())} segmento(s) sem coordenadas ficaram fora da Trilha 2.")

    x, y = projetar_mercator(lat, lon)
    df_res["x_proj"], df_res["y_proj"] = x, y
    df_res["densidade"] = densidade_kde(x, y, df_res["peso"].to_numpy(float), bandwidth, cell_size)

    dens_validas = df_res.loc[validos, "densidade"]
    limite = float(np.percentile(dens_validas, percentil))
    df_res["hotspot_kde"] = (df_res["densidade"] >= limite) & validos
    df_res["Criticidade"] = df_res["hotspot_kde"].map({True: "Crítico", False: "Não Crítico"})
    df_res["score_kernel"] = df_res["densidade"]
    df_res["Critico"] = df_res["hotspot_kde"]
    maximo = dens_validas.max()
    df_res["indice_densidade"] = 100 * df_res["densidade"] / maximo if maximo > 0 else 0.0
    quartis = np.percentile(dens_validas, [25, 50, 75])
    df_res["nivel_densidade"] = np.where(validos, np.searchsorted(quartis, df_res["densidade"], side="left") + 1,
                                         np.nan)

    df_res = df_res.sort_values(by="score_kernel", ascending=False, na_position="last").reset_index(drop=True)
    df_res.attrs.update({"avisos": avisos, "limite": limite, "bandwidth": bandwidth,
                         "cell_size": cell_size, "percentil": percentil})
    return df_res
