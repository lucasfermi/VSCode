"""Trilha 2 — Densidade Estimada de Kernel (KDE).

Segue o código R do Manual (item 3.3): projeção de Mercator, grade de células de
500 m, núcleo gaussiano truncado em 3 larguras de banda, normalização por
n x 2 x pi x h^2, densidade da célula mais próxima atribuída a cada sinistro e,
como críticos, os do último quartil das densidades atribuídas aos sinistros
(nível 4 do ``find_decil`` do código, o que vai para o mapa e para a tabela de
trechos críticos).

Unidade do quartil (``unidade``):

* ``sinistros`` (padrão, Manual): cada sinistro é um registro. Numa planilha de
  segmentos os sinistros estão no meio do segmento, então o segmento conta no
  quartil tantas vezes quanto tem sinistros, e a grade e a normalização usam só os
  sinistros. Segmento sem sinistro não tem registro: fica sem densidade e nunca é
  crítico. Com o input da análise prévia (DF, MG e PE), o resultado é igual ao do
  código R em todos os segmentos.
* ``segmentos`` (v4): cada segmento é um ponto, inclusive os sem sinistros, e o
  quartil é tomado sobre os segmentos: um quarto deles sai crítico por construção.

Diferença de implementação para a v4: em vez de calcular a densidade em todas as
células da grade (milhões de células em escala estadual) e montar uma matriz
pontos x células, a densidade é calculada só nas células que contêm pontos, com
busca de vizinhos por KD-tree. O resultado é o mesmo até a precisão de máquina.
"""
import itertools

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from utils.constantes import COLUNAS_SINISTROS

R_TERRA = 6378137.0
UNIDADES = {"sinistros": "Sinistros (Manual)", "segmentos": "Segmentos (v4)"}


def projetar_mercator(lat, lon):
    """Projeção de Mercator esférica usada no Manual (item 3.3.2)."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    return R_TERRA * np.radians(lon), R_TERRA * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def _celulas(x, y, bandwidth, cell_size):
    """Origem da grade e célula de cada ponto (mesma grade da v4 e do R)."""
    x_min, y_min = x.min() - bandwidth, y.min() - bandwidth
    # ceil(.) - 1 reproduz o desempate do which.min/argmin (ponto na divisa -> célula de menor índice)
    ix = np.maximum(np.ceil((x - x_min) / cell_size).astype(np.int64) - 1, 0)
    iy = np.maximum(np.ceil((y - y_min) / cell_size).astype(np.int64) - 1, 0)
    return x_min, y_min, ix, iy


def densidade_kde(x, y, pesos, bandwidth=1000.0, cell_size=500.0, raio_corte=3.0, bloco=4096, n=None):
    """Densidade da célula da grade que contém cada ponto (mesma grade da v4 e do R).

    Pontos sem coordenada recebem NaN. A normalização usa ``n`` registros (padrão: o total de pontos, como na
    v4). Pontos com coordenadas idênticas são somados antes (resultado idêntico) e as células são processadas
    em blocos, o que limita a memória mesmo com centenas de milhares de pontos.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    pesos = np.asarray(pesos, float)
    n_total = len(x) if n is None else n
    dens = np.full(len(x), np.nan)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(pesos)
    if not ok.any():
        return dens
    xo, yo, wo = x[ok], y[ok], pesos[ok]
    x_min, y_min, ix, iy = _celulas(xo, yo, bandwidth, cell_size)
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


def soma_pesos_celula(x, y, pesos, bandwidth=1000.0, cell_size=500.0):
    """Soma dos pesos dos pontos da célula de cada ponto (``somar_pontos_dentro`` do código R)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    _, _, ix, iy = _celulas(x, y, bandwidth, cell_size)
    _, inv = np.unique(np.column_stack([ix, iy]), axis=0, return_inverse=True)
    inv = inv.ravel()
    return np.bincount(inv, weights=np.asarray(pesos, float))[inv]


def _niveis(valores, registros):
    """Nível de 1 a 4 de cada valor pelos quartis dos registros (``find_decil`` do código R)."""
    quebras = np.percentile(registros, [25, 50, 75, 100])
    return np.searchsorted(quebras, valores, side="left") + 1


def aplicar_kernel(df, bandwidth=1000.0, cell_size=500.0, percentil=75.0, unidade="sinistros"):
    """Aplica a Trilha 2. O peso de cada ponto é a coluna UPS (pesos escolhidos na interface)."""
    if unidade not in UNIDADES:
        raise ValueError(f"Unidade do quartil desconhecida: {unidade}")
    df_res = df.copy()
    if "UPS" in df_res:
        df_res["peso"] = df_res["UPS"].astype(float)
    else:  # compatibilidade: pesos padrão do Manual
        df_res["peso"] = df_res["sem_vitima"] * 1 + df_res["com_vitima"] * 4 + df_res["com_obito"] * 28
        df_res["UPS"] = df_res["peso"]

    lat = pd.to_numeric(df_res.get("latitude"), errors="coerce")
    lon = pd.to_numeric(df_res.get("longitude"), errors="coerce")
    validos = (lat.notna() & lon.notna()).to_numpy()
    if validos.sum() < 2:
        raise ValueError("A Trilha 2 precisa de pelo menos 2 segmentos com latitude e longitude.")
    avisos = []
    if (~validos).any():
        avisos.append(f"{int((~validos).sum())} segmento(s) sem coordenadas ficaram fora da Trilha 2.")

    x, y = projetar_mercator(lat, lon)
    df_res["x_proj"], df_res["y_proj"] = x, y
    peso = df_res["peso"].to_numpy(float)
    attrs = {}
    if unidade == "segmentos":
        dens = densidade_kde(x, y, peso, bandwidth, cell_size)
        dens_validas = dens[validos]
        limite = float(np.percentile(dens_validas, percentil))
        # densidade zero (nenhum sinistro no raio do núcleo) nunca é crítica: quando a maioria dos segmentos não
        # tem sinistros por perto, o limite seria zero e todos virariam críticos
        critico = (dens >= limite) & (dens > 0) & validos
        if limite <= 0:
            avisos.append(f"{percentil:g}% ou mais dos segmentos não têm sinistros num raio de "
                          f"{3 * bandwidth / 1000:g} km (densidade zero): só os de densidade positiva contam como "
                          "críticos.")
        quartis = np.percentile(dens_validas, [25, 50, 75])
        nivel = np.where(validos, np.searchsorted(quartis, dens, side="left") + 1, np.nan)
        n_registros = int(validos.sum())
    else:
        if "total_sinistros" in df_res:
            contagem = pd.to_numeric(df_res["total_sinistros"], errors="coerce")
        else:
            contagem = df_res[[c for c in COLUNAS_SINISTROS if c in df_res]].apply(pd.to_numeric, errors="coerce").sum(
                axis=1)
        contagem = contagem.fillna(0).to_numpy(float)
        if (np.abs(contagem - np.rint(contagem)) > 1e-9).any():
            avisos.append("Há contagens de sinistros não inteiras: arredondadas para o quartil sobre os sinistros.")
        contagem = np.rint(contagem).astype(np.int64)
        com = validos & (contagem > 0)
        if not com.any():
            raise ValueError("A Trilha 2 precisa de pelo menos um segmento com sinistros e coordenadas.")
        n_registros = int(contagem[com].sum())
        dens = np.full(len(df_res), np.nan)
        dens[com] = densidade_kde(x[com], y[com], peso[com], bandwidth, cell_size, n=n_registros)
        registros = np.repeat(dens[com], contagem[com])          # um valor por sinistro, como no código R
        limite = float(np.percentile(registros, percentil))
        nivel = np.full(len(df_res), np.nan)
        nivel[com] = _niveis(dens[com], registros)
        if percentil == 75:
            # código R do Manual: críticos = registros do maior nível (nível 4: densidade acima do P75)
            critico = com & (nivel == nivel[com].max())
        else:
            critico = com & (dens > limite)
            if not critico.any():
                critico = com & (dens >= limite)
        # avaliação do modelo no código R: hotspot_kde (>= P75) x hotspot_pesos (soma da UPS na célula >= P75)
        soma = soma_pesos_celula(x[com], y[com], peso[com], bandwidth, cell_size)
        hotspot_kde = dens[com] >= limite
        hotspot_pesos = soma >= np.percentile(np.repeat(soma, contagem[com]), percentil)
        attrs["coincidencia"] = float(100 * np.average(hotspot_kde == hotspot_pesos, weights=contagem[com]))
        sem = validos & (contagem == 0)
        if sem.any():
            avisos.append(f"{int(sem.sum())} segmento(s) sem sinistros: no Manual só os sinistros têm densidade, "
                          "então esses segmentos ficam sem densidade e não são críticos.")

    df_res["densidade"] = dens
    df_res["nivel_densidade"] = nivel
    df_res["hotspot_kde"] = critico
    df_res["Criticidade"] = np.where(critico, "Crítico", "Não Crítico")
    df_res["score_kernel"] = df_res["densidade"]
    df_res["Critico"] = critico
    maximo = np.nanmax(dens[validos]) if np.isfinite(dens[validos]).any() else 0.0
    df_res["indice_densidade"] = 100 * df_res["densidade"] / maximo if maximo > 0 else 0.0

    df_res = df_res.sort_values(by="score_kernel", ascending=False, na_position="last").reset_index(drop=True)
    df_res.attrs.update({"avisos": avisos, "limite": limite, "bandwidth": bandwidth, "cell_size": cell_size,
                         "percentil": percentil, "unidade": unidade, "registros": n_registros, **attrs})
    return df_res
