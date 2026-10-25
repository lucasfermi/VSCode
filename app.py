"""Análise de Segmentos Críticos por Sinistros — interface Streamlit (versão 4.1)."""
import hashlib
import io
import json
import os
import traceback
import zipfile

import streamlit as st

from utils.ambiente import instrucoes_instalacao, python_em_uso, verificar_ambiente

VERSAO = "4.2 (em desenvolvimento)"
BASE = os.path.dirname(os.path.abspath(__file__))
ICONE = os.path.join(BASE, "assets", "icone.png")
LOGO = os.path.join(BASE, "assets", "logo_horizontal.png")
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Análise de Segmentos Críticos",
    page_icon=ICONE if os.path.exists(ICONE) else "🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 1a. AMBIENTE: versões erradas viram uma mensagem com a solução, não um traceback ---
ERROS_AMBIENTE, AVISOS_AMBIENTE = verificar_ambiente()
if ERROS_AMBIENTE:
    st.error("O ambiente Python em uso não tem as bibliotecas da versão 4.1:\n\n"
             + "\n".join(f"- {e}" for e in ERROS_AMBIENTE))
    st.markdown("Crie um ambiente só para a v4.1 (o da v4 precisa do `fpdf` antigo) e abra o app por ele. "
                "Na pasta do projeto:")
    st.code(instrucoes_instalacao(), language="bash")
    st.caption(f"Python em uso agora: `{python_em_uso()}`")
    st.stop()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from models.trilha1_valor_critico import METODOS as METODOS_VC  # noqa: E402
from models.trilha1_valor_critico import aplicar_valor_critico  # noqa: E402
from models.trilha2_kernel import aplicar_kernel  # noqa: E402
from models.trilha3_bayes import CRITERIO_PADRAO, CRITERIOS, aplicar_bayes  # noqa: E402
from models.trilha3_bayes import METODOS as METODOS_EB  # noqa: E402
from utils.constantes import NIVEIS_CONFIANCA_K, ORDEM_TRILHAS, PESOS_UPS_PADRAO, rotulo_trilha  # noqa: E402
from utils.entrada import COLUNAS_MODELO, ErroEntrada, adaptar_planilha, ler_arquivo  # noqa: E402
from utils.mapas import mapa_criticos, mapa_kde  # noqa: E402
from utils.osm import ATRIBUICAO, CLASSES_PRINCIPAIS, CLASSES_URBANAS, ler_vias_osm  # noqa: E402
from utils.preprocessamento import preparar_dados  # noqa: E402
from utils.relatorio import gerar_pdf_completo  # noqa: E402
from utils.segmentacao import (  # noqa: E402
    COMPRIMENTO_PADRAO,
    LIMITES_COMPRIMENTO,
    LONGE_DO_SNV,
    ler_arquivos_sinistros,
    ler_snv_enviado,
    preparar_snv,
    retangulo,
    segmentar,
)
from utils.trafego import ler_vmd_pnct  # noqa: E402

for _aviso in AVISOS_AMBIENTE:
    st.warning(_aviso)

# --- 2. IDENTIDADE VISUAL (a fonte Roboto é servida pelo próprio app; ver .streamlit/config.toml) ---
st.markdown("""
    <style>
        h1 { color: #0988C3 !important; font-weight: 700; border-bottom: 4px solid #FFC900;
             padding-bottom: 10px; margin-bottom: 20px; }
        h2, h3, h4 { color: #64609A; }
        @media (prefers-color-scheme: dark) { h2, h3, h4 { color: #9E9AC8; } }
        div.stButton > button { border-radius: 8px; font-weight: bold; }
        [data-testid="stSidebar"] { border-right: 1px solid #E0E0E0; }
    </style>
""", unsafe_allow_html=True)

ESTADO_INICIAL = {"dados": None, "avisos_entrada": [], "erro_entrada": None, "arquivo_id": None, "uploader_key": 0,
                  "resultados": {}, "erros": {}, "avisos": {}, "df_proc": None, "assinatura": None,
                  "pdf": None, "xlsx": None, "pdf_assinatura": None, "mapas": {}, "msgs_segmentacao": None}
for chave, valor in ESTADO_INICIAL.items():
    st.session_state.setdefault(chave, valor)


def limpar_resultados():
    for chave in ("resultados", "erros", "avisos"):
        st.session_state[chave] = {}
    st.session_state.update(df_proc=None, assinatura=None, pdf=None, xlsx=None, pdf_assinatura=None, mapas={})


def assinatura(dados: pd.DataFrame, opcoes: dict) -> str:
    h = hashlib.sha1(pd.util.hash_pandas_object(dados, index=False).to_numpy().tobytes())
    h.update(json.dumps(opcoes, sort_keys=True).encode())
    return h.hexdigest()


@st.cache_data(show_spinner=False)
def modelo_excel(preenchido: bool) -> bytes:
    linhas = [
        ["A1", 10, 2, 0, -15.7801, -47.9292, 5000, 1.2, 2022],
        ["A2", 3, 1, 1, -15.7654, -47.9400, 4500, 0.8, 2022],
        ["A3", 0, 0, 0, -15.8000, -47.9450, 5200, 1.5, 2022],
        ["A4", 0, 5, 2, -15.8120, -47.8900, 6000, 2.0, 2022],
    ] if preenchido else []
    df = pd.DataFrame(linhas, columns=COLUNAS_MODELO)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Dados", index=False)
        wb, ws = writer.book, writer.sheets["Dados"]
        cab = wb.add_format({"bold": True, "text_wrap": True, "valign": "vcenter", "align": "center",
                             "fg_color": "#0988C3", "font_color": "#FFFFFF", "border": 1})
        for i, nome in enumerate(df.columns):
            ws.write(0, i, nome, cab)
            ws.set_column(i, i, max(len(nome) + 4, 12), wb.add_format({"border": 1}))
    return output.getvalue()


def resultados_planilha(resultados: dict) -> tuple[bytes, str, str]:
    """Excel com uma aba por trilha; acima de 50 mil linhas, CSVs num .zip (bem mais rápido)."""
    output = io.BytesIO()
    if sum(len(r) for r in resultados.values()) <= 50_000:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for chave, res in resultados.items():
                res.to_excel(writer, sheet_name=rotulo_trilha(chave).split(" — ")[0], index=False)
        return output.getvalue(), "resultados_segmentos_criticos.xlsx", MIME_XLSX
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for chave, res in resultados.items():
            nome = rotulo_trilha(chave).split(" — ")[0].replace(" ", "_").lower()
            z.writestr(f"{nome}.csv", res.to_csv(index=False, sep=";", decimal=","))
    return output.getvalue(), "resultados_segmentos_criticos.zip", "application/zip"


LIMITE_PONTOS_MAPA = 20_000


def _chave(arquivos) -> tuple:
    return tuple((a.name, a.size, getattr(a, "file_id", None)) for a in arquivos)


@st.cache_resource(max_entries=2, show_spinner="Lendo o SNV...")
def snv_preparado(chave, _arquivos):
    """SNV lido e preparado uma vez por envio (compartilhado entre execuções)."""
    return preparar_snv(ler_snv_enviado([(a.name, a.getvalue()) for a in _arquivos]))


@st.cache_resource(max_entries=2, show_spinner="Lendo os sinistros...")
def sinistros_lidos(chave, _arquivos):
    return ler_arquivos_sinistros([(a.name, a.getvalue()) for a in _arquivos])


@st.cache_resource(max_entries=2, show_spinner="Lendo as vias do OpenStreetMap...")
def vias_osm_lidas(chave, bbox, classes, _arquivo):
    return ler_vias_osm(_arquivo.getvalue(), bbox, list(classes))


@st.cache_resource(max_entries=2, show_spinner="Lendo o VMD...")
def vmd_pnct(chave, _arquivo):
    return ler_vmd_pnct(_arquivo.getvalue(), nome=_arquivo.name)


SEM_EXTENSAO = ("Nenhuma linha tem a extensão do segmento: a planilha parece ter um sinistro por linha. Com ela, "
                "só a Trilha 2 (KDE) roda. Para as três trilhas, envie-a na Opção 2 (segmentação automática), "
                "com o SNV.")


def avisos_sem_extensao(dados: pd.DataFrame, avisos: list[str]) -> list[str]:
    """Planilha sem nenhuma extensão (em geral, um sinistro por linha): um aviso que indica a Opção 2."""
    if dados["extensao_trecho"].isna().all():
        return [SEM_EXTENSAO] + [a for a in avisos if "sem extensão válida" not in a]
    return avisos


def dica_erro(mensagem: str, dados: pd.DataFrame) -> str:
    """O que o usuário pode fazer quando uma trilha não roda por falta de extensão ou de VMD."""
    sem_extensao = "extensao_trecho" not in dados or dados["extensao_trecho"].isna().all()
    if ("extensão" in mensagem or "VMD" in mensagem) and sem_extensao:
        return (" A planilha não traz a extensão dos segmentos (parece ter um sinistro por linha): envie-a na "
                "Opção 2 (segmentação automática), com o SNV.")
    if "VMD" in mensagem:
        return " Inclua a coluna volume_trafego na planilha ou, na Opção 2, envie a planilha de VMD do PNCT."
    return ""


def mensagens_segmentacao(resumo: dict) -> list[tuple[str, str]]:
    """Resumo da segmentação em mensagens (tipo, texto) para a barra lateral."""
    n, ok = resumo["sinistros"], resumo["atribuidos"]
    msgs = [("success", f"{resumo['segmentos']:,} segmentos de cerca de {resumo['comprimento']:g} km em "
                        f"{', '.join(resumo['ufs'])}; {ok:,} de {n:,} sinistros localizados "
                        f"({ok / n:.0%}). SNV {resumo['versao_snv']}.".replace(",", "."))]
    fora = {k: v for k, v in resumo["situacoes"].items() if not k.startswith("localizado")}
    if fora:
        msgs.append(("warning", "Fora da análise: " + "; ".join(f"{v:,} {k}".replace(",", ".")
                                                             for k, v in fora.items()) + "."))
    longe = resumo["situacoes"].get(LONGE_DO_SNV, 0)
    if longe > 0.1 * n and not resumo.get("osm"):
        msgs.append(("info", f"{longe:,}".replace(",", ".") + " sinistros ficaram longe das rodovias federais. "
                             "Para incluir as vias estaduais e municipais, envie também o arquivo do OpenStreetMap "
                             "da região."))
    if resumo["sem_sentido"]:
        msgs.append(("warning", f"{resumo['sem_sentido']} sinistro(s) sem sentido informado ficaram de fora."))
    osm = resumo.get("osm")
    if osm:
        msgs.append(("success", f"OpenStreetMap: {osm['segmentos']:,} segmentos em {osm['km']:,} km de vias fora do "
                                f"SNV; {osm['sinistros']:,} sinistros nessas vias.".replace(",", ".")))
    vmd = resumo.get("vmd")
    if vmd is None:
        msgs.append(("info", "Sem volume de tráfego (VMD), a Trilha 3 e os métodos de taxa da Trilha 1 não rodam."))
    else:
        ano = vmd["ano"] or "ano não informado"
        msgs.append(("success", f"VMD do PNCT ({ano}, SNV {vmd['versao_snv']}) em {vmd['cobertura']:.0%} dos "
                                "segmentos."))
        if vmd["nao_simulavel"]:
            msgs.append(("warning", f"{vmd['nao_simulavel']} segmento(s) com VMD marcado pelo PNCT como "
                                    "“Não Simulável” (perto de áreas urbanas): use com cautela."))
        if vmd["ano"] and resumo["anos"] and vmd["ano"] not in resumo["anos"]:
            msgs.append(("warning", f"O VMD é de {vmd['ano']} e os sinistros, de "
                                    f"{', '.join(map(str, resumo['anos']))}: as taxas são aproximadas."))
    return msgs


def planilha_segmentos(dados: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        dados.to_excel(writer, sheet_name="Segmentos", index=False)
    return output.getvalue()


def mostrar_mapa(chave, construir, altura=520):
    """Monta o mapa uma vez por execução (fica em cache na sessão)."""
    if chave not in st.session_state.mapas:
        mapa = construir()
        st.session_state.mapas[chave] = None if mapa is None else mapa.get_root().render()
    html_mapa = st.session_state.mapas[chave]
    if html_mapa is None:
        st.info("Sem coordenadas para exibir o mapa.")
    else:  # textos vindos da planilha já são escapados em utils/mapas.py
        st.iframe(html_mapa, height=altura)


def para_mapa(df):
    """Em bases muito grandes, o mapa mostra só os segmentos críticos."""
    if len(df) <= LIMITE_PONTOS_MAPA:
        return df
    st.caption(f"Base com {len(df):,} pontos: o mapa mostra só os críticos.".replace(",", "."))
    return df[df["Critico"].astype(bool)].head(LIMITE_PONTOS_MAPA)


# --- 3. BARRA LATERAL: ENTRADA DE DADOS ---
with st.sidebar:
    if os.path.exists(LOGO):          # marcas do projeto: ver assets/LEIA-ME.md
        st.image(LOGO, width="stretch")
    else:
        st.markdown(
            """<div style="text-align: center; margin-bottom: 25px;">
            <div style="background-color: #0988C3; height: 4px; width: 40px; margin: 0 auto 10px auto;
                        border-radius: 2px;"></div>
            <h2 style="color: #0988C3; margin: 0; padding: 0; font-weight: 700; font-size: 1.4rem;">
                SISTEMA DE DADOS</h2>
            <h3 style="color: #64609A; margin: 0; padding: 0; font-weight: 300; font-size: 1.1rem;">
                RODOVIÁRIOS</h3>
            </div>""",
            unsafe_allow_html=True,
        )
    st.markdown("---")
    st.header("Inserir Dados")

    st.subheader("Opção 1: Carregar Planilha")
    arquivo = st.file_uploader("Carregue um arquivo CSV ou Excel", type=["csv", "xlsx"],
                               key=f"upload_{st.session_state.uploader_key}")
    if arquivo is not None:
        ident = [arquivo.name, arquivo.size, getattr(arquivo, "file_id", None)]
        if st.session_state.arquivo_id != ident:          # processa só quando o arquivo muda
            limpar_resultados()
            st.session_state.msgs_segmentacao = None
            try:
                dados, avisos = adaptar_planilha(ler_arquivo(arquivo.name, arquivo.getvalue()))
                avisos = avisos_sem_extensao(dados, avisos)
                st.session_state.update(dados=dados, avisos_entrada=avisos, erro_entrada=None, arquivo_id=ident)
            except ErroEntrada as e:
                st.session_state.update(dados=None, avisos_entrada=[], erro_entrada=str(e), arquivo_id=ident)
            except Exception as e:  # noqa: BLE001
                st.session_state.update(dados=None, avisos_entrada=[], arquivo_id=ident,
                                        erro_entrada=f"Não foi possível ler a planilha ({type(e).__name__}: {e}).")
        if st.session_state.erro_entrada:
            st.error(f"❌ {st.session_state.erro_entrada}")
        elif st.session_state.dados is not None:
            st.success(f"✅ '{arquivo.name}' carregada: {len(st.session_state.dados)} segmentos.")
            for aviso in st.session_state.avisos_entrada:
                st.warning(aviso)

    col1_modelo, col2_modelo = st.columns(2)
    with col1_modelo:
        st.download_button("📥 Baixar Exemplo", data=modelo_excel(True), file_name="modelo_preenchido.xlsx",
                           mime=MIME_XLSX, on_click="ignore")
    with col2_modelo:
        st.download_button("📋 Modelo em Branco", data=modelo_excel(False), file_name="modelo_em_branco.xlsx",
                           mime=MIME_XLSX, on_click="ignore")

    st.markdown("---")
    st.subheader("Opção 2: Segmentação automática")
    st.caption("Envie os sinistros (dados abertos da PRF ou uma planilha com latitude e longitude) e o SNV do "
               "DNIT: o app corta a malha em segmentos e conta os sinistros de cada um.")
    chave_up = st.session_state.uploader_key
    arqs_sin = st.file_uploader("Sinistros: dados da PRF (datatran) ou planilha com latitude, longitude e ano",
                                type=["csv", "zip", "xlsx"], accept_multiple_files=True, key=f"prf_{chave_up}")
    arqs_snv = st.file_uploader("SNV do DNIT (shapefile em .zip, ou .shp, .shx, .dbf e .prj)",
                                type=["zip", "shp", "shx", "dbf", "prj", "cpg"], accept_multiple_files=True,
                                key=f"snv_{chave_up}")
    arq_vmd = st.file_uploader("VMD por trecho do SNV (planilha de modelagem do PNCT, opcional)", type=["xlsx"],
                               key=f"vmd_{chave_up}")
    arq_osm = st.file_uploader("Vias do OpenStreetMap (.osm.pbf da região, opcional)", type=["pbf", "gpkg", "geojson"],
                               key=f"osm_{chave_up}", help="Arquivos regionais em download.geofabrik.de.")
    if arqs_sin and arqs_snv:
        try:
            sinistros = sinistros_lidos(_chave(arqs_sin), arqs_sin)
            snv = snv_preparado(_chave(arqs_snv), arqs_snv)
            vmd = vmd_pnct(_chave([arq_vmd]), arq_vmd) if arq_vmd is not None else None
        except Exception as e:  # noqa: BLE001
            st.error(f"❌ Não foi possível ler os arquivos ({type(e).__name__}: {e}).")
        else:
            repetidas = sinistros.attrs.get("linhas_repetidas", 0)
            if repetidas:
                st.caption(f"{repetidas:,} linhas repetiam a mesma ocorrência (arquivos por pessoa ou anos "
                           f"repetidos) e foram contadas uma vez: {len(sinistros):,} sinistros.".replace(",", "."))
            sem_coord = sinistros.attrs.get("sem_coordenada", 0)
            if sem_coord:
                st.caption(f"{sem_coord:,} sinistros sem coordenada válida.".replace(",", "."))
            com_km = bool(sinistros.attrs.get("com_km"))
            if sinistros["uf"].notna().any():
                ufs_disp = sorted(sinistros["uf"].dropna().unique())
            else:
                ufs_disp = sorted(snv["sg_uf"].dropna().unique())
            anos_disp = sorted(int(a) for a in sinistros["ano"].dropna().unique())
            ufs = st.multiselect("UF", ufs_disp, placeholder="Escolha a UF")
            anos = st.multiselect("Anos", anos_disp, default=anos_disp[-3:])
            comprimento = st.number_input("Comprimento do segmento (km)", min_value=LIMITES_COMPRIMENTO[0],
                                          max_value=LIMITES_COMPRIMENTO[1], value=COMPRIMENTO_PADRAO, step=0.1,
                                          format="%.1f", help="O Manual recomenda segmentos de 1 km.")
            por_sentido = st.checkbox("Separar por sentido da via", disabled=not com_km,
                                      help="Só para dados com o sentido da via (PRF).")
            residenciais = False
            if arq_osm is not None:
                residenciais = st.checkbox("Incluir ruas residenciais do OpenStreetMap")
                if com_km and sinistros["km"].notna().all():
                    st.warning("Os dados da PRF só cobrem rodovias federais: as vias do OpenStreetMap ficariam sem "
                               "sinistros e pesariam na comparação. Use o OpenStreetMap com bases de todas as vias.")
            if st.button("✂️ Segmentar", width="stretch"):
                try:
                    with st.spinner("Segmentando..."):
                        vias = None
                        if arq_osm is not None and ufs:
                            filtro = sinistros if anos == [] else sinistros[sinistros["ano"].isin(anos)]
                            bbox = tuple(round(v, 3) for v in retangulo(filtro, snv, ufs))
                            classes = tuple(CLASSES_PRINCIPAIS + (CLASSES_URBANAS if residenciais else []))
                            vias = vias_osm_lidas(_chave([arq_osm]), bbox, classes, arq_osm)
                        dados = segmentar(sinistros, snv, ufs, anos, comprimento, por_sentido and com_km, vmd=vmd,
                                          vias_osm=vias)
                    limpar_resultados()
                    st.session_state.update(dados=dados, avisos_entrada=[], erro_entrada=None, arquivo_id=None,
                                            msgs_segmentacao=mensagens_segmentacao(dados.attrs["resumo"]))
                except ValueError as e:
                    st.session_state.msgs_segmentacao = [("error", str(e))]
    if st.session_state.msgs_segmentacao:
        for tipo, texto in st.session_state.msgs_segmentacao:
            getattr(st, tipo)(texto)
        dados_seg = st.session_state.dados
        if dados_seg is not None and "codigo_snv" in dados_seg:
            st.download_button("📥 Baixar segmentos (planilha)", data=planilha_segmentos(dados_seg),
                               file_name="segmentos.xlsx", mime=MIME_XLSX, on_click="ignore", width="stretch")
            if "fonte" in dados_seg and (dados_seg["fonte"] == "OpenStreetMap").any():
                st.caption(f"Vias além do SNV: {ATRIBUICAO}.")

    st.markdown("---")
    st.subheader("Opção 3: Inserir ou Corrigir Trecho")
    with st.form(key="formulario_trecho", clear_on_submit=True):
        segmento = st.text_input("ID do Segmento*", help="Um ID já existente substitui o registro anterior.")
        st.markdown("**Georreferenciamento**")
        latitude = st.number_input("Latitude", value=None, min_value=-90.0, max_value=90.0, format="%.6f")
        longitude = st.number_input("Longitude", value=None, min_value=-180.0, max_value=180.0, format="%.6f")
        st.markdown("**Dados do Segmento**")
        extensao = st.number_input("Extensão (km)", min_value=0.01, value=1.0, format="%.3f")
        volume = st.number_input("Volume tráfego (VMDa)", min_value=0, value=None)
        n_anos = st.number_input("Anos de dados", min_value=1, max_value=20, value=3)
        st.markdown("**Dados de Sinistros (soma do período)**")
        sem_vitima = st.number_input("Sem vítima*", min_value=0, value=None)
        com_vitima = st.number_input("Com vítima*", min_value=0, value=None)
        com_obito = st.number_input("Com óbito*", min_value=0, value=None)
        if st.form_submit_button("➕ Adicionar registro"):
            if not segmento or sem_vitima is None or com_vitima is None or com_obito is None:
                st.error("Preencha os campos obrigatórios (*)")
            else:
                novo = pd.DataFrame([{
                    "segmento_id": segmento.strip(), "latitude": latitude if latitude is not None else np.nan,
                    "longitude": longitude if longitude is not None else np.nan, "extensao_trecho": extensao,
                    "volume_trafego": volume if volume is not None else np.nan, "n_anos": n_anos,
                    "sem_vitima": sem_vitima, "com_vitima": com_vitima, "com_obito": com_obito,
                }])
                atual = st.session_state.dados
                if atual is not None and segmento.strip() in set(atual["segmento_id"]):
                    atual = atual[atual["segmento_id"] != segmento.strip()]
                    st.success(f"Registro '{segmento}' atualizado!")
                else:
                    st.success(f"Registro '{segmento}' adicionado!")
                st.session_state.dados = novo if atual is None else pd.concat([atual, novo], ignore_index=True)
                limpar_resultados()

    st.markdown("---")
    if st.button("Limpar todos os registros"):
        st.session_state.update(dados=None, avisos_entrada=[], erro_entrada=None, arquivo_id=None,
                                msgs_segmentacao=None, uploader_key=st.session_state.uploader_key + 1)
        limpar_resultados()
        st.rerun()
    st.caption(f"Versão {VERSAO}")

# --- 4. PAINEL PRINCIPAL ---
st.title("Análise de Segmentos Críticos por Sinistros")

with st.expander("⚙️ Configurações das análises"):
    aba_pesos, *abas_config = st.tabs(["Pesos UPS"] + [rotulo_trilha(c) for c in ORDEM_TRILHAS])
    aba_config = dict(zip(ORDEM_TRILHAS, abas_config))
    with aba_pesos:
        st.info("Pesos do Manual: 1 (sem vítima), 4 (com vítima) e 28 (com óbito). Valem para as três trilhas.")
        c1, c2, c3 = st.columns(3)
        peso_sv = c1.slider("Peso Sem Vítima", 1, 10, PESOS_UPS_PADRAO["sem_vitima"])
        peso_cv = c2.slider("Peso Com Vítima", 1, 50, PESOS_UPS_PADRAO["com_vitima"])
        peso_co = c3.slider("Peso Com Óbito", 1, 100, PESOS_UPS_PADRAO["com_obito"])
    niveis = list(NIVEIS_CONFIANCA_K)
    with aba_config["vc"]:
        metodo_vc = st.selectbox("Método", list(METODOS_VC), format_func=METODOS_VC.get)
        nivel_vc = st.selectbox("Nível de confiança (%)", niveis, index=niveis.index(95.0),
                                format_func=lambda n: f"{n:g} (k = {NIVEIS_CONFIANCA_K[n]:.3f})")
        sinal_vc = st.radio("Correção de continuidade", [-1, 1], horizontal=True,
                            format_func=lambda s: "−0,5/m (Manual)" if s < 0 else "+1/(2m) (literatura clássica)")
        excluir_zeros = st.checkbox("Excluir segmentos sem sinistros (item 5.1 do Manual)", value=False)
    with aba_config["bayes"]:
        metodo_eb = st.selectbox("Método", list(METODOS_EB), format_func=METODOS_EB.get)
        criterio_eb = st.radio("Critério de criticidade", list(CRITERIOS), format_func=CRITERIOS.get,
                               index=list(CRITERIOS).index(CRITERIO_PADRAO[metodo_eb]))
        nivel_eb = st.selectbox("Nível de confiança do critério z (%)", niveis, index=niveis.index(97.5),
                                format_func=lambda n: f"{n:g} (z = {NIVEIS_CONFIANCA_K[n]:.3f})",
                                disabled=criterio_eb != "z")
    with aba_config["kde"]:
        c1, c2, c3 = st.columns(3)
        banda = c1.number_input("Largura de banda (m)", min_value=100, max_value=10000, value=1000, step=100)
        celula = c2.number_input("Tamanho da célula (m)", min_value=50, max_value=5000, value=500, step=50)
        percentil = c3.number_input("Percentil de corte", min_value=50, max_value=99, value=75, step=1)

opcoes = {"pesos": [peso_sv, peso_cv, peso_co], "vc": [metodo_vc, nivel_vc, sinal_vc, excluir_zeros],
          "eb": [metodo_eb, criterio_eb, nivel_eb], "kde": [banda, celula, percentil]}

st.header("Registros Inseridos")
dados = st.session_state.dados
if dados is None or dados.empty:
    st.info("ℹ️ Nenhum registro inserido.")
    st.stop()

st.dataframe(dados, width="stretch", hide_index=True)
sig = assinatura(dados, opcoes)

if st.button("🚀 Executar Análises", type="primary", width="stretch"):
    limpar_resultados()
    with st.spinner("Calculando..."):
        df_proc = preparar_dados(dados, peso_sv, peso_cv, peso_co)
        tarefas = {
            "vc": lambda: aplicar_valor_critico(df_proc, nivel_confianca=nivel_vc, metodo=metodo_vc,
                                                sinal_correcao=sinal_vc, incluir_sem_sinistros=not excluir_zeros),
            "kde": lambda: aplicar_kernel(df_proc, bandwidth=float(banda), cell_size=float(celula),
                                          percentil=float(percentil)),
            "bayes": lambda: aplicar_bayes(df_proc, metodo=metodo_eb, criterio=criterio_eb,
                                           nivel_confianca=nivel_eb),
        }
        for chave, tarefa in tarefas.items():
            try:
                res = tarefa()
                st.session_state.resultados[chave] = res
                st.session_state.avisos[chave] = res.attrs.get("avisos", [])
            except ValueError as e:
                st.session_state.erros[chave] = str(e) + dica_erro(str(e), dados)
            except Exception as e:  # noqa: BLE001
                st.session_state.erros[chave] = f"Erro inesperado ({type(e).__name__}): {e}"
                traceback.print_exc()
        st.session_state.update(df_proc=df_proc, assinatura=sig)

# --- 5. RESULTADOS ---
if st.session_state.assinatura and st.session_state.assinatura != sig:
    st.info("Os dados ou as configurações mudaram desde a última execução. "
            "Clique em **Executar Análises** para atualizar os resultados.")
elif st.session_state.assinatura == sig:
    st.subheader("📊 Resultados das Análises")
    resultados = st.session_state.resultados
    abas = st.tabs([rotulo_trilha(c) for c in ORDEM_TRILHAS])
    for chave, aba in zip(ORDEM_TRILHAS, abas):
        with aba:
            if chave in st.session_state.erros:
                st.warning(st.session_state.erros[chave])
                continue
            res = resultados[chave]
            for aviso in st.session_state.avisos.get(chave, []):
                st.caption(f"⚠️ {aviso}")
            st.metric("Segmentos críticos", f"{int(res['Critico'].sum())} de {len(res)}")
            if chave == "vc":
                geo = para_mapa(res.merge(dados[["segmento_id", "latitude", "longitude"]], on="segmento_id",
                                          how="left"))
                st.markdown("##### Mapa: críticos em vermelho")
                mostrar_mapa(chave, lambda g=geo: mapa_criticos(g, "Indice", "Índice observado"))
            elif chave == "bayes":
                geo = para_mapa(res)
                st.markdown("##### Mapa: críticos em vermelho")
                mostrar_mapa(chave, lambda g=geo: mapa_criticos(g, "ajustado", "UPS esperada (EB)"))
            else:
                geo = para_mapa(res)
                st.markdown("##### Mapa: quartis de densidade (vermelho = quartil superior, crítico)")
                mostrar_mapa(chave, lambda g=geo: mapa_kde(g))
            tabela = res.drop(columns=["x_proj", "y_proj", "peso"], errors="ignore")
            if "rodovia" in dados and "rodovia" not in tabela:    # ex.: "BR-040/DF, km 10,0 a 11,0"
                tabela = tabela.merge(dados[["segmento_id", "rodovia"]].drop_duplicates("segmento_id"),
                                      on="segmento_id", how="left")
                tabela.insert(1, "rodovia", tabela.pop("rodovia"))
            st.dataframe(tabela, width="stretch", hide_index=True)

    if resultados:
        st.markdown("---")
        st.subheader("📄 Relatório Técnico Automatizado")
        st.warning("⚠️ **Nota de Responsabilidade:** Este relatório é processado automaticamente e não "
                   "substitui a análise técnica.")
        if st.session_state.pdf_assinatura != sig:
            with st.spinner("Gerando relatório..."):    # gerado uma vez por execução, não a cada clique
                st.session_state.pdf = gerar_pdf_completo(st.session_state.df_proc, resultados, LOGO)
                st.session_state.xlsx = resultados_planilha(resultados)
                st.session_state.pdf_assinatura = sig
        c1, c2 = st.columns(2)
        c1.download_button("📥 Baixar Relatório PDF", data=st.session_state.pdf, type="primary",
                           file_name="relatorio_tecnico_seguranca_viaria.pdf", mime="application/pdf",
                           on_click="ignore", width="stretch")
        dados_planilha, nome_planilha, mime_planilha = st.session_state.xlsx
        c2.download_button("📊 Baixar resultados (planilha)", data=dados_planilha, file_name=nome_planilha,
                           mime=mime_planilha, on_click="ignore", width="stretch")
