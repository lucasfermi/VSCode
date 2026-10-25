"""Confere o ambiente Python antes de abrir o app, para mostrar uma mensagem clara
em vez de um erro de importação (ex.: 'No module named fpdf.enums' quando o
ambiente ainda tem o fpdf antigo da v4)."""
import importlib.util
import os
import sys
from importlib import metadata

from packaging.version import InvalidVersion, Version

# Versões mínimas que a v4.1 usa (o requirements.txt fixa as versões testadas)
MINIMOS = {
    "streamlit": "1.58",      # st.iframe, width="stretch", on_click="ignore"
    "pandas": "2.0",
    "numpy": "1.24",
    "scipy": "1.6",           # cKDTree.query_ball_point(workers=...)
    "statsmodels": "0.13",
    "folium": "0.15",         # GeoJson(marker=...)
    "matplotlib": "3.5",
    "fpdf2": "2.7",           # fpdf.enums.XPos/YPos
    "xlsxwriter": "3.0",
    "openpyxl": "3.0",
}


def _versao(pacote):
    try:
        return metadata.version(pacote)
    except metadata.PackageNotFoundError:
        return None


def verificar_ambiente():
    """Retorna (erros, avisos). Erros impedem o app de funcionar; avisos não."""
    erros, avisos = [], []
    for pacote, minimo in MINIMOS.items():
        v = _versao(pacote)
        if v is None:
            erros.append(f"Falta o pacote `{pacote}` (versão {minimo} ou mais nova).")
            continue
        try:
            if Version(v) < Version(minimo):
                erros.append(f"`{pacote}` {v} é antigo; a v4.1 precisa da versão {minimo} ou mais nova.")
        except InvalidVersion:
            pass
    antigo = _versao("fpdf")
    if antigo:
        if importlib.util.find_spec("fpdf.enums") is None:
            erros.append(f"O pacote antigo `fpdf` {antigo} (usado pela v4) está ativo neste ambiente; "
                         "a v4.1 usa o `fpdf2`, e os dois não podem ficar juntos.")
        else:
            avisos.append(f"O pacote antigo `fpdf` {antigo} continua instalado junto com o `fpdf2`. "
                          "Funciona, mas o ideal é um ambiente só para a v4.1.")
    return erros, avisos


def instrucoes_instalacao():
    """Comandos para criar um ambiente só da v4.1, rodados na pasta do projeto."""
    if os.name == "nt":
        return ("python -m venv .venv\n"
                ".venv\\Scripts\\python -m pip install -r requirements.txt\n"
                ".venv\\Scripts\\python -m streamlit run app.py")
    return ("python3 -m venv .venv\n"
            ".venv/bin/python -m pip install -r requirements.txt\n"
            ".venv/bin/python -m streamlit run app.py")


def python_em_uso():
    return sys.executable
