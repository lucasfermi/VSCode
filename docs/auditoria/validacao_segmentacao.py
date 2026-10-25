"""Validação da segmentação automática contra a segmentação oficial (DF, MG e PE, 2021 a 2023).

Uso, a partir da pasta do projeto:

    python docs/auditoria/validacao_segmentacao.py SNV.shp planilha_oficial.xlsx datatran2021.csv ...

``SNV.shp`` é o shapefile da publicação do SNV do DNIT; a planilha oficial tem as colunas ``ID``,
``CodigoSNV``, ``Sentido``, ``Latitude Média``, ``Longitude Média`` e ``Sinistros_SV/CV/CO AAAA``; os
arquivos ``datatran`` são os dados abertos da PRF por ocorrência. Para os trechos da planilha oficial, o
script corta segmentos de 1 km sem fundir sobras (como a planilha oficial) e compara, segmento a
segmento e por sentido, o número de sinistros de cada gravidade e a posição do segmento.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from models.trilha1_valor_critico import aplicar_valor_critico  # noqa: E402
from utils import segmentacao as sg  # noqa: E402
from utils.preprocessamento import preparar_dados  # noqa: E402

ANOS = (2021, 2022, 2023)
GRAV = ["sem_vitima", "com_vitima", "com_obito"]


def oficial(caminho):
    of = pd.read_excel(caminho)
    for alvo, sigla in zip(GRAV, ("SV", "CV", "CO")):
        of[alvo] = of[[f"Sinistros_{sigla} {a}" for a in ANOS]].sum(axis=1)
    of = of.sort_values(["CodigoSNV", "Sentido", "ID"])
    of["ordem"] = of.groupby(["CodigoSNV", "Sentido"]).cumcount() + 1
    of["chave"] = of["CodigoSNV"] + "-" + of["ordem"].astype(str).str.zfill(3) + "-" + of["Sentido"].str[0]
    return of


def distancia_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * np.arcsin(np.sqrt(a))


def criticos(df):
    proc = preparar_dados(df.assign(n_anos=len(ANOS)), 1, 4, 28)
    res = aplicar_valor_critico(proc, metodo="severidade")
    return set(res.loc[res["Critico"].astype(bool), "segmento_id"])


def main(shp, planilha, *csvs):
    snv = sg.preparar_snv(sg.carregar_snv(shp))
    of = oficial(planilha)
    codigos = sorted(of["CodigoSNV"].unique())
    bruto = pd.concat([pd.read_csv(c, sep=";", encoding="latin-1", dtype=str) for c in csvs], ignore_index=True)
    prf = sg.ler_sinistros_prf(bruto)
    prf = prf[prf["uf"].isin(["DF", "MG", "PE"]) & prf["ano"].isin(ANOS)]
    n_of = of.groupby(["CodigoSNV", "Sentido"]).size().groupby(level=0).max()
    print(f"Trechos SNV na planilha oficial: {len(codigos)}; sinistros da PRF em DF, MG e PE: {len(prf)}")
    locs = {m: sg.localizar_sinistros(prf, snv, metodo=m) for m in ("auto", "coordenada", "km")}
    b = criticos(of.assign(segmento_id=of["chave"], extensao_trecho=of["Comprimento"])
                 [["segmento_id", "extensao_trecho", *GRAV]])

    for referencia in ("geometria", "km"):
        seg = sg.cortar_segmentos(snv, 1.0, referencia=referencia, fundir_resto=False, codigos=codigos)
        n_aut = seg.groupby("codigo_snv").size()
        iguais = int((n_of == n_aut.reindex(n_of.index)).sum())
        pos = of.merge(seg, left_on=of["CodigoSNV"] + "-" + of["ordem"].astype(str).str.zfill(3),
                       right_on="segmento_id", suffixes=("", "_aut"))
        d = distancia_m(pos["Latitude Média"], pos["Longitude Média"], pos["latitude"], pos["longitude"])
        print(f"\nCorte pela {referencia}: {n_aut.index.isin(codigos).sum()} trechos na versão "
              f"{snv['versao_snv'].iloc[0]}, {iguais} com o mesmo número de segmentos da planilha oficial; "
              f"distância ao ponto oficial: mediana {np.median(d):.0f} m, 90% até {np.quantile(d, 0.9):.0f} m")
        for metodo, loc in locs.items():
            aut = sg.agregar_por_segmento(loc, seg, por_sentido=True)
            m = of.merge(aut, left_on="chave", right_on="segmento_id", suffixes=("_of", ""))
            g_of = m[[f"{g}_of" for g in GRAV]].to_numpy()
            g_aut = m[GRAV].to_numpy()
            exato = (g_of == g_aut).all(axis=1)
            ups_of, ups = g_of @ [1, 4, 28], g_aut @ [1, 4, 28]
            a = criticos(m.assign(segmento_id=m["chave"])[["segmento_id", "extensao_trecho", *GRAV]])
            bb = b & set(m["chave"])
            print(f"  [{metodo:>10}] {len(m)} segmentos; sinistros {g_aut.sum()} (oficial {g_of.sum()}); "
                  f"contagens iguais {exato.mean():.1%}; correlação da UPS {np.corrcoef(ups, ups_of)[0, 1]:.3f}; "
                  f"Trilha 1: {len(a & bb)} críticos em comum de {len(bb)} oficiais e {len(a)} automáticos "
                  f"(Jaccard {len(a & bb) / max(1, len(a | bb)):.2f})")


if __name__ == "__main__":
    main(*sys.argv[1:])
