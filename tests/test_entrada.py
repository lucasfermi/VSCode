import pandas as pd
import pytest

from conftest import RAIZ
from utils.entrada import ErroEntrada, adaptar_planilha, ler_arquivo


def test_modelo_do_app_preserva_ids():
    arq = RAIZ / "data" / "exemplo_dados.csv"
    dados, avisos = adaptar_planilha(ler_arquivo(arq.name, arq.read_bytes()))
    assert dados["segmento_id"].tolist() == ["A1", "A2", "A3"]          # a v4 trocava por 0, 1, 2
    assert dados["n_anos"].tolist() == [1, 1, 1]


def test_csv_brasileiro_com_ponto_e_virgula_e_virgula_decimal():
    texto = ("segmento_id;sem_vitima;com_vitima;com_obito;latitude;longitude;volume_trafego;extensao_trecho\n"
             "A1;10;2;0;-15,78;-47,93;5.000;1,2\n").encode("latin-1")
    dados, _ = adaptar_planilha(ler_arquivo("dados.CSV", texto))
    linha = dados.iloc[0]
    assert (linha["latitude"], linha["longitude"], linha["extensao_trecho"]) == (-15.78, -47.93, 1.2)
    assert linha["volume_trafego"] == 5000


def test_planilha_oficial_separa_sentidos_e_soma_anos():
    df = pd.DataFrame({
        "ID": [25, 25], "CodigoSNV": ["050BMG0220"] * 2, "Comprimento": [1.0, 1.0],
        "Latitude Média": [-18.86, -18.86], "Longitude Média": [-48.25, -48.25],
        "Sentido": ["Crescente", "Decrescente"], "VMD 2021": [100, 100], "VMD 2022": [200, 200],
        "Sinistros_SV 2021": [1, 0], "Sinistros_SV 2022": [2, 0], "Sinistros_CV 2021": [0, 1],
        "Sinistros_CV 2022": [0, 0], "Sinistros_CO 2021": [0, 0], "Sinistros_CO 2022": [1, 0],
    })
    dados, avisos = adaptar_planilha(df)
    assert dados["segmento_id"].tolist() == ["25-C", "25-D"]
    assert dados["sem_vitima"].tolist() == [3, 0]
    assert dados["com_obito"].tolist() == [1, 0]
    assert dados["volume_trafego"].tolist() == [150, 150]
    assert dados["n_anos"].tolist() == [2, 2]
    assert any("sentido" in a for a in avisos)


def test_planilha_oficial_com_um_sinistro_por_linha_mantem_os_sentidos():
    # formato do input de Kernel da análise prévia: uma linha por sinistro e o ID repetido nos dois sentidos
    df = pd.DataFrame({
        "ID": [29, 29, 29, 30], "ID_2": [33, 34, 34, 35], "CodigoSNV": ["050BMG0240"] * 4, "Comprimento": [1.0] * 4,
        "latitude": [-18.88, -18.88, -18.88, -18.89], "longitude": [-48.26, -48.26, -48.26, -48.25],
        "Sentido": ["Decrescente", "Crescente", "Crescente", "Crescente"],
        "Sinistros_SV.2021": [1, 0, 0, 0], "Sinistros_CV.2021": [0, 1, 0, 1], "Sinistros_CO.2021": [0, 0, 1, 0],
    })
    dados, avisos = adaptar_planilha(df)
    assert dados["segmento_id"].tolist() == ["29-D", "29-C", "30-C"]     # antes: os dois sentidos do 29 somados
    assert dados[["sem_vitima", "com_vitima", "com_obito"]].to_numpy().tolist() == [[1, 0, 0], [0, 1, 1], [0, 1, 0]]
    assert any("somadas" in a for a in avisos)


def test_coluna_de_total_nao_vira_obito_e_linha_de_total_sai():
    df = pd.DataFrame({"ID": ["1", "2", None, "TOTAL"], "sem_vitima": [1, 0, None, 1],
                       "com_vitima": [2, 1, None, 3], "com_obito": [0, 1, None, 1],
                       "TOTAL_COM_VITIMA": [2, 1, None, 3], "extensao": [1, 1, 1, 2]})
    dados, avisos = adaptar_planilha(df)
    assert dados["segmento_id"].tolist() == ["1", "2"]
    assert dados["com_obito"].tolist() == [0, 1]                       # a v4 somava a coluna de total


def test_sem_colunas_de_sinistro_da_erro_claro():
    with pytest.raises(ErroEntrada, match="colunas de sinistros"):
        adaptar_planilha(pd.DataFrame({"ID": [1], "acidentes_leves": [3]}))
