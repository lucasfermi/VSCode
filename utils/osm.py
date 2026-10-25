"""Malha do OpenStreetMap para as vias que o SNV não cobre (estaduais e municipais).

Fluxo:

1. ``ler_vias_osm``: vias de um arquivo do OpenStreetMap (.osm.pbf regional da Geofabrik, GeoPackage
   ou GeoJSON) dentro de um retângulo, filtradas por classe (``highway``).
2. ``montar_vias``: tira o que o SNV já cobre (a até 40 m de um trecho federal com pista), junta os
   pedaços com o mesmo código (ex.: DF-001) ou nome em vias contínuas e deixa uma só pista onde a via
   é duplicada (pistas paralelas a até 60 m).
3. ``cortar_vias``: segmentos de L km ao longo de cada via, com a mesma regra de sobra do SNV.
4. ``agregar_osm``: sinistros com coordenada presos ao segmento mais próximo (até 50 m).

Dados © colaboradores do OpenStreetMap, licença ODbL: a atribuição acompanha mapas e relatórios.
"""
from __future__ import annotations

import io
import re
import unicodedata

import numpy as np
import pandas as pd
import shapely
from shapely.ops import substring

from utils.segmentacao import (
    _PARA_GEO,
    _PARA_METRICO,
    COMPRIMENTO_PADRAO,
    GRAVIDADES,
    LIMITES_COMPRIMENTO,
    _transformar,
    _trechos_base,
    cortes_do_trecho,
)

ATRIBUICAO = "© colaboradores do OpenStreetMap (ODbL)"
CLASSES_PRINCIPAIS = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified"]
CLASSES_URBANAS = ["residential", "living_street"]
NOMES_CLASSES = {
    "motorway": "via expressa", "trunk": "via arterial principal", "primary": "via principal",
    "secondary": "via secundária", "tertiary": "via coletora", "unclassified": "via local",
    "residential": "rua residencial", "living_street": "via compartilhada",
}
ORDEM_CLASSES = {c: i for i, c in enumerate(CLASSES_PRINCIPAIS + CLASSES_URBANAS)}
DISTANCIA_SNV_M = 40.0          # via do OSM a até 40 m de um trecho do SNV é a mesma rodovia
DISTANCIA_PISTA_DUPLA_M = 60.0  # pistas paralelas da mesma via a até 60 m viram uma só
COMPRIMENTO_MINIMO_M = 50.0     # sobras menores (pedaços de cruzamento) são descartadas
TOLERANCIA_OSM_M = 50.0         # distância máxima entre o sinistro e a via


def _tag(outras: pd.Series, chave: str) -> pd.Series:
    return outras.fillna("").str.extract(rf'"{chave}"=>"([^"]*)"', expand=False)


def ler_vias_osm(fonte, bbox=None, classes=None) -> pd.DataFrame:
    """Vias do OpenStreetMap (caminho ou bytes) no retângulo ``bbox`` = (oeste, sul, leste, norte), em
    graus. Requer o pyogrio (a GDAL embutida lê o .osm.pbf)."""
    from pyogrio.raw import read

    classes = list(classes or CLASSES_PRINCIPAIS)
    fonte = io.BytesIO(fonte) if isinstance(fonte, bytes) else fonte
    lista = ", ".join(f"'{c}'" for c in classes)
    opcoes = {"bbox": tuple(bbox)} if bbox is not None else {}
    try:
        meta, _, geom, campos = read(fonte, layer="lines", where=f"highway IN ({lista})", **opcoes)
    except Exception:   # GeoPackage/GeoJSON já recortado: camada única
        if hasattr(fonte, "seek"):
            fonte.seek(0)
        meta, _, geom, campos = read(fonte, where=f"highway IN ({lista})", **opcoes)
    df = pd.DataFrame(dict(zip(meta["fields"], campos)))
    outras = df["other_tags"] if "other_tags" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    refs = (df["ref"] if "ref" in df else _tag(outras, "ref")).astype("string")
    out = pd.DataFrame({
        "osm_id": df["osm_id"].astype(str) if "osm_id" in df else df.index.astype(str),
        "nome": df["name"].astype("string").str.strip() if "name" in df else pd.NA,
        "ref": refs.str.split(";").str[0].str.strip(),
        "federal": refs.fillna("").str.upper().str.contains(r"(?:^|;)\s*BR[- ]?\d", regex=True),
        "classe": df["highway"].astype(str),
        "geometry": shapely.from_wkb(geom),
    })
    return out[shapely.get_type_id(out["geometry"].to_numpy()) == 1].reset_index(drop=True)


def _normalizar(texto: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", s).strip()


def _fora_do_snv(geoms_m: np.ndarray, snv: pd.DataFrame | None) -> np.ndarray:
    """Retira de cada via o trecho a até ``DISTANCIA_SNV_M`` de uma rodovia do SNV com pista."""
    if snv is None or not len(geoms_m):
        return geoms_m
    base = _trechos_base(snv)["geom_m"].to_numpy()
    arvore = shapely.STRtree(base)
    i_via, i_snv = arvore.query(geoms_m, predicate="dwithin", distance=DISTANCIA_SNV_M)
    saida = geoms_m.copy()
    for i in np.unique(i_via):
        perto = shapely.union_all(shapely.buffer(base[i_snv[i_via == i]], DISTANCIA_SNV_M))
        saida[i] = shapely.difference(geoms_m[i], perto)
    return saida


def montar_vias(vias_osm: pd.DataFrame, snv: pd.DataFrame | None = None) -> pd.DataFrame:
    """Vias contínuas (geometria em metros), fora do SNV e com uma pista só nas vias duplicadas. Com o
    SNV, as vias que o OSM marca como federais (código BR-) também saem: elas são do SNV."""
    v = vias_osm.copy()
    if snv is not None and "federal" in v:
        v = v[~v["federal"]]
    v["geom_m"] = _fora_do_snv(_transformar(v["geometry"].to_numpy(), _PARA_METRICO), snv)
    v = v[~shapely.is_empty(v["geom_m"].to_numpy())]
    v["chave"] = v["ref"].where(v["ref"].fillna("").str.len() > 0, v["nome"])
    v["chave"] = v["chave"].map(lambda c: _normalizar(c) if isinstance(c, str) and c.strip() else None)
    sem_nome = v["chave"].isna()
    v.loc[sem_nome, "chave"] = "SEM NOME " + v.loc[sem_nome, "classe"].str.upper()

    vias = []
    for chave, g in v.groupby("chave", sort=True):
        classe = min(g["classe"], key=lambda c: ORDEM_CLASSES.get(c, 99))
        rotulo = g["ref"].dropna().iloc[0] if g["ref"].notna().any() else (
            g["nome"].dropna().iloc[0] if g["nome"].notna().any() else None)
        nome = g["nome"].dropna().iloc[0] if g["nome"].notna().any() else None
        if sem_nome[g.index].all():   # vias sem nome nem código ficam como estão no OSM
            for geom, cls in zip(g["geom_m"], g["classe"]):
                for p in shapely.get_parts(geom):
                    if shapely.get_type_id(p) == 1 and p.length >= COMPRIMENTO_MINIMO_M:
                        vias.append((chave, None, None, cls, p))
            continue
        juntas = shapely.line_merge(shapely.union_all(g["geom_m"].to_numpy()))
        pecas = sorted((p for p in shapely.get_parts(juntas) if shapely.get_type_id(p) == 1
                        and p.length >= COMPRIMENTO_MINIMO_M), key=lambda p: -p.length)
        if not pecas:
            continue
        arvore = shapely.STRtree(pecas)
        mantida = np.zeros(len(pecas), dtype=bool)
        for i, p in enumerate(pecas):
            vizinhas = [j for j in arvore.query(p, predicate="dwithin", distance=DISTANCIA_PISTA_DUPLA_M)
                        if j < i and mantida[j]]
            if vizinhas:
                faixa = shapely.union_all(shapely.buffer(np.array(pecas, dtype=object)[vizinhas],
                                                         DISTANCIA_PISTA_DUPLA_M))
                if shapely.intersection(p, faixa).length >= 0.8 * p.length:
                    continue   # pista paralela (ou repetida) de uma via já incluída
            mantida[i] = True
            vias.append((chave, rotulo, nome, classe, p))
    out = pd.DataFrame(vias, columns=["chave", "rotulo", "nome", "classe", "geom_m"])
    out["comprimento_m"] = shapely.length(out["geom_m"].to_numpy()) if len(out) else []
    out = out.sort_values(["classe", "chave", "comprimento_m"], key=lambda s: s.map(ORDEM_CLASSES) if s.name == "classe"
                          else s).reset_index(drop=True)
    out["codigo_via"] = [f"OSM{i:06d}" for i in range(1, len(out) + 1)]
    return out


def _km(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def cortar_vias(vias: pd.DataFrame, comprimento: float = COMPRIMENTO_PADRAO, fundir_resto: bool = True,
                fracao_minima: float = 0.5) -> pd.DataFrame:
    """Segmentos de ``comprimento`` km ao longo de cada via do OSM (km contado do início da via)."""
    lo, hi = LIMITES_COMPRIMENTO
    if not lo <= comprimento <= hi:
        raise ValueError(f"O comprimento do segmento deve ficar entre {lo:g} e {hi:g} km.")
    linhas = []
    for r in vias.itertuples(index=False):
        ext = r.comprimento_m / 1000
        cortes = cortes_do_trecho(ext, comprimento, fundir_resto, fracao_minima)
        for k, (a, b) in enumerate(zip(cortes[:-1], cortes[1:]), start=1):
            linhas.append((r.codigo_via, k, r.classe, r.rotulo, r.nome, a, b, a / ext, b / ext, r.geom_m))
    seg = pd.DataFrame(linhas, columns=["codigo_via", "ordem", "classe", "rotulo", "nome", "km_inicial", "km_final",
                                        "frac_inicial", "frac_final", "geom_m"])
    if seg.empty:
        return seg.assign(segmento_id=pd.Series(dtype=str))
    seg["segmento_id"] = seg["codigo_via"] + "-" + seg["ordem"].astype(str).str.zfill(3)
    seg["extensao_trecho"] = (seg["km_final"] - seg["km_inicial"]).round(4)
    seg["geom_m"] = [substring(g, fa, fb, normalized=True)
                     for g, fa, fb in zip(seg["geom_m"], seg["frac_inicial"], seg["frac_final"])]
    meio = shapely.line_interpolate_point(seg["geom_m"].to_numpy(), 0.5, normalized=True)
    lon, lat = _PARA_GEO.transform(shapely.get_x(meio), shapely.get_y(meio))
    seg["latitude"], seg["longitude"] = lat, lon
    seg["geometry"] = _transformar(seg["geom_m"].to_numpy(), _PARA_GEO)
    nome = seg["rotulo"].fillna(seg["classe"].map(NOMES_CLASSES).fillna(seg["classe"]) + " sem nome")
    extra = np.where(seg["nome"].notna() & (seg["nome"] != seg["rotulo"]), " (" + seg["nome"].fillna("") + ")", "")
    seg["rodovia"] = (nome + extra + ", km " + seg["km_inicial"].map(_km) + " a " + seg["km_final"].map(_km)
                      + " da via")
    return seg


def agregar_osm(sinistros: pd.DataFrame, segmentos: pd.DataFrame, n_anos, tolerancia_m: float = TOLERANCIA_OSM_M):
    """Prende os sinistros (com latitude e longitude) ao segmento do OSM mais próximo e conta por
    segmento, no formato interno das trilhas. Retorna (dados, índices dos sinistros atribuídos)."""
    base = segmentos[["segmento_id", "latitude", "longitude", "extensao_trecho", "rodovia", "codigo_via", "classe",
                      "km_inicial", "km_final"]].copy()
    tem = sinistros["latitude"].notna() & sinistros["longitude"].notna()
    s = sinistros[tem]
    atribuidos = pd.Index([])
    contagem = pd.DataFrame(columns=["segmento_id", *GRAVIDADES])
    if len(s) and len(segmentos):
        x, y = _PARA_METRICO.transform(s["longitude"].to_numpy(float), s["latitude"].to_numpy(float))
        arvore = shapely.STRtree(segmentos["geom_m"].to_numpy())
        i_pt, i_seg = arvore.query_nearest(shapely.points(x, y), max_distance=tolerancia_m, all_matches=False)
        par = pd.DataFrame({"segmento_id": segmentos["segmento_id"].to_numpy()[i_seg],
                            "gravidade": s["gravidade"].to_numpy()[i_pt]})
        atribuidos = s.index[i_pt]
        if len(par):
            contagem = (par.groupby(["segmento_id", "gravidade"]).size().unstack("gravidade", fill_value=0)
                        .reindex(columns=GRAVIDADES, fill_value=0).reset_index())
    out = base.merge(contagem, on="segmento_id", how="left")
    out[GRAVIDADES] = out[GRAVIDADES].fillna(0).astype(int)
    out["volume_trafego"] = np.nan
    out["n_anos"] = n_anos
    out["fonte"] = "OpenStreetMap"
    return out, atribuidos
