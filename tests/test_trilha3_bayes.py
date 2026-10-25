import os

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from models.trilha3_bayes import _marshall, aplicar_bayes
from utils.preprocessamento import preparar_dados


def _base(n=300, semente=0):
    rng = np.random.default_rng(semente)
    vmd = rng.lognormal(8.5, 0.6, n)
    L = np.where(rng.random(n) < 0.9, 1.0, rng.uniform(0.2, 1.0, n))
    risco = rng.gamma(2.0, 0.5, n)
    mu = 0.4e-6 * vmd * 365 * 3 * L * risco
    d = pd.DataFrame({"segmento_id": [f"s{i}" for i in range(n)], "latitude": -15.8, "longitude": -47.9,
                      "extensao_trecho": L, "volume_trafego": vmd, "n_anos": 3,
                      "sem_vitima": rng.poisson(mu * 0.15), "com_vitima": rng.poisson(mu * 0.75),
                      "com_obito": rng.poisson(mu * 0.08)})
    return preparar_dados(d, 1, 4, 28)


def _v4_original(d):
    """Cópia da lógica de models/trilha3_bayes.py da v4 (com o índice por nome)."""
    df = d.copy()
    df["exposicao"] = df["volume_trafego"] * df["extensao_trecho"] * 365 * 3
    y = df["UPS"]
    X = sm.add_constant(np.log(df["exposicao"]))
    nb = sm.NegativeBinomial(y, X, loglike_method="nb2").fit(disp=False)
    df["N_previsto"] = nb.predict(X)
    df["resid2"] = ((df["UPS"] - df["N_previsto"]) ** 2).replace(0, 1e-6)
    c = sm.OLS(np.log(df["resid2"]), sm.add_constant(np.log(df["extensao_trecho"]))).fit().params.iloc[0]
    df["phi"] = np.exp(c + np.log(df["extensao_trecho"]))
    df["omega"] = 1 / (1 + df["N_previsto"] * df["phi"])
    df["ajustado"] = df["omega"] * df["N_previsto"] + (1 - df["omega"]) * df["UPS"]
    df["dp"] = np.sqrt((1 - df["omega"]) * df["ajustado"])
    df["Critico"] = df["ajustado"] > df["N_previsto"] + 1.96 * df["dp"]
    return df.set_index("segmento_id")


def test_modo_v4_reproduz_a_v4():
    d = _base()
    ref = _v4_original(d)
    res = aplicar_bayes(d, metodo="v4_script_r").set_index("segmento_id").loc[ref.index]
    np.testing.assert_allclose(res["ajustado"], ref["ajustado"], rtol=1e-5, atol=1e-6)
    assert (res["Critico"] == ref["Critico"]).all()


def test_marshall_encolhe_para_a_media_global():
    rng = np.random.default_rng(5)
    n = rng.uniform(1, 20, 500)
    x = rng.poisson(0.5 * n * rng.gamma(4, 0.25, 500)).astype(float)
    esperado, peso, previsto = _marshall(x, n)
    assert ((peso >= 0) & (peso <= 1)).all()
    taxa_global = x.sum() / n.sum()
    # a estimativa fica entre o observado e a média global
    lo = np.minimum(x / n, taxa_global) - 1e-12
    hi = np.maximum(x / n, taxa_global) + 1e-12
    assert ((esperado / n >= lo) & (esperado / n <= hi)).all()
    # segmentos com menos exposição encolhem mais
    assert np.corrcoef(n, peso)[0, 1] < 0


@pytest.mark.parametrize("metodo", ["media_global", "nb_gravidade"])
def test_metodos_por_gravidade_corrigem_regressao_a_media(metodo):
    d = _base(n=1500, semente=3)
    res = aplicar_bayes(d, metodo=metodo)
    assert res["omega"].median() > 0.1                      # na v4 a mediana fica perto de 0,002
    v4 = aplicar_bayes(d, metodo="v4_script_r")
    assert v4["omega"].median() < 0.05


def test_sem_vmd_da_erro_claro():
    d = _base(20)
    d["volume_trafego"] = np.nan
    with pytest.raises(ValueError, match="volume de tráfego"):
        aplicar_bayes(d)


@pytest.mark.skipif(not os.environ.get("DADOS_SCRIPT_R"), reason="defina DADOS_SCRIPT_R=dados_analisados.xlsx")
def test_igual_a_saida_do_script_r():
    """Compara com a saída do script R (arquivo não versionado por depender de autorização da fonte)."""
    from utils.entrada import adaptar_planilha
    raw = pd.read_excel(os.environ["DADOS_SCRIPT_R"])
    brutas = [c for c in raw.columns if c in ("ID", "CodigoSNV", "Comprimento", "Latitude Média", "Longitude Média",
                                              "Sentido") or c.startswith(("VMD ", "Sinistros_"))]
    dados, _ = adaptar_planilha(raw[brutas])
    res = aplicar_bayes(preparar_dados(dados, 1, 4, 28), metodo="v4_script_r")
    res = res.set_index("segmento_id").loc[dados["segmento_id"]]
    np.testing.assert_allclose(res["ajustado"].to_numpy(), raw["Nesperado"].to_numpy(), rtol=1e-3, atol=1e-3)
    assert (res["Critico"].to_numpy() == raw["critico"].eq("Crítico").to_numpy()).all()
