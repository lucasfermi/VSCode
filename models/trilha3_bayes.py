"""Trilha 3 — Método Empírico de Bayes.

Três variantes, escolhidas pelo parâmetro ``metodo``:

* ``media_global`` (padrão): EB pela Média Global, como descreve o Manual (item 3.2),
  com o estimador global de Marshall (1991). É aplicado a cada tipo de sinistro
  (sem vítima, com vítima, com óbito) e o resultado é somado com os pesos da UPS.
  Aplicar o EB direto sobre a UPS (soma ponderada) subestima a variância e anula a
  correção da regressão à média.
* ``nb_gravidade``: EB com Binomial Negativa por tipo de sinistro (Hauer; HSM),
  com superdispersão k = alpha / extensão.
* ``v4_script_r``: procedimento da v4 (Binomial Negativa sobre a UPS + regressão de
  log(resíduo²) em log(extensão)). Reproduz o script R; mantido para comparação.

Critério de criticidade (``criterio``):

* ``manual``: esperado acima da referência (taxa esperada > taxa global no método da
  Média Global; esperado > previsto pela regressão nos demais).
* ``z``: esperado > referência + z x desvio-padrão, com z do nível de confiança.
"""
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm

from utils.constantes import COLUNAS_SINISTROS, k_por_nivel

METODOS = {
    "media_global": "Média Global por tipo de sinistro (Manual; Marshall, 1991)",
    "nb_gravidade": "Binomial Negativa por tipo de sinistro (Hauer; HSM)",
    "v4_script_r": "Binomial Negativa sobre a UPS + ajuste φ (v4 / script R)",
}
CRITERIOS = {
    "manual": "Esperado acima da referência (Manual)",
    "z": "Esperado acima da referência + z desvios-padrão",
}
CRITERIO_PADRAO = {"media_global": "manual", "nb_gravidade": "manual", "v4_script_r": "z"}


def _exposicao(d):
    """Exposição no período, em milhões de veículos-km (Manual, eq. 3.7)."""
    return d["volume_trafego"] * d["n_anos"] * 365 * d["extensao_trecho"] * 1e-6


def _marshall(x, n):
    """Estimador EB global de Marshall (1991) para as taxas x/n.

    Retorna (esperado, peso da referência, previsto), em contagens do período."""
    x = np.asarray(x, float)
    n = np.asarray(n, float)
    r = x / n
    m = x.sum() / n.sum()
    s2 = np.sum(n * (r - m) ** 2) / n.sum()
    A = max(s2 - m / n.mean(), 0.0)          # variância entre segmentos
    C = A / (A + m / n) if A > 0 else np.zeros_like(n)
    taxa = m + C * (r - m)
    return taxa * n, 1 - C, m * n


def _nb_hauer(x, n, L):
    """EB com Binomial Negativa (NB2) e k = alpha / L (Hauer, 2001)."""
    x = np.asarray(x, float)
    X = sm.add_constant(np.log(np.asarray(n, float)), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = sm.NegativeBinomial(x, X, loglike_method="nb2").fit(disp=False, maxiter=300)
    mu = np.asarray(res.predict(X), float)
    alpha = float(np.asarray(res.params)[-1])
    if not np.isfinite(alpha) or alpha <= 0 or not res.mle_retvals.get("converged", True):
        raise RuntimeError("a Binomial Negativa não convergiu")
    w = 1.0 / (1.0 + (alpha / np.asarray(L, float)) * mu)
    return w * mu + (1 - w) * x, w, mu


def _v4_script_r(y, n, L):
    """Procedimento da v4 (equivalente ao script R), com o índice corrigido para pandas 3."""
    y = np.asarray(y, float)
    X = sm.add_constant(np.log(np.asarray(n, float)), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        modelo_nb = sm.NegativeBinomial(y, X, loglike_method="nb2").fit(disp=False)
    previsto = np.asarray(modelo_nb.predict(X), float)
    resid2 = (y - previsto) ** 2
    resid2[resid2 == 0] = 1e-6
    X_res = sm.add_constant(np.log(np.asarray(L, float)), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        c = float(np.asarray(sm.OLS(np.log(resid2), X_res).fit().params)[0])
    phi = np.exp(c + np.log(np.asarray(L, float)))
    omega = 1 / (1 + previsto * phi)
    ajustado = omega * previsto + (1 - omega) * y
    return ajustado, omega, previsto, np.sqrt((1 - omega) * ajustado)


def aplicar_bayes(df, metodo="media_global", criterio=None, nivel_confianca=97.5, pesos=None):
    """Aplica a Trilha 3. ``pesos`` = pesos da UPS (padrão: os usados em preparar_dados).

    Devolve uma linha por segmento com: N_observado (UPS observada no período),
    N_previsto (referência), omega (peso da referência), ajustado (UPS esperada),
    desvio_padrao, excesso (ajustado - previsto) e Critico.
    """
    if metodo not in METODOS:
        raise ValueError(f"Método desconhecido: {metodo}")
    criterio = criterio or CRITERIO_PADRAO[metodo]
    pesos = pesos or df.attrs.get("pesos_ups") or {"sem_vitima": 1, "com_vitima": 4, "com_obito": 28}

    d = df.copy()
    if "n_anos" not in d:
        d["n_anos"] = 1
    if "volume_trafego" not in d or not (pd.to_numeric(d["volume_trafego"], errors="coerce") > 0).any():
        raise ValueError("A Trilha 3 precisa do volume de tráfego (VMD) dos segmentos.")
    d["exposicao"] = _exposicao(d)
    avisos = []
    validos = d["exposicao"] > 0
    if (~validos).any():
        avisos.append(f"{int((~validos).sum())} segmento(s) sem VMD ou extensão ficaram fora da Trilha 3.")
    d = d[validos].copy()
    if len(d) < 3:
        raise ValueError("A Trilha 3 precisa de pelo menos 3 segmentos com VMD e extensão.")

    n = d["exposicao"].to_numpy(float)
    L = d["extensao_trecho"].to_numpy(float)
    ups_obs = sum(pesos[c] * d[c].to_numpy(float) for c in COLUNAS_SINISTROS)

    if metodo == "v4_script_r":
        # mesma escala de exposição da v4 (veículos-km), para reproduzir o ajuste numérico
        ajustado, omega, previsto, dp = _v4_script_r(ups_obs, n * 1e6, L)
    else:
        ajustado = np.zeros(len(d))
        previsto = np.zeros(len(d))
        variancia = np.zeros(len(d))
        for c in COLUNAS_SINISTROS:
            x = d[c].to_numpy(float)
            if pesos[c] == 0:
                continue
            if x.sum() == 0:            # nenhum sinistro desse tipo na base
                continue
            if metodo == "nb_gravidade":
                try:
                    esp, w, prev = _nb_hauer(x, n, L)
                except Exception:
                    esp, w, prev = _marshall(x, n)
                    avisos.append(f"Binomial Negativa sem convergência para '{c}': usada a Média Global.")
            else:
                esp, w, prev = _marshall(x, n)
            ajustado += pesos[c] * esp
            previsto += pesos[c] * prev
            variancia += pesos[c] ** 2 * (1 - w) * esp
        dp = np.sqrt(variancia)
        with np.errstate(divide="ignore", invalid="ignore"):
            omega = np.where(ups_obs != previsto, (ups_obs - ajustado) / (ups_obs - previsto), 1.0)

    if criterio == "manual":
        critico = ajustado > previsto
        z = None
    else:
        z = k_por_nivel(nivel_confianca)
        critico = ajustado > previsto + z * dp

    res = d.assign(
        N_observado=ups_obs, N_previsto=previsto, omega=np.clip(omega, 0, 1), ajustado=ajustado,
        desvio_padrao=dp, excesso=ajustado - previsto, Critico=critico,
    )
    colunas = ["segmento_id", "latitude", "longitude", "extensao_trecho", "volume_trafego", "n_anos",
               *COLUNAS_SINISTROS, "exposicao", "N_observado", "N_previsto", "omega", "ajustado",
               "desvio_padrao", "excesso", "Critico"]
    res = res[[c for c in colunas if c in res]].sort_values("ajustado", ascending=False).reset_index(drop=True)
    res["UPS"] = res["N_observado"]
    res.attrs.update({"avisos": avisos, "metodo": metodo, "criterio": criterio, "z": z})
    return res


# Nome usado pela v4
def aplicar_bayes_trilha3(df, metrica="UPS"):
    return aplicar_bayes(df, metodo="v4_script_r", criterio="z", nivel_confianca=97.5)
