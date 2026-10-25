"""Volume de tráfego (VMD) por segmento, a partir da modelagem do PNCT (DNIT) por trecho do SNV.

A planilha do PNCT (ex.: ``VDM_Modelagem_2019_SNV_202001A``) traz o VMDa estimado por trecho e sentido
(``VMDa_C`` e ``VMDa_D``), numa versão do SNV que pode ser anterior à usada na segmentação. Cada segmento
recebe o VMD:

1. do trecho com o mesmo código, levando a posição do segmento pela fração do trecho (o km do trecho
   pode ter mudado entre as versões); nos trechos que o PNCT dividiu em partes, vale a parte que contém
   o segmento;
2. se o código não existir na planilha e o segmento for do eixo principal da BR (tipo B), do trecho
   principal da mesma UF e BR que contém o km do meio do segmento. Acessos, contornos, travessias,
   variantes e anéis têm quilometragem própria, que não coincide com a da BR: sem o código, ficam sem VMD.

O VMD do segmento é a soma dos dois sentidos; com a análise por sentido, cada sentido usa o seu. A
coluna ``classificacao`` repete o aviso do PNCT ("Não Simulável" perto de áreas urbanas: uso restrito).
"""
from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd

ORIGEM_CODIGO = "mesmo trecho do SNV"
ORIGEM_KM = "mesma BR e km"
SEM_VMD = "sem VMD"


def _num(df: pd.DataFrame, coluna: str) -> pd.Series:
    if coluna not in df:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[coluna].astype("string").str.replace(",", ".", regex=False),
                         errors="coerce").astype("float64")


def ler_vmd_pnct(fonte, nome: str = "") -> pd.DataFrame:
    """Lê a planilha de VMDa modelado do PNCT (caminho ou bytes). ``nome`` (do arquivo) dá o ano."""
    xl = pd.ExcelFile(io.BytesIO(fonte) if isinstance(fonte, bytes) else fonte)
    abas = [a for a in xl.sheet_names if "metadad" not in a.lower()]
    aba = next((a for a in abas if a.upper().startswith("SNV")), abas[0] if abas else xl.sheet_names[0])
    topo = pd.read_excel(xl, aba, header=None, nrows=15)
    linhas = [i for i in range(len(topo)) if topo.iloc[i].astype(str).str.strip().eq("vl_codigo").any()]
    if not linhas:
        raise ValueError("A planilha de VMD precisa da coluna vl_codigo (código do trecho do SNV).")
    v = pd.read_excel(xl, aba, header=linhas[0])
    v.columns = [str(c).strip() for c in v.columns]
    falta = [c for c in ("vl_codigo", "vl_br", "sg_uf", "vl_km_inic", "vl_km_fina", "VMDa_C", "VMDa_D") if c not in v]
    if falta:
        raise ValueError("A planilha de VMD não tem as colunas: " + ", ".join(falta) + ".")
    km_ini_trecho, km_fim_trecho = _num(v, "vl_km_inic"), _num(v, "vl_km_fina")
    col_cls = next((c for c in v.columns if c.lower().startswith("classifica")), None)
    out = pd.DataFrame({
        "codigo": v["vl_codigo"].astype(str).str.strip(),
        "br": _num(v, "vl_br").round().astype("Int64").astype("string").str.zfill(3),
        "uf": v["sg_uf"].astype(str).str.strip().str.upper(),
        "principal": (v["desc_coinc"].fillna("-").astype(str).str.strip().eq("-") if "desc_coinc" in v
                      else True),
        "tipo": (v["sg_tipo_tr"].astype(str).str.strip().str.upper() if "sg_tipo_tr" in v
                 else v["vl_codigo"].astype(str).str.strip().str[3]),
        "km_ini_trecho": km_ini_trecho,
        "km_fim_trecho": km_fim_trecho,
        "km_ini": _num(v, "vl_km_i_estim").fillna(km_ini_trecho),
        "km_fim": _num(v, "vl_km_f_estim").fillna(km_fim_trecho),
        "vmd_c": _num(v, "VMDa_C").round(),          # veículos por dia (a modelagem traz decimais)
        "vmd_d": _num(v, "VMDa_D").round(),
        "classificacao": (v[col_cls].astype("string").str.strip().replace({"": "-"}).fillna("-") if col_cls
                          else "-"),
    })
    out = out[(out["vmd_c"].notna() | out["vmd_d"].notna()) & out["km_ini"].notna()].reset_index(drop=True)
    versao = None
    if "versao_snv" in v and v["versao_snv"].notna().any():
        versao = str(v["versao_snv"].dropna().iloc[0]).strip()
    elif m := re.search(r"(\d{6}[A-Z])", aba):
        versao = m.group(1)
    ano = re.search(r"(?<!\d)(20\d{2})(?!\d)", nome)
    out.attrs.update(versao_snv=versao or "não informada", ano=int(ano.group(1)) if ano else None)
    return out


def atribuir_vmd(segmentos: pd.DataFrame, vmd: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta ``vmd_c``, ``vmd_d``, ``vmd_origem`` e ``vmd_classificacao`` aos segmentos (saída de
    ``segmentacao.cortar_segmentos``)."""
    seg = segmentos.reset_index(drop=True).copy()
    seg["_i"] = np.arange(len(seg))
    seg["_frac"] = (seg["frac_inicial"] + seg["frac_final"]) / 2
    seg["_km"] = (seg["km_inicial"] + seg["km_final"]) / 2
    partes = vmd.sort_values("km_ini")
    colunas = ["vmd_c", "vmd_d", "classificacao"]

    # 1. Mesmo código: posição pela fração do trecho na versão do PNCT
    trecho = vmd.groupby("codigo")[["km_ini_trecho", "km_fim_trecho"]].first()
    a = seg.merge(trecho, left_on="codigo_snv", right_index=True)
    a["_km_pnct"] = a["km_ini_trecho"] + a["_frac"] * (a["km_fim_trecho"] - a["km_ini_trecho"])
    a = pd.merge_asof(a.sort_values("_km_pnct"), partes[["codigo", "km_ini", *colunas]],
                      left_on="_km_pnct", right_on="km_ini", left_by="codigo_snv", right_by="codigo",
                      direction="backward")
    a = a[a["km_ini"].notna()]
    a["vmd_origem"] = ORIGEM_CODIGO

    # 2. Eixo principal (tipo B, 4º caractere do código): mesma UF e BR, pelo km do meio do segmento
    resto = seg[~seg["_i"].isin(a["_i"]) & seg["codigo_snv"].astype(str).str[3].eq("B")]
    princ = partes[partes["principal"] & partes["tipo"].eq("B")].astype({"br": str, "uf": str})
    b = pd.merge_asof(resto.astype({"br": str, "uf": str}).sort_values("_km"),
                      princ[["uf", "br", "km_ini", "km_fim", *colunas]],
                      left_on="_km", right_on="km_ini", by=["uf", "br"], direction="backward")
    b = b[b["km_fim"].notna() & (b["_km"] <= b["km_fim"] + 1e-6)]
    b["vmd_origem"] = ORIGEM_KM

    achados = pd.concat([a[["_i", *colunas, "vmd_origem"]], b[["_i", *colunas, "vmd_origem"]]])
    out = seg.merge(achados, on="_i", how="left").sort_values("_i")
    out["vmd_origem"] = out["vmd_origem"].fillna(SEM_VMD)
    out = out.rename(columns={"classificacao": "vmd_classificacao"})
    return out.drop(columns=["_i", "_frac", "_km"]).reset_index(drop=True)
