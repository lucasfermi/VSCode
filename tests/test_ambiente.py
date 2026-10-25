from importlib import metadata

import utils.ambiente as amb


def _simular(monkeypatch, versoes, tem_enums=True):
    def versao(pacote):
        if pacote in versoes:
            return versoes[pacote]
        raise metadata.PackageNotFoundError(pacote)
    monkeypatch.setattr(amb.metadata, "version", versao)
    monkeypatch.setattr(amb.importlib.util, "find_spec", lambda nome: object() if tem_enums else None)


def _completo(**extras):
    v = {p: m for p, m in amb.MINIMOS.items()}
    v.update(extras)
    return v


def test_ambiente_correto_nao_reclama(monkeypatch):
    _simular(monkeypatch, _completo())
    assert amb.verificar_ambiente() == ([], [])


def test_ambiente_da_v4_com_fpdf_antigo_e_bloqueado(monkeypatch):
    versoes = _completo(fpdf="1.7.2")
    del versoes["fpdf2"]
    _simular(monkeypatch, versoes, tem_enums=False)
    erros, _ = amb.verificar_ambiente()
    assert any("fpdf2" in e for e in erros)
    assert any("fpdf` 1.7.2" in e for e in erros)


def test_fpdf_antigo_junto_com_fpdf2_so_avisa(monkeypatch):
    _simular(monkeypatch, _completo(fpdf="1.7.2"), tem_enums=True)
    erros, avisos = amb.verificar_ambiente()
    assert erros == [] and len(avisos) == 1


def test_streamlit_antigo_e_bloqueado(monkeypatch):
    _simular(monkeypatch, _completo(streamlit="1.49.1"))
    erros, _ = amb.verificar_ambiente()
    assert any("streamlit" in e for e in erros)
