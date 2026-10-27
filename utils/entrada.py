"""Leitura de planilhas (CSV ou Excel) e adaptação para o formato interno das trilhas.

Formatos aceitos:

* Modelo do próprio app (uma linha por segmento ou por segmento-ano):
  ``segmento_id, sem_vitima, com_vitima, com_obito, latitude, longitude,
  volume_trafego, extensao_trecho, ano``.
* Planilhas oficiais (DF, MG, PE): ``ID``, ``CodigoSNV``, ``Comprimento``,
  ``Latitude Média``, ``Longitude Média``, ``Sentido``, ``VMD AAAA`` e
  ``Sinistros_SV/CV/CO AAAA``.

O formato de saída tem uma linha por segmento:
``segmento_id, latitude, longitude, extensao_trecho, volume_trafego, n_anos,
sem_vitima, com_vitima, com_obito`` (+ ``rodovia`` e ``sentido`` quando houver).
"""
from __future__ import annotations

import io
import re
import unicodedata

import numpy as np
import pandas as pd

from utils.constantes import COLUNAS_SINISTROS

COLUNAS_MODELO = ["segmento_id", "sem_vitima", "com_vitima", "com_obito", "latitude",
                  "longitude", "volume_trafego", "extensao_trecho", "ano"]

ANOS_PADRAO = 3  # período mínimo recomendado pelo Manual (item 2.1)


class ErroEntrada(ValueError):
    """Erro de entrada com mensagem pronta para o usuário."""


def normalizar_nome(nome) -> str:
    """'Latitude Média' -> 'latitude_media'; 'Sinistros_SV 2021' -> 'sinistros_sv_2021'."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s.strip().lower())
    return s.strip("_")


_ANO = r"(?:_?((?:19|20)\d{2}))?"
_PREFIXO = r"(?:sinistros?_|acidentes?_|qtd_|n_)?"
PADROES = {
    "sem_vitima": re.compile(rf"^{_PREFIXO}(?:sv|sem_vitimas?|danos_materiais){_ANO}$"),
    "com_vitima": re.compile(rf"^{_PREFIXO}(?:cv|com_vitimas?|com_feridos?|com_vitimas_feridas){_ANO}$"),
    "com_obito": re.compile(rf"^{_PREFIXO}(?:co|com_obitos?|com_vitimas_fatais|fatais){_ANO}$"),
    "volume": re.compile(rf"^(?:vmd|vmda|volume|volume_trafego|volume_de_trafego){_ANO}$"),
}


def para_numero(serie: pd.Series) -> pd.Series:
    """Converte texto em número aceitando o padrão brasileiro (1.234,5)."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    s = serie.astype("string").str.strip()
    s = s.mask(s.isin(["", "nan", "NaN", "None", "-"]))
    validos = s.dropna()
    if len(validos) and validos.str.contains(",", regex=False).any():
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    elif len(validos) and validos.str.fullmatch(r"-?\d{1,3}(?:\.\d{3})+").all():
        s = s.str.replace(".", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def ler_arquivo(nome: str, conteudo: bytes) -> pd.DataFrame:
    """Lê CSV (separador ',', ';' ou tabulação; UTF-8 ou Latin-1) ou Excel (.xlsx)."""
    ext = nome.lower().rsplit(".", 1)[-1] if "." in nome else ""
    if ext in ("xlsx", "xlsm"):
        return pd.read_excel(io.BytesIO(conteudo))
    if ext in ("csv", "txt"):
        texto = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = conteudo.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not texto or not texto.strip():
            raise ErroEntrada("O arquivo está vazio.")
        cabecalho = texto.splitlines()[0]
        contagem = {sep: cabecalho.count(sep) for sep in (";", ",", "\t")}
        sep = max(contagem, key=contagem.get)
        return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str)
    raise ErroEntrada(f"Formato '.{ext}' não suportado. Use .csv ou .xlsx.")


def _achar(df: pd.DataFrame, *candidatos: str):
    normal = {}
    for c in df.columns:
        normal.setdefault(normalizar_nome(c), c)
    for cand in candidatos:
        if cand in normal:
            return normal[cand]
    return None


def _colunas_por_padrao(df: pd.DataFrame, padrao: re.Pattern):
    encontradas = []
    for c in df.columns:
        m = padrao.match(normalizar_nome(c))
        if m:
            encontradas.append((c, m.group(1)))
    return encontradas


def adaptar_planilha(df_bruto: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Converte a planilha para o formato interno. Retorna (dados, avisos)."""
    avisos: list[str] = []
    df = df_bruto.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").reset_index(drop=True)
    if df.empty:
        raise ErroEntrada("A planilha não tem linhas com dados.")

    out = pd.DataFrame(index=df.index)

    # 1. Sinistros por gravidade (soma das colunas anuais, se houver)
    anos_detectados: set[str] = set()
    faltando = []
    for alvo in COLUNAS_SINISTROS:
        cols = _colunas_por_padrao(df, PADROES[alvo])
        if cols:
            out[alvo] = df[[c for c, _ in cols]].apply(para_numero).sum(axis=1, min_count=1)
            anos_detectados.update(a for _, a in cols if a)
        else:
            out[alvo] = np.nan
            faltando.append(alvo)
    if len(faltando) == len(COLUNAS_SINISTROS):
        raise ErroEntrada(
            "Não encontrei colunas de sinistros. Use 'sem_vitima', 'com_vitima' e 'com_obito' "
            "(modelo do app) ou 'Sinistros_SV/CV/CO AAAA' (planilhas oficiais).")
    if faltando:
        avisos.append("Colunas não encontradas e consideradas zero: " + ", ".join(faltando) + ".")

    # 2. Identificador
    col_id = _achar(df, "segmento_id", "id_segmento", "segmento", "id", "codigosnv", "codigo_snv", "snv")
    if col_id is None:
        ids = pd.Series(np.arange(1, len(df) + 1), index=df.index).astype("string")
        avisos.append("Sem coluna de identificação: os segmentos foram numerados pela ordem das linhas.")
    else:
        ids = df[col_id].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    out["segmento_id"] = ids

    # 3. Coordenadas, extensão, período, volume
    col_lat = _achar(df, "latitude", "latitude_media", "lat", "lat_media")
    col_lon = _achar(df, "longitude", "longitude_media", "lon", "long", "lng", "lon_media", "long_media")
    out["latitude"] = para_numero(df[col_lat]) if col_lat else np.nan
    out["longitude"] = para_numero(df[col_lon]) if col_lon else np.nan
    fora = ~out["latitude"].between(-90, 90) & out["latitude"].notna() | \
        ~out["longitude"].between(-180, 180) & out["longitude"].notna()
    if fora.any():
        out.loc[fora, ["latitude", "longitude"]] = np.nan
        avisos.append(f"{int(fora.sum())} linha(s) com coordenadas impossíveis foram tratadas como sem coordenada.")
    fora_br = (~out["latitude"].between(-34.5, 6) | ~out["longitude"].between(-75, -32)) & out["latitude"].notna()
    if fora_br.any():
        avisos.append(f"{int(fora_br.sum())} linha(s) com coordenadas fora do Brasil (confira se latitude e "
                      "longitude não estão invertidas).")

    col_ext = _achar(df, "extensao_trecho", "extensao", "extensao_km", "comprimento", "comprimento_km")
    if col_ext:
        out["extensao_trecho"] = para_numero(df[col_ext])
    else:
        out["extensao_trecho"] = 1.0
        avisos.append("Sem coluna de extensão: todos os segmentos foram considerados com 1 km.")

    col_ano = _achar(df, "ano")
    out["ano"] = para_numero(df[col_ano]) if col_ano else np.nan

    vol_ano = [(c, a) for c, a in _colunas_por_padrao(df, PADROES["volume"]) if a]
    vol_sem = [c for c, a in _colunas_por_padrao(df, PADROES["volume"]) if not a]
    if vol_ano:
        out["volume_trafego"] = df[[c for c, _ in vol_ano]].apply(para_numero).mean(axis=1)
    elif vol_sem:
        out["volume_trafego"] = para_numero(df[vol_sem[0]])
    else:
        out["volume_trafego"] = np.nan

    col_snv = _achar(df, "codigosnv", "codigo_snv", "snv", "rodovia", "br")
    if col_snv and col_snv != col_id:
        out["rodovia"] = df[col_snv].astype("string").str.strip()
    col_sentido = _achar(df, "sentido")
    if col_sentido:
        out["sentido"] = df[col_sentido].astype("string").str.strip()

    # 4. Linhas inválidas: sem ID, linhas de total, sem nenhum sinistro informado
    sem_id = out["segmento_id"].isna() | (out["segmento_id"] == "")
    total = out["segmento_id"].fillna("").str.lower().str.match(r"^(total|soma|subtotal)\b")
    sem_dados = out[COLUNAS_SINISTROS].isna().all(axis=1)
    descartar = sem_id | total | sem_dados
    if descartar.any():
        avisos.append(f"{int(descartar.sum())} linha(s) descartada(s): sem ID, linha de total ou sem sinistros "
                      "informados.")
        out = out[~descartar]
    if out.empty:
        raise ErroEntrada("Nenhuma linha válida depois da validação.")
    parciais = out[COLUNAS_SINISTROS].isna().any(axis=1)
    if parciais.any():
        avisos.append(f"{int(parciais.sum())} linha(s) com algum tipo de sinistro em branco: considerado zero.")
    out[COLUNAS_SINISTROS] = out[COLUNAS_SINISTROS].fillna(0)
    if (out[COLUNAS_SINISTROS] < 0).any().any():
        raise ErroEntrada("Há quantidades de sinistros negativas na planilha.")

    ext_invalida = out["extensao_trecho"].isna() | (out["extensao_trecho"] <= 0)
    if ext_invalida.any():
        out.loc[ext_invalida, "extensao_trecho"] = np.nan
        avisos.append(f"{int(ext_invalida.sum())} linha(s) sem extensão válida (> 0): ficam fora das Trilhas 1 e 3, "
                      "mas entram na Trilha 2 (KDE).")

    # 5. Uma linha por segmento. Nas planilhas oficiais o mesmo ID nos dois sentidos são dois segmentos, também
    #    quando cada segmento ocupa várias linhas (um sinistro ou um ano por linha)
    if ("sentido" in out and out["segmento_id"].duplicated().any()
            and out.groupby("segmento_id")["sentido"].nunique().gt(1).any()):
        out["segmento_id"] = out["segmento_id"] + "-" + out["sentido"].fillna("?").str[0].str.upper()
        avisos.append("O ID se repete entre os sentidos da via: cada sentido virou um segmento "
                      "(ex.: '25-C' e '25-D').")
    formato_longo = col_ano is not None and out["segmento_id"].duplicated().any()
    if not formato_longo and out["segmento_id"].duplicated().any():
        n_rep = int(out["segmento_id"].duplicated(keep=False).sum())
        avisos.append(f"{n_rep} linha(s) com ID repetido foram somadas como um mesmo segmento.")
        formato_longo = True

    if formato_longo:
        agg = {c: "sum" for c in COLUNAS_SINISTROS}
        agg.update({"latitude": "first", "longitude": "first", "extensao_trecho": "first",
                    "volume_trafego": "mean"})
        for c in ("rodovia", "sentido"):
            if c in out:
                agg[c] = "first"
        n_anos = out.groupby("segmento_id", sort=False)["ano"].nunique()
        out = out.groupby("segmento_id", sort=False).agg(agg)
        out["n_anos"] = n_anos.reindex(out.index).replace(0, np.nan)
        out = out.reset_index()
    else:
        out["n_anos"] = np.nan
        if col_ano:
            out.loc[out["ano"].notna(), "n_anos"] = 1

    if out["n_anos"].isna().any():
        n_padrao = len(anos_detectados) or len(vol_ano) or ANOS_PADRAO
        if not (anos_detectados or vol_ano):
            avisos.append(f"Período dos dados não identificado: considerado {ANOS_PADRAO} anos (mínimo do Manual).")
        out["n_anos"] = out["n_anos"].fillna(n_padrao)

    if out.empty:
        raise ErroEntrada("Nenhuma linha válida depois da validação.")
    colunas = ["segmento_id", "latitude", "longitude", "extensao_trecho", "volume_trafego", "n_anos",
               *COLUNAS_SINISTROS] + [c for c in ("rodovia", "sentido") if c in out]
    out = out[colunas].reset_index(drop=True)
    out["segmento_id"] = out["segmento_id"].astype(str)
    return out, avisos


# Compatibilidade com a v4
def adaptar_planilha_oficial(df: pd.DataFrame) -> pd.DataFrame:
    return adaptar_planilha(df)[0]
