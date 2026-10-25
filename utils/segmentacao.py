"""Segmentação automática da malha rodoviária sobre o SNV do DNIT.

Fluxo:

1. ``carregar_snv`` e ``preparar_snv``: trechos do SNV (shapefile da publicação do DNIT), com o trecho
   principal de cada coincidência (BRs que dividem a mesma pista) e a geometria em metros.
2. ``ler_sinistros_prf``: sinistros por ocorrência dos dados abertos da PRF (datatran), com a gravidade
   no formato das trilhas.
3. ``localizar_sinistros``: posição de cada sinistro num trecho principal, como fração do trecho. No
   modo ``auto`` vale a coordenada, presa à BR informada; sem coordenada, vale o km.
4. ``cortar_segmentos``: cada trecho com pista vira segmentos de L km (1 km por padrão) que não
   atravessam o limite do trecho, medidos na quilometragem do SNV (padrão) ou na geometria.
5. ``agregar_por_segmento``: sinistros por segmento, no formato interno das trilhas.

As geometrias do SNV são digitalizadas no sentido crescente do km (96% dos trechos conferidos com os
sinistros da PRF; os demais são curtos ou têm poucos sinistros).
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.ops import substring

CRS_SNV = "EPSG:4674"          # SIRGAS 2000: coordenadas do SNV e da PRF
CRS_METRICO = "EPSG:5880"      # SIRGAS 2000 / Brazil Polyconic: distâncias e cortes em metros
SUPERFICIES_SEM_PISTA = {"PLA", "TRV"}   # rodovia planejada e travessia (balsa)
COMPRIMENTO_PADRAO = 1.0       # km, recomendação do Manual
# Limites técnicos: 0,1 km é a resolução do km nos boletins da PRF. O intervalo recomendado para
# análise deve sair da literatura de segmentação.
LIMITES_COMPRIMENTO = (0.1, 10.0)
TOLERANCIA_M = 500.0           # distância máxima entre a coordenada do sinistro e a rodovia informada
TOLERANCIA_COORD_M = 100.0     # sinistros só com coordenada (sem BR e km): até 100 m de uma rodovia
LOCALIZADO_OSM = "localizado no OpenStreetMap"
COLUNAS_SNV = ["vl_br", "sg_uf", "vl_codigo", "sg_tipo_tr", "desc_coinc", "ds_coinc", "vl_km_inic",
               "vl_km_fina", "ds_sup_fed"]
LOCALIZADO_COORD = "localizado pela coordenada"
LOCALIZADO_KM = "localizado pelo km"
SEM_PISTA = "em trecho sem pista (planejado ou travessia)"
EM_OUTRA_UF = "em rodovia federal de outra UF"
LONGE_DO_SNV = "coordenada longe do SNV"
SITUACOES_LOCALIZADAS = (LOCALIZADO_COORD, LOCALIZADO_KM)
GRAVIDADES = ["sem_vitima", "com_vitima", "com_obito"]

_PARA_METRICO = Transformer.from_crs(CRS_SNV, CRS_METRICO, always_xy=True)
_PARA_GEO = Transformer.from_crs(CRS_METRICO, CRS_SNV, always_xy=True)


def _transformar(geometrias, transformador):
    return shapely.transform(
        np.asarray(geometrias, dtype=object),
        lambda xy: np.column_stack(transformador.transform(xy[:, 0], xy[:, 1])))


def _numero(serie: pd.Series) -> pd.Series:
    """Texto com vírgula decimal (padrão da PRF) para número."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    return pd.to_numeric(serie.astype("string").str.strip().str.replace(",", ".", regex=False), errors="coerce")


# ---------------------------------------------------------------------------------------------------
# 1. SNV
# ---------------------------------------------------------------------------------------------------
def _ler_vetorial(fonte) -> pd.DataFrame:
    """Lê camada vetorial (caminho ou bytes, inclusive .zip) com o pyogrio, em SIRGAS 2000."""
    from pyogrio.raw import read

    meta, _, geometria, campos = read(fonte)
    df = pd.DataFrame(dict(zip(meta["fields"], campos)))
    geoms = shapely.from_wkb(geometria)
    crs = meta.get("crs")
    if crs and crs.upper() != CRS_SNV:
        geoms = _transformar(geoms, Transformer.from_crs(crs, CRS_SNV, always_xy=True))
    df["geometry"] = geoms
    return df


def carregar_snv(caminho) -> pd.DataFrame:
    """Lê o shapefile ou GeoPackage do SNV (requer o pacote pyogrio)."""
    return _ler_vetorial(caminho)


def ler_snv_enviado(arquivos: list[tuple[str, bytes]]) -> pd.DataFrame:
    """SNV enviado pelo usuário: um .zip com o shapefile ou os arquivos .shp, .shx, .dbf e .prj."""
    zips = [c for n, c in arquivos if n.lower().endswith(".zip")]
    if zips:
        conteudo = zips[0]
    else:
        partes = {n.rsplit(".", 1)[-1].lower(): (n, c) for n, c in arquivos if "." in n}
        falta = [e for e in ("shp", "shx", "dbf") if e not in partes]
        if falta:
            raise ValueError("Para o shapefile do SNV, envie juntos os arquivos .shp, .shx, .dbf e .prj "
                             f"(faltou: .{', .'.join(falta)}).")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for ext, (_, c) in partes.items():
                z.writestr(f"snv.{ext}", c)
        conteudo = buf.getvalue()
    return _ler_vetorial(conteudo)


def preparar_snv(trechos: pd.DataFrame) -> pd.DataFrame:
    """Normaliza os trechos do SNV e acrescenta ``codigo_principal``, ``invertido`` (o trecho
    coincidente corre no sentido oposto ao principal), ``com_pista`` e ``geom_m`` (metros)."""
    falta = [c for c in [*COLUNAS_SNV, "geometry"] if c not in trechos]
    if falta:
        raise ValueError("O arquivo do SNV não tem as colunas: " + ", ".join(falta) + ".")
    t = trechos.copy()
    t["vl_br"] = t["vl_br"].astype(str).str.strip().str.zfill(3)
    t["sg_uf"] = t["sg_uf"].astype(str).str.strip().str.upper()
    t["vl_codigo"] = t["vl_codigo"].astype(str).str.strip()
    t["sg_tipo_tr"] = t["sg_tipo_tr"].astype(str).str.strip().str.upper()
    t["km_ini"] = _numero(t["vl_km_inic"])
    t["km_fim"] = _numero(t["vl_km_fina"])
    t = t[t["km_ini"].notna() & t["km_fim"].notna() & (t["km_fim"] > t["km_ini"]) & t["geometry"].notna()]
    t = t.drop_duplicates("vl_codigo")
    geoms = t["geometry"].to_numpy()
    multi = shapely.get_type_id(geoms) == 5
    if multi.any():   # MultiLineString contínua vira LineString
        geoms = geoms.copy()
        geoms[multi] = shapely.line_merge(geoms[multi])
        t["geometry"] = geoms
    t = t[shapely.get_type_id(t["geometry"].to_numpy()) == 1].reset_index(drop=True)

    eh_principal = t["desc_coinc"].fillna("-").astype(str).str.strip().eq("-")
    principais = set(t.loc[eh_principal, "vl_codigo"])

    def principal_de(codigo, coincidentes):
        for c in str(coincidentes).split(";"):
            if c.strip() in principais:
                return c.strip()
        return codigo

    t["codigo_principal"] = [c if p else principal_de(c, k)
                             for c, k, p in zip(t["vl_codigo"], t["ds_coinc"], eh_principal)]
    t["com_pista"] = ~t["ds_sup_fed"].astype(str).str.strip().str.upper().isin(SUPERFICIES_SEM_PISTA)
    t["geom_m"] = _transformar(t["geometry"].to_numpy(), _PARA_METRICO)
    t["comprimento_m"] = shapely.length(t["geom_m"].to_numpy())

    idx = t.set_index("vl_codigo")
    gp = idx.loc[t["codigo_principal"], "geom_m"].to_numpy()
    g = t["geom_m"].to_numpy()
    ini_c = shapely.get_point(g, 0)
    t["invertido"] = (shapely.distance(ini_c, shapely.get_point(gp, 0))
                      > shapely.distance(ini_c, shapely.get_point(gp, -1)))
    t.loc[eh_principal.to_numpy(), "invertido"] = False
    if "versao_snv" not in t:
        t["versao_snv"] = pd.NA
    return t


def _trechos_base(snv: pd.DataFrame) -> pd.DataFrame:
    """Trechos principais com pista: a malha física, sem duplicar BRs coincidentes."""
    return snv[snv["com_pista"] & snv["vl_codigo"].eq(snv["codigo_principal"])]


# ---------------------------------------------------------------------------------------------------
# 2. Sinistros da PRF
# ---------------------------------------------------------------------------------------------------
def ler_sinistros_prf(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza os dados abertos da PRF por ocorrência (arquivos datatran).

    Os arquivos "agrupados por pessoa" repetem a ocorrência em uma linha por pessoa, causa e tipo; as
    repetições do mesmo ``id`` são descartadas e contadas em ``attrs['linhas_repetidas']``.
    """
    falta = [c for c in ("data_inversa", "uf", "br", "km") if c not in df]
    if falta:
        raise ValueError("O arquivo da PRF não tem as colunas: " + ", ".join(falta) + ".")
    n_linhas = len(df)
    if "id" in df:
        df = df.drop_duplicates("id")
    data = pd.to_datetime(df["data_inversa"], errors="coerce", format="%Y-%m-%d")
    sem_data = data.isna()
    if sem_data.any():   # arquivos antigos usam dd/mm/aaaa
        data[sem_data] = pd.to_datetime(df.loc[sem_data, "data_inversa"], errors="coerce", dayfirst=True)
    br = _numero(df["br"])
    out = pd.DataFrame({
        "id": df["id"].astype(str) if "id" in df else pd.Series(range(len(df)), index=df.index).astype(str),
        "data": data,
        "ano": data.dt.year.astype("Int64"),
        "uf": df["uf"].astype("string").str.strip().str.upper(),
        "br": br.round().astype("Int64").astype("string").str.zfill(3),
        "km": _numero(df["km"]),
        "latitude": _numero(df["latitude"]) if "latitude" in df else np.nan,
        "longitude": _numero(df["longitude"]) if "longitude" in df else np.nan,
    })
    fora = ~out["latitude"].between(-34.5, 6) | ~out["longitude"].between(-75, -32)
    out.loc[fora, ["latitude", "longitude"]] = np.nan

    sentido = df["sentido_via"].astype("string").str.strip().str.lower() if "sentido_via" in df else None
    out["sentido"] = (pd.Series(pd.NA, index=df.index, dtype="string") if sentido is None else
                      sentido.map({"crescente": "Crescente", "decrescente": "Decrescente"}).astype("string"))

    cls = (df["classificacao_acidente"].astype("string").str.lower().fillna("")
           if "classificacao_acidente" in df else pd.Series("", index=df.index))
    mortos = _numero(df["mortos"]).fillna(0) if "mortos" in df else 0
    feridos = _numero(df["feridos"]).fillna(0) if "feridos" in df else 0
    sem_cls = cls.eq("")
    obito = cls.str.contains("fata") | (sem_cls & (mortos > 0))
    vitima = ~obito & (cls.str.contains("ferid") | (sem_cls & (feridos > 0)))
    out["gravidade"] = np.select([obito, vitima], ["com_obito", "com_vitima"], "sem_vitima")
    out = out.reset_index(drop=True)
    out.attrs["linhas_repetidas"] = n_linhas - len(out)
    return out


def ler_arquivos_prf(arquivos: list[tuple[str, bytes]]) -> pd.DataFrame:
    """Arquivos datatran da PRF (.csv ou .zip com o .csv), já normalizados por ``ler_sinistros_prf``."""
    tabelas = []
    for nome, conteudo in arquivos:
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
                if not csvs:
                    raise ValueError(f"O arquivo {nome} não tem nenhum .csv dentro.")
                conteudos = [z.read(n) for n in csvs]
        else:
            conteudos = [conteudo]
        for c in conteudos:
            for codificacao in ("utf-8-sig", "latin-1"):
                try:
                    tabelas.append(pd.read_csv(io.BytesIO(c), sep=";", dtype=str, encoding=codificacao))
                    break
                except UnicodeDecodeError:
                    continue
    if not tabelas:
        raise ValueError("Nenhum arquivo da PRF foi lido.")
    return ler_sinistros_prf(pd.concat(tabelas, ignore_index=True))


def ler_sinistros_pontuais(df: pd.DataFrame) -> pd.DataFrame:
    """Sinistros de outras fontes (DETRAN, município, Infosiga): uma linha por sinistro, com latitude e
    longitude. A gravidade vem de uma coluna de texto (gravidade, classificação) ou das contagens da
    linha: com óbito (ou mortos) > 0 é óbito; com vítima (ou feridos) > 0 é vítima; senão, sem vítima."""
    from utils.entrada import normalizar_nome

    nomes = {normalizar_nome(c): c for c in df.columns}

    def achar(*opcoes):
        return next((nomes[o] for o in opcoes if o in nomes), None)

    c_lat = achar("latitude", "lat", "latitude_media")
    c_lon = achar("longitude", "lon", "long", "lng", "longitude_media")
    if not (c_lat and c_lon):
        raise ValueError("A planilha de sinistros precisa das colunas latitude e longitude.")
    c_ano = achar("ano")
    c_data = achar("data", "data_inversa", "data_sinistro", "data_acidente", "data_ocorrencia")
    if not (c_ano or c_data):
        raise ValueError("A planilha de sinistros precisa do ano (coluna ano) ou da data de cada sinistro.")
    c_id = achar("id", "id_sinistro", "segmento_id", "boletim", "codigo")
    c_grav = achar("gravidade", "classificacao", "classificacao_acidente", "severidade")
    c_obito = achar("com_obito", "mortos", "obitos", "vitimas_fatais", "fatais")
    c_vit = achar("com_vitima", "feridos", "vitimas", "feridos_graves")
    c_uf = achar("uf", "sigla_uf")

    data = pd.to_datetime(df[c_data], errors="coerce", dayfirst=True) if c_data else pd.Series(pd.NaT, index=df.index)
    ano = _numero(df[c_ano]) if c_ano else data.dt.year
    out = pd.DataFrame({
        "id": df[c_id].astype(str) if c_id else pd.Series(range(len(df)), index=df.index).astype(str),
        "data": data,
        "ano": ano.round().astype("Int64"),
        "uf": df[c_uf].astype("string").str.strip().str.upper() if c_uf else pd.Series(pd.NA, index=df.index,
                                                                                       dtype="string"),
        "br": pd.Series(pd.NA, index=df.index, dtype="string"),
        "km": np.nan,
        "latitude": _numero(df[c_lat]),
        "longitude": _numero(df[c_lon]),
        "sentido": pd.Series(pd.NA, index=df.index, dtype="string"),
    })
    fora = ~out["latitude"].between(-34.5, 6) | ~out["longitude"].between(-75, -32)
    out.loc[fora, ["latitude", "longitude"]] = np.nan
    if c_grav:
        txt = df[c_grav].astype("string").str.lower().fillna("")
        obito = txt.str.contains("fata|óbito|obito|morte")
        vitima = ~obito & txt.str.contains("ferid|vítima|vitima") & ~txt.str.contains("sem v")
    else:
        mortos = _numero(df[c_obito]).fillna(0) if c_obito else pd.Series(0, index=df.index)
        feridos = _numero(df[c_vit]).fillna(0) if c_vit else pd.Series(0, index=df.index)
        obito, vitima = mortos > 0, (mortos <= 0) & (feridos > 0)
    out["gravidade"] = np.select([obito, vitima], ["com_obito", "com_vitima"], "sem_vitima")
    out = out.reset_index(drop=True)
    out.attrs.update(linhas_repetidas=0, sem_coordenada=int(fora.sum()))
    return out


def ler_arquivos_sinistros(arquivos: list[tuple[str, bytes]]) -> pd.DataFrame:
    """Sinistros de vários arquivos: dados abertos da PRF (datatran, .csv ou .zip) ou planilhas com
    latitude e longitude (.csv ou .xlsx)."""
    from utils.entrada import ler_arquivo

    tabelas = []
    for nome, conteudo in arquivos:
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                partes = [(n, z.read(n)) for n in z.namelist() if n.lower().endswith((".csv", ".xlsx"))]
            if not partes:
                raise ValueError(f"O arquivo {nome} não tem .csv nem .xlsx dentro.")
        else:
            partes = [(nome, conteudo)]
        for n, c in partes:
            bruto = ler_arquivo(n, c)
            colunas = {str(x).strip().lower() for x in bruto.columns}
            if {"data_inversa", "br", "km"} <= colunas:
                tabelas.append(("prf", bruto.astype("string")))
            else:
                tabelas.append(("planilha", bruto))
    if not tabelas:
        raise ValueError("Nenhum arquivo de sinistros foi lido.")
    lidas = []
    prf = [t for k, t in tabelas if k == "prf"]
    if prf:
        lidas.append(ler_sinistros_prf(pd.concat(prf, ignore_index=True)))
    lidas += [ler_sinistros_pontuais(t) for k, t in tabelas if k == "planilha"]
    out = pd.concat(lidas, ignore_index=True) if len(lidas) > 1 else lidas[0]
    out.attrs.update(linhas_repetidas=sum(t.attrs.get("linhas_repetidas", 0) for t in lidas),
                     sem_coordenada=sum(t.attrs.get("sem_coordenada", 0) for t in lidas),
                     com_km=bool(prf))
    return out


def retangulo(sinistros: pd.DataFrame, snv: pd.DataFrame, ufs, margem: float = 0.02):
    """Retângulo (oeste, sul, leste, norte) da análise: a extensão dos sinistros, dentro das UFs (com
    folga de meio grau, porque o SNV não chega a todos os cantos da UF)."""
    base = _trechos_base(snv)
    base = base[base["sg_uf"].isin(set(ufs))]
    if base.empty:
        raise ValueError("Nenhum trecho do SNV nas UFs escolhidas.")
    uo, us, ul, un = shapely.total_bounds(base["geometry"].to_numpy()) + np.array([-0.5, -0.5, 0.5, 0.5])
    pts = sinistros.dropna(subset=["latitude", "longitude"])
    if "uf" in pts and pts["uf"].notna().any():      # bases nacionais: só os sinistros das UFs escolhidas
        pts = pts[pts["uf"].isin(set(ufs))]
    pts = pts[pts["longitude"].between(uo, ul) & pts["latitude"].between(us, un)]
    if pts.empty:
        return (uo - margem, us - margem, ul + margem, un + margem)
    return (max(uo, pts["longitude"].min()) - margem, max(us, pts["latitude"].min()) - margem,
            min(ul, pts["longitude"].max()) + margem, min(un, pts["latitude"].max()) + margem)


# ---------------------------------------------------------------------------------------------------
# 3. Localização no SNV
# ---------------------------------------------------------------------------------------------------
def localizar_sinistros(sinistros: pd.DataFrame, snv: pd.DataFrame, metodo: str = "auto",
                        tolerancia_m: float = TOLERANCIA_M) -> pd.DataFrame:
    """Acrescenta ``codigo_snv`` (trecho principal), ``frac_snv`` (posição de 0 a 1 no trecho),
    ``km_snv``, ``distancia_m`` (da coordenada ao trecho) e ``situacao``.

    ``metodo``:

    * ``"auto"`` (padrão): a coordenada é presa ao ponto mais próximo da mesma UF e BR, até
      ``tolerancia_m``; sem coordenada, ou longe da BR informada, vale o km.
    * ``"km"``: só UF, BR e km (posição proporcional à quilometragem do trecho).
    * ``"coordenada"``: ignora BR e km e usa o trecho com pista mais próximo (dados sem BR e km).
    """
    if metodo not in ("km", "auto", "coordenada"):
        raise ValueError("metodo deve ser 'km', 'auto' ou 'coordenada'.")
    s = sinistros.reset_index(drop=True).copy()
    n = len(s)
    codigo = np.full(n, None, dtype=object)
    frac = np.full(n, np.nan)
    dist = np.full(n, np.nan)
    situacao = np.full(n, "sem trecho no SNV para a BR e o km", dtype=object)

    lat = s["latitude"].to_numpy(float) if "latitude" in s else np.full(n, np.nan)
    lon = s["longitude"].to_numpy(float) if "longitude" in s else np.full(n, np.nan)
    tem_coord = ~np.isnan(lat) & ~np.isnan(lon)
    x, y = _PARA_METRICO.transform(np.nan_to_num(lon), np.nan_to_num(lat))
    pontos = shapely.points(x, y)
    pontos[~tem_coord] = None
    idx_snv = snv.set_index("vl_codigo")
    geom_princ = idx_snv["geom_m"]

    def prender(alvos, candidatos):
        """Prende os pontos ``alvos`` ao trecho mais próximo entre ``candidatos`` (até a tolerância)."""
        if not len(alvos) or candidatos.empty:
            return
        arvore = shapely.STRtree(candidatos["geom_m"].to_numpy())
        (i_pt, i_tr), d = arvore.query_nearest(pontos[alvos], max_distance=tolerancia_m, return_distance=True,
                                               all_matches=False)
        alvo = alvos[i_pt]
        princ = candidatos["codigo_principal"].to_numpy()[i_tr]
        codigo[alvo] = princ
        frac[alvo] = shapely.line_locate_point(geom_princ.loc[princ].to_numpy(), pontos[alvo], normalized=True)
        dist[alvo] = d
        situacao[alvo] = LOCALIZADO_COORD

    if metodo == "coordenada":
        situacao[:] = np.where(tem_coord, LONGE_DO_SNV, "sem coordenada")
        prender(np.flatnonzero(tem_coord), _trechos_base(snv))
        return _com_resultado(s, snv, codigo, frac, dist, situacao)

    pista = idx_snv.loc[snv["codigo_principal"], "com_pista"].to_numpy()
    grupos = {k: g for k, g in snv.assign(_pista=pista).groupby(["sg_uf", "vl_br"])}
    for (uf, br), idx in s.groupby(["uf", "br"], dropna=True).groups.items():
        cand = grupos.get((uf, br))
        if cand is None:
            continue
        idx = np.asarray(idx)
        if metodo == "auto":
            prender(idx[tem_coord[idx]], cand[cand["_pista"]])
            idx = idx[situacao[idx] != LOCALIZADO_COORD]
        if not len(idx):
            continue
        km = s.loc[idx, "km"].to_numpy(float)
        ini, fim = cand["km_ini"].to_numpy(), cand["km_fim"].to_numpy()
        ii, jj = np.nonzero((km[:, None] >= ini[None, :] - 1e-6) & (km[:, None] <= fim[None, :] + 1e-6))
        if not len(ii):
            continue
        d = shapely.distance(pontos[idx[ii]], cand["geom_m"].to_numpy()[jj])
        nao_eixo = (cand["sg_tipo_tr"].to_numpy()[jj] != "B").astype(int)
        no_fim = (km[ii] >= fim[jj] - 1e-6).astype(int)        # no limite, fica com o trecho seguinte
        ordem = np.lexsort((no_fim, nao_eixo, np.where(np.isnan(d), np.inf, d), ii))
        ii, jj = ii[ordem], jj[ordem]
        primeiro = np.r_[True, ii[1:] != ii[:-1]]
        ii, jj = ii[primeiro], jj[primeiro]
        sel = cand.iloc[jj]
        f = np.clip((km[ii] - sel["km_ini"].to_numpy()) / (sel["km_fim"] - sel["km_ini"]).to_numpy(), 0, 1)
        f = np.where(sel["invertido"].to_numpy(), 1 - f, f)
        alvo = idx[ii]
        princ = sel["codigo_principal"].to_numpy()
        codigo[alvo] = princ
        frac[alvo] = f
        dist[alvo] = shapely.distance(pontos[alvo], geom_princ.loc[princ].to_numpy())
        situacao[alvo] = np.where(sel["_pista"].to_numpy(), LOCALIZADO_KM, SEM_PISTA)
    return _com_resultado(s, snv, codigo, frac, dist, situacao)


def _com_resultado(s, snv, codigo, frac, dist, situacao):
    idx = snv.set_index("vl_codigo")
    ok = np.array([c is not None for c in codigo])
    km = np.full(len(s), np.nan)
    if ok.any():
        p = idx.loc[codigo[ok]]
        km[ok] = p["km_ini"].to_numpy() + frac[ok] * (p["km_fim"] - p["km_ini"]).to_numpy()
    s["codigo_snv"] = pd.array(codigo, dtype="string")
    s["frac_snv"] = frac
    s["km_snv"] = km
    s["distancia_m"] = dist
    s["situacao"] = pd.array(situacao, dtype="string")
    return s


# ---------------------------------------------------------------------------------------------------
# 4. Segmentos
# ---------------------------------------------------------------------------------------------------
def cortes_do_trecho(extensao: float, comprimento: float = COMPRIMENTO_PADRAO, fundir_resto: bool = True,
                     fracao_minima: float = 0.5) -> list[float]:
    """Distâncias (a partir do início do trecho) onde o trecho é cortado.

    Sobra menor que ``fracao_minima × comprimento`` é somada ao último segmento quando ``fundir_resto``.
    """
    n = int(np.floor(extensao / comprimento + 1e-9))
    if n == 0:
        return [0.0, float(extensao)]
    cortes = [k * comprimento for k in range(n + 1)]
    resto = extensao - n * comprimento
    if resto > 1e-9 * max(1.0, comprimento):
        if fundir_resto and resto < fracao_minima * comprimento:
            cortes[-1] = float(extensao)
        else:
            cortes.append(float(extensao))
    return cortes


def _km_br(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def cortar_segmentos(snv: pd.DataFrame, comprimento: float = COMPRIMENTO_PADRAO, referencia: str = "km",
                     fundir_resto: bool = True, fracao_minima: float = 0.5, codigos=None, ufs=None) -> pd.DataFrame:
    """Segmentos de ``comprimento`` km dentro de cada trecho principal com pista.

    ``referencia="km"`` (padrão) corta na quilometragem do SNV, de modo que os limites caem nos marcos
    quilométricos (km 25 a 26); ``"geometria"`` mede o comprimento na linha do SNV, como a segmentação
    oficial de DF, MG e PE. A extensão do segmento segue a referência escolhida.
    """
    lo, hi = LIMITES_COMPRIMENTO
    if not lo <= comprimento <= hi:
        raise ValueError(f"O comprimento do segmento deve ficar entre {lo:g} e {hi:g} km.")
    if referencia not in ("geometria", "km"):
        raise ValueError("referencia deve ser 'geometria' ou 'km'.")
    base = _trechos_base(snv)
    if codigos is not None:
        base = base[base["vl_codigo"].isin(set(codigos))]
    if ufs is not None:
        base = base[base["sg_uf"].isin(set(ufs))]
    linhas = []
    for r in base.itertuples(index=False):
        ext = r.comprimento_m / 1000 if referencia == "geometria" else r.km_fim - r.km_ini
        if ext <= 0:
            continue
        cortes = cortes_do_trecho(ext, comprimento, fundir_resto, fracao_minima)
        for k, (a, b) in enumerate(zip(cortes[:-1], cortes[1:]), start=1):
            linhas.append((r.vl_codigo, k, r.vl_br, r.sg_uf, r.km_ini, r.km_fim, a / ext, b / ext, b - a, r.geom_m))
    seg = pd.DataFrame(linhas, columns=["codigo_snv", "ordem", "br", "uf", "_ki", "_kf", "frac_inicial",
                                        "frac_final", "extensao_trecho", "geom_m"])
    if seg.empty:
        raise ValueError("Nenhum trecho do SNV com pista para segmentar.")
    largura = max(3, len(str(seg["ordem"].max())))
    seg["segmento_id"] = seg["codigo_snv"] + "-" + seg["ordem"].astype(str).str.zfill(largura)
    seg["km_inicial"] = (seg["_ki"] + seg["frac_inicial"] * (seg["_kf"] - seg["_ki"])).round(3)
    seg["km_final"] = (seg["_ki"] + seg["frac_final"] * (seg["_kf"] - seg["_ki"])).round(3)
    seg["extensao_trecho"] = seg["extensao_trecho"].round(4)
    geom_m = np.array([substring(g, fa, fb, normalized=True)
                       for g, fa, fb in zip(seg["geom_m"], seg["frac_inicial"], seg["frac_final"])], dtype=object)
    meio = shapely.line_interpolate_point(geom_m, 0.5, normalized=True)
    lon, lat = _PARA_GEO.transform(shapely.get_x(meio), shapely.get_y(meio))
    seg["latitude"], seg["longitude"] = lat, lon
    seg["geometry"] = _transformar(geom_m, _PARA_GEO)
    seg["rodovia"] = ("BR-" + seg["br"] + "/" + seg["uf"] + ", km " + seg["km_inicial"].map(_km_br) + " a "
                      + seg["km_final"].map(_km_br))
    return seg.drop(columns=["_ki", "_kf", "geom_m"])


# ---------------------------------------------------------------------------------------------------
# 5. Agregação
# ---------------------------------------------------------------------------------------------------
def agregar_por_segmento(localizados: pd.DataFrame, segmentos: pd.DataFrame, por_sentido: bool = False,
                         anos=None) -> pd.DataFrame:
    """Sinistros por segmento no formato interno das trilhas (uma linha por segmento, ou por segmento e
    sentido). O resumo da localização fica em ``attrs['resumo']``."""
    loc = localizados
    if anos is not None:
        loc = loc[loc["ano"].isin(list(anos))]
    ok = loc[loc["situacao"].isin(SITUACOES_LOCALIZADAS) & loc["codigo_snv"].isin(set(segmentos["codigo_snv"]))]
    n_anos = len(set(anos)) if anos is not None else int(ok["ano"].nunique()) or np.nan

    seg = (segmentos[["codigo_snv", "frac_inicial", "segmento_id"]].astype({"codigo_snv": str})
           .sort_values("frac_inicial"))
    esq = ok.dropna(subset=["frac_snv"]).astype({"codigo_snv": str}).sort_values("frac_snv")
    atrib = pd.merge_asof(esq, seg, left_on="frac_snv", right_on="frac_inicial", by="codigo_snv",
                          direction="backward").dropna(subset=["segmento_id"])
    chaves = ["segmento_id"]
    extras_vmd = [c for c in ("vmd_c", "vmd_d", "vmd_origem", "vmd_classificacao") if c in segmentos]
    base = segmentos[["segmento_id", "latitude", "longitude", "extensao_trecho", "rodovia", "codigo_snv",
                      "km_inicial", "km_final", *extras_vmd]].copy()
    sem_sentido = 0
    if por_sentido:
        sem_sentido = int(atrib["sentido"].isna().sum())
        atrib = atrib.dropna(subset=["sentido"])
        chaves.append("sentido")
        base = base.merge(pd.DataFrame({"sentido": ["Crescente", "Decrescente"]}), how="cross")
    if atrib.empty:
        contagem = pd.DataFrame(columns=chaves + GRAVIDADES)
    else:
        contagem = (atrib.groupby(chaves + ["gravidade"]).size().unstack("gravidade", fill_value=0)
                    .reindex(columns=GRAVIDADES, fill_value=0).reset_index())
    out = base.merge(contagem, on=chaves, how="left")
    out[GRAVIDADES] = out[GRAVIDADES].fillna(0).astype(int)
    if por_sentido:
        out["segmento_id"] = out["segmento_id"] + "-" + out["sentido"].str[0]
    if extras_vmd:   # soma dos dois sentidos; por sentido, o VMD do próprio sentido
        out["volume_trafego"] = (np.where(out["sentido"] == "Crescente", out["vmd_c"], out["vmd_d"]) if por_sentido
                                 else out[["vmd_c", "vmd_d"]].sum(axis=1, min_count=2))
    else:
        out["volume_trafego"] = np.nan
    out["n_anos"] = n_anos
    colunas = ["segmento_id", "latitude", "longitude", "extensao_trecho", "volume_trafego", "n_anos",
               *GRAVIDADES, "rodovia"] + (["sentido"] if por_sentido else []) + ["codigo_snv", "km_inicial",
                                                                                   "km_final"]
    colunas += [c for c in ("vmd_origem", "vmd_classificacao") if c in extras_vmd]
    out = out[colunas].reset_index(drop=True)
    out.attrs["resumo"] = {
        "sinistros": int(len(loc)),
        "atribuidos": int(len(atrib)),
        "sem_sentido": sem_sentido,
        "situacoes": loc["situacao"].value_counts().to_dict(),
        "segmentos": int(len(segmentos)),
        "anos": sorted(int(a) for a in ok["ano"].dropna().unique()),
    }
    return out


# ---------------------------------------------------------------------------------------------------
# 6. Tudo junto
# ---------------------------------------------------------------------------------------------------
def segmentar(sinistros: pd.DataFrame, snv: pd.DataFrame, ufs, anos=None, comprimento: float = COMPRIMENTO_PADRAO,
              por_sentido: bool = False, referencia: str = "km", metodo: str | None = None, vmd=None,
              vias_osm=None) -> pd.DataFrame:
    """Segmenta a malha das ``ufs`` e conta os sinistros do período.

    ``sinistros``: saída de ``ler_arquivos_sinistros``. Com BR e km (PRF), cada sinistro vai para a BR
    informada; só com coordenada, para a rodovia do SNV mais próxima (até 100 m) e, com ``vias_osm``
    (saída de ``osm.ler_vias_osm``), para as demais vias. ``vmd``: tabela de ``trafego.ler_vmd_pnct``.
    """
    ufs = sorted(set(ufs))
    if not ufs:
        raise ValueError("Escolha ao menos uma UF.")
    # sem coluna de UF (planilhas de outras fontes), valem todos os sinistros enviados
    s = sinistros[sinistros["uf"].isin(ufs)] if sinistros["uf"].notna().any() else sinistros
    if anos is not None:
        s = s[s["ano"].isin(list(anos))]
    if s.empty:
        raise ValueError("Nenhum sinistro nas UFs e anos escolhidos.")
    com_km = s["km"].notna().any() and s["br"].notna().any()
    metodo = metodo or ("auto" if com_km else "coordenada")
    tolerancia = TOLERANCIA_M if metodo != "coordenada" else TOLERANCIA_COORD_M
    seg = cortar_segmentos(snv, comprimento, referencia=referencia, ufs=ufs)
    if vmd is not None:
        from utils.trafego import atribuir_vmd

        seg = atribuir_vmd(seg, vmd)
    loc = localizar_sinistros(s, snv, metodo=metodo, tolerancia_m=tolerancia)
    # sem UF nos dados, a rodovia mais próxima pode ser de outra UF: o sinistro fica de fora
    uf_trecho = loc["codigo_snv"].map(snv.drop_duplicates("vl_codigo").set_index("vl_codigo")["sg_uf"])
    outra_uf = loc["situacao"].isin(SITUACOES_LOCALIZADAS) & uf_trecho.notna() & ~uf_trecho.isin(ufs)
    loc.loc[outra_uf, "situacao"] = EM_OUTRA_UF
    dados = agregar_por_segmento(loc, seg, por_sentido=por_sentido, anos=anos)
    resumo = dados.attrs["resumo"]
    dados["fonte"] = "SNV"
    if vias_osm is not None:
        from utils import osm

        vias = osm.montar_vias(vias_osm, snv)
        seg_osm = osm.cortar_vias(vias, comprimento)
        resto = loc[~loc["situacao"].isin(SITUACOES_LOCALIZADAS)]
        n_anos = dados["n_anos"].iloc[0] if len(dados) else (len(set(anos)) if anos is not None else np.nan)
        dados_osm, atribuidos = osm.agregar_osm(resto, seg_osm, n_anos)
        loc.loc[atribuidos, "situacao"] = LOCALIZADO_OSM
        dados = pd.concat([dados, dados_osm], ignore_index=True)
        resumo["atribuidos"] += len(atribuidos)
        resumo["situacoes"] = loc["situacao"].value_counts().to_dict()
        resumo["osm"] = {"vias": len(vias), "segmentos": len(seg_osm), "sinistros": len(atribuidos),
                         "km": round(float(vias["comprimento_m"].sum()) / 1000) if len(vias) else 0}
    dados.attrs["resumo"] = resumo
    resumo.update(versao_snv=str(snv["versao_snv"].dropna().iloc[0]) if snv["versao_snv"].notna().any()
                  else "não informada", comprimento=comprimento, ufs=ufs, com_km=bool(com_km))
    if vmd is not None:
        com_vmd = dados["volume_trafego"].notna()
        resumo["vmd"] = {
            "ano": vmd.attrs.get("ano"), "versao_snv": vmd.attrs.get("versao_snv"),
            "cobertura": float(com_vmd[dados["fonte"] == "SNV"].mean()) if len(dados) else 0.0,
            "pelo_km": int((dados.get("vmd_origem") == "mesma BR e km").sum()),
            "nao_simulavel": int(dados["vmd_classificacao"].fillna("").str.lower().str.startswith("não sim").sum()),
        }
    return dados
