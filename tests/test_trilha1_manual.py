"""Conferência da Trilha 1 com os exemplos resolvidos do Manual (item 5.1, Tabelas 5.1 a 5.5)."""
import numpy as np
import pandas as pd
import pytest

from conftest import RAIZ
from models.trilha1_valor_critico import aplicar_valor_critico
from utils.entrada import adaptar_planilha, ler_arquivo
from utils.preprocessamento import preparar_dados


@pytest.fixture(scope="module")
def manual():
    arq = RAIZ / "data" / "exemplo_manual_trilha1.csv"
    dados, _ = adaptar_planilha(ler_arquivo(arq.name, arq.read_bytes()))
    return preparar_dados(dados, 1, 4, 28)


def criticos(res):
    return {int(s.split()[-1]) for s in res.loc[res["Critico"], "segmento_id"]}


def test_formato_longo_vira_um_segmento_com_3_anos(manual):
    assert len(manual) == 15
    assert (manual["n_anos"] == 3).all()
    assert manual["total_sinistros"].sum() == 219     # soma da Tabela 5.1
    assert manual["UPS"].sum() == 843                 # total da Tabela 5.5


def test_numero_de_sinistros(manual):
    res = aplicar_valor_critico(manual, metodo="numero")
    assert criticos(res) == {7, 8, 9}
    # O Manual imprime Ns = 15,73, mas a soma 226/15 dá 15,07 (erro aritmético do exemplo).
    assert res.attrs["media"] == pytest.approx(226 / 15)
    # Com o Ns impresso no Manual, a equação 3.3 dá os limites da página 56.
    ns, k = 15.73, 1.645
    for E, esperado in [(1, 21.76), (0.8, 22.40), (0.6, 23.32), (0.4, 24.80)]:
        assert ns + k * np.sqrt(ns / E) - 0.5 / E == pytest.approx(esperado, abs=0.01)


def test_severidade(manual):
    res = aplicar_valor_critico(manual, metodo="severidade")
    assert res.attrs["media"] == pytest.approx(57.48, abs=0.005)
    assert criticos(res) == {7, 8, 9, 11}
    assert [int(s.split()[-1]) for s in res.loc[res["Critico"], "segmento_id"]] == [9, 7, 11, 8]
    vc = res.drop_duplicates("extensao_trecho").set_index("extensao_trecho")["Valor_Critico"]
    for E, esperado in [(1.0, 69.46), (0.8, 70.80), (0.6, 72.75), (0.4, 75.95)]:
        assert vc[E] == pytest.approx(esperado, abs=0.015)


def test_taxa_de_severidade(manual):
    res = aplicar_valor_critico(manual, metodo="taxa_severidade")
    assert res.attrs["media"] == pytest.approx(2.637, abs=0.0005)
    assert criticos(res) == {3, 7, 8, 9}                      # Tabela 5.5
    s1 = res.set_index("segmento_id").loc["Segmento 1"]
    assert s1["Indice"] == pytest.approx(2.879, abs=0.0005)
    assert s1["Valor_Critico"] == pytest.approx(3.652, abs=0.0005)


def test_taxa_de_sinistros_tabela_5_4(manual):
    # A Tabela 5.3 usa 16 sinistros no segmento 10 e 2 no segmento 15 (na Tabela 5.1 são 2 e 3).
    d = manual.copy()
    d.loc[d["segmento_id"] == "Segmento 10", ["sem_vitima", "com_vitima", "com_obito"]] = [16, 0, 0]
    d.loc[d["segmento_id"] == "Segmento 15", ["sem_vitima", "com_vitima", "com_obito"]] = [2, 0, 0]
    d = preparar_dados(d, 1, 4, 28)
    res = aplicar_valor_critico(d, metodo="taxa_sinistros")
    assert res.attrs["media"] == pytest.approx(0.726, abs=0.0005)
    assert criticos(res) == {7, 8, 9, 10}
    assert [int(s.split()[-1]) for s in res.loc[res["Critico"], "segmento_id"]] == [7, 9, 8, 10]
    tab = res.set_index("segmento_id")
    assert tab.loc["Segmento 1", "Valor_Critico"] == pytest.approx(1.218, abs=0.0005)
    assert tab.loc["Segmento 15", "Valor_Critico"] == pytest.approx(1.288, abs=0.0005)


def test_sinal_da_correcao_e_exclusao_de_zeros():
    d = pd.DataFrame({"segmento_id": list("abcd"), "extensao_trecho": [1, 1, 1, 0.005],
                      "sem_vitima": [0, 4, 9, 0], "com_vitima": [0, 1, 2, 0], "com_obito": [0, 0, 1, 0]})
    d = preparar_dados(d, 1, 4, 28)
    menos = aplicar_valor_critico(d, sinal_correcao=-1)
    mais = aplicar_valor_critico(d, sinal_correcao=+1)
    assert (mais["Valor_Critico"] - menos["Valor_Critico"]).round(9).tolist() == \
        (1 / mais["extensao_trecho"]).round(9).tolist()
    sem_zeros = aplicar_valor_critico(d, incluir_sem_sinistros=False)
    assert set(sem_zeros["segmento_id"]) == {"b", "c"}


def test_segmento_curto_sem_sinistros_nunca_e_critico():
    """Com a correção -0,5/m, o valor crítico de um segmento curto fica negativo; sem sinistros, não é crítico."""
    ids = ["a", *[f"b{i}" for i in range(18)], "c", "d"]
    d = pd.DataFrame({"segmento_id": ids, "extensao_trecho": [1.0] * 19 + [0.05, 0.05],
                      "sem_vitima": [1] + [0] * 18 + [0, 1], "com_vitima": 0, "com_obito": 0})
    res = aplicar_valor_critico(preparar_dados(d, 1, 4, 28)).set_index("segmento_id")
    assert res.loc["c", "Valor_Critico"] < 0 and not res.loc["c", "Critico"]
    assert res.loc["d", "Critico"]                       # curto, mas com sinistro: segue a regra do Manual
    assert any("valor crítico negativo" in a for a in res.attrs["avisos"])
