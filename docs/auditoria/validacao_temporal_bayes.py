"""Validação temporal da Trilha 3, Empírico de Bayes (auditoria de 19/10/2026).

Estima a UPS esperada de cada segmento com 2021-2022 e confere com o que aconteceu em 2023.
Uso, a partir da pasta do projeto:

    python docs/auditoria/validacao_temporal_bayes.py caminho/para/planilha_oficial.xlsx

A planilha precisa das colunas oficiais (ID, Comprimento, Sentido, VMD AAAA, Sinistros_SV/CV/CO AAAA)
com os anos 2021, 2022 e 2023.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from models.trilha3_bayes import _marshall, aplicar_bayes  # noqa: E402
from utils.entrada import adaptar_planilha  # noqa: E402
from utils.preprocessamento import preparar_dados  # noqa: E402

PESOS = {"SV": 1, "CV": 4, "CO": 28}


def ups(raw, anos):
    return sum(p * raw[[f"Sinistros_{t} {a}" for a in anos]].sum(axis=1) for t, p in PESOS.items()).to_numpy(float)


def main(arquivo):
    raw = pd.read_excel(arquivo)
    base = [c for c in raw.columns if c in ("ID", "CodigoSNV", "Comprimento", "Latitude Média", "Longitude Média",
                                            "Sentido") or c.startswith("VMD ")]
    antes = raw[base + [c for c in raw.columns if c.startswith("Sinistros_") and c[-4:] in ("2021", "2022")]]
    dados, _ = adaptar_planilha(antes)
    proc = preparar_dados(dados, 1, 4, 28)
    obs_2023 = ups(raw, ["2023"])
    anos = 2

    est = {"Observado, sem ajuste": proc["UPS"].to_numpy() / anos}
    for metodo, nome in [("v4_script_r", "Bayes da v4 (= script R)"), ("media_global", "Média Global por tipo (v4.1)"),
                         ("nb_gravidade", "Binomial Negativa por tipo")]:
        res = aplicar_bayes(proc, metodo=metodo).set_index("segmento_id").loc[proc["segmento_id"]]
        est[nome] = res["ajustado"].to_numpy() / anos
    n = (proc["volume_trafego"] * anos * 365 * proc["extensao_trecho"] * 1e-6).to_numpy()
    esp, _, _ = _marshall(proc["UPS"].to_numpy(float), n)
    est["Média Global sobre a UPS"] = esp / anos

    print(f"{'Método':<30} {'RMSE':>6} {'top 10%: previsto':>18} {'realizado 2023':>15}")
    for nome, e in est.items():
        top = e >= np.quantile(e, 0.9)
        rmse = np.sqrt(np.mean((obs_2023 - e) ** 2))
        print(f"{nome:<30} {rmse:6.2f} {e[top].mean():18.1f} {obs_2023[top].mean():15.1f}")


if __name__ == "__main__":
    main(sys.argv[1])
