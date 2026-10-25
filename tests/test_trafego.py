"""VMD do PNCT ligado aos segmentos do SNV (planilha sintética no formato da modelagem do PNCT)."""
import io

import numpy as np
import pandas as pd
import pytest

from utils import trafego as tf


def planilha_pnct(linhas):
    """Excel com aba de metadados e a tabela a partir da 2ª linha, como a planilha do PNCT."""
    colunas = ["vl_br", "sg_uf", "desc_coinc", "vl_codigo", "vl_km_inic", "vl_km_fina", "vl_km_i_estim",
               "vl_km_f_estim", "versao_snv", "classificação", "VMDa_C", "VMDa_D"]
    tabela = pd.DataFrame(linhas, columns=colunas)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        metadados = pd.DataFrame({"Nome do Campo": ["vl_codigo"], "Descrição": ["código"]})
        metadados.to_excel(w, sheet_name="Metadados", index=False)
        pd.DataFrame([["Dados PNCT - 202001A"]]).to_excel(w, sheet_name="SNV_202001A", index=False, header=False)
        tabela.to_excel(w, sheet_name="SNV_202001A", index=False, startrow=1)
    return buf.getvalue()


LINHAS = [
    # trecho que mudou de km entre versões (era 0 a 2, hoje 0 a 2,4)
    (10, "DF", "-", "010BDF0010", 0.0, 2.0, 0.0, 2.0, "202001A", "-", 1000, 1100),
    # trecho dividido em duas partes pelo PNCT
    (10, "DF", "-", "010BDF0020", 2.0, 6.0, 2.0, 4.0, "202001A", "Referencial", 2000, 2100),
    (10, "DF", "-", "010BDF0020", 2.0, 6.0, 4.0, 6.0, "202001A", "Não Simulável", 3000, 3100),
    # trecho de outra BR, só achado pelo km
    (20, "DF", "-", "020BDF0099", 0.0, 10.0, 0.0, 10.0, "202001A", "-", 500, 600),
]


def segmentos():
    return pd.DataFrame({
        "segmento_id": ["010BDF0010-001", "010BDF0010-002", "010BDF0020-001", "010BDF0020-004", "020BDF0050-001",
                        "030BDF0010-001"],
        "codigo_snv": ["010BDF0010", "010BDF0010", "010BDF0020", "010BDF0020", "020BDF0050", "030BDF0010"],
        "br": ["010", "010", "010", "010", "020", "030"],
        "uf": ["DF"] * 6,
        "frac_inicial": [0.0, 0.5, 0.0, 0.75, 0.0, 0.0],
        "frac_final": [0.5, 1.0, 0.25, 1.0, 1.0, 1.0],
        "km_inicial": [0.0, 1.2, 2.0, 5.0, 3.0, 0.0],
        "km_final": [1.2, 2.4, 3.0, 6.0, 4.0, 1.0],
    })


def test_leitura_da_planilha_do_pnct():
    v = tf.ler_vmd_pnct(planilha_pnct(LINHAS), nome="VDM_Modelagem_2019_SNV_202001A.xlsx")
    assert len(v) == 4
    assert v.attrs == {"versao_snv": "202001A", "ano": 2019}
    assert list(v["br"].unique()) == ["010", "020"]
    assert v.loc[2, "classificacao"] == "Não Simulável"
    assert v.loc[1, ["km_ini", "km_fim"]].tolist() == [2.0, 4.0]


def test_planilha_sem_colunas_de_vmd():
    buf = io.BytesIO()
    pd.DataFrame({"vl_codigo": ["x"], "vl_br": [10]}).to_excel(buf, index=False)
    with pytest.raises(ValueError, match="VMDa_C"):
        tf.ler_vmd_pnct(buf.getvalue())


def test_vmd_por_codigo_parte_e_km():
    v = tf.ler_vmd_pnct(planilha_pnct(LINHAS))
    s = tf.atribuir_vmd(segmentos(), v).set_index("segmento_id")
    # mesmo código: a posição vai pela fração do trecho, mesmo com o km diferente entre versões
    assert s.loc["010BDF0010-002", ["vmd_c", "vmd_d"]].tolist() == [1000, 1100]
    # trecho dividido: o começo fica na 1ª parte e o fim na 2ª
    assert s.loc["010BDF0020-001", "vmd_c"] == 2000
    assert s.loc["010BDF0020-004", "vmd_c"] == 3000
    assert s.loc["010BDF0020-004", "vmd_classificacao"] == "Não Simulável"
    # código novo: VMD do trecho da mesma BR que contém o km do meio
    assert s.loc["020BDF0050-001", "vmd_c"] == 500
    assert s.loc["020BDF0050-001", "vmd_origem"] == tf.ORIGEM_KM
    # BR sem VMD
    assert s.loc["030BDF0010-001", "vmd_origem"] == tf.SEM_VMD
    assert np.isnan(s.loc["030BDF0010-001", "vmd_c"])


def test_acesso_com_codigo_novo_nao_usa_o_km_da_br():
    """Acessos, contornos e travessias têm quilometragem própria: sem o código na planilha, ficam sem VMD."""
    v = tf.ler_vmd_pnct(planilha_pnct(LINHAS))
    seg = pd.DataFrame({"segmento_id": ["020ADF0900-001", "020BDF0050-001"], "codigo_snv": ["020ADF0900", "020BDF0050"],
                        "br": ["020", "020"], "uf": ["DF", "DF"], "frac_inicial": [0.0, 0.0], "frac_final": [1.0, 1.0],
                        "km_inicial": [3.0, 3.0], "km_final": [4.0, 4.0]})
    s = tf.atribuir_vmd(seg, v).set_index("segmento_id")
    assert s.loc["020ADF0900-001", "vmd_origem"] == tf.SEM_VMD
    assert s.loc["020BDF0050-001", "vmd_origem"] == tf.ORIGEM_KM
