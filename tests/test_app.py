"""Teste de fumaça da interface: carrega dados, executa as trilhas e gera o PDF sem erro."""
from streamlit.testing.v1 import AppTest

from conftest import RAIZ
from utils.entrada import adaptar_planilha, ler_arquivo


def _app_com_dados(arquivo):
    arq = RAIZ / "data" / arquivo
    dados, _ = adaptar_planilha(ler_arquivo(arq.name, arq.read_bytes()))
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=120)
    at.session_state["dados"] = dados
    at.run()
    return at


def test_fluxo_completo_sem_excecao():
    at = _app_com_dados("exemplo_dados.csv")
    assert not at.exception
    assert [t.label for t in at.tabs][:4] == ["Pesos UPS", "Trilha 1 — Valor Crítico",
                                             "Trilha 2 — Densidade de Kernel (KDE)", "Trilha 3 — Empírico de Bayes"]
    [b for b in at.button if "Executar" in str(b.label)][0].click().run()
    assert not at.exception
    assert [t.label for t in at.tabs][-3:] == ["Trilha 1 — Valor Crítico", "Trilha 2 — Densidade de Kernel (KDE)",
                                              "Trilha 3 — Empírico de Bayes"]
    pdf = at.session_state["pdf"]
    assert pdf[:4] == b"%PDF"
    # mudar um peso invalida os resultados em vez de mantê-los desatualizados
    at.slider[2].set_value(30).run()
    assert not at.exception
    assert any("mudaram" in i.value for i in at.info)


def test_trilha_sem_requisito_mostra_aviso_e_nao_quebra():
    at = _app_com_dados("exemplo_manual_trilha1.csv")          # sem coordenadas
    [b for b in at.button if "Executar" in str(b.label)][0].click().run()
    assert not at.exception
    assert any("latitude e longitude" in w.value for w in at.warning)
