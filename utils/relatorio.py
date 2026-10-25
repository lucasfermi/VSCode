"""Relatório técnico em PDF (fpdf2)."""
import io
import re
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from fpdf import FPDF  # noqa: E402
from fpdf.enums import XPos, YPos  # noqa: E402

from utils.constantes import ORDEM_TRILHAS, TRILHAS, rotulo_trilha  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
PASTA_FONTES = BASE / "static" / "fonts"

COR_AZUL = (9, 136, 195)     # #0988C3
COR_VERDE = (92, 193, 4)     # #5CC104
COR_AMARELO = (255, 201, 0)  # #FFC900
COR_ROXO = (100, 96, 154)    # #64609A
COR_CINZA = (128, 128, 128)


def _br(valor, casas=1):
    """Formata número no padrão brasileiro: 1.234,5."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


class PDFRelatorio(FPDF):
    def __init__(self, logo_path=None):
        super().__init__()
        self.logo_path = logo_path
        self.set_auto_page_break(auto=True, margin=20)
        self.set_title("Relatório de Segurança Viária")
        self.fonte = "helvetica"
        regular = PASTA_FONTES / "Roboto-Regular.ttf"
        if regular.exists():
            self.add_font("Roboto", "", str(regular))
            self.add_font("Roboto", "B", str(PASTA_FONTES / "Roboto-Bold.ttf"))
            self.add_font("Roboto", "I", str(PASTA_FONTES / "Roboto-Italic.ttf"))
            self.fonte = "Roboto"

    def header(self):
        self.set_line_width(2)
        self.set_draw_color(*COR_AZUL)
        self.line(0, 5, 210, 5)
        self.set_draw_color(*COR_VERDE)
        self.line(0, 7, 150, 7)
        self.set_draw_color(*COR_AMARELO)
        self.line(0, 9, 100, 9)
        if self.logo_path and Path(self.logo_path).exists():
            self.image(str(self.logo_path), 10, 15, 40)
        self.set_y(20)
        self.set_font(self.fonte, "B", 10)
        self.set_text_color(*COR_ROXO)
        self.cell(0, 5, "SISTEMA DE DADOS RODOVIÁRIOS", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(self.fonte, "", 9)
        self.set_text_color(*COR_AZUL)
        self.cell(0, 5, "Relatório Técnico de Identificação de Segmentos Críticos", align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(20)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.fonte, "I", 8)
        self.set_text_color(*COR_CINZA)
        self.cell(0, 10, f"Página {self.page_no()} | Gerado em {datetime.now().strftime('%d/%m/%Y')}", align="C")

    def capitulo_titulo(self, label):
        if self.get_y() > self.page_break_trigger - 30:   # evita título órfão no pé da página
            self.add_page()
        self.ln(4)
        self.set_font(self.fonte, "B", 14)
        self.set_text_color(*COR_AZUL)
        self.set_fill_color(*COR_AMARELO)
        self.rect(10, self.get_y() + 2.5, 5, 5, "F")
        self.set_x(18)
        self.cell(0, 10, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def subtitulo(self, label):
        self.set_font(self.fonte, "B", 12)
        self.set_text_color(*COR_ROXO)
        self.cell(0, 8, label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def texto_corpo(self, text):
        self.set_font(self.fonte, "", 11)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(3)

    def destaque_box(self, text, tipo="info"):
        self.set_font(self.fonte, "B", 10)
        if tipo == "conclusao":
            self.set_fill_color(240, 248, 255)
            self.set_text_color(*COR_AZUL)
            self.set_draw_color(*COR_AZUL)
        else:
            self.set_fill_color(255, 250, 205)
            self.set_text_color(*COR_ROXO)
            self.set_draw_color(*COR_AMARELO)
        self.set_line_width(0.3)
        self.multi_cell(0, 7, text, border=1, align="L", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(4)

    def adicionar_tabela(self, df, larguras=None):
        if df.empty:
            return
        cols = list(df.columns)
        larguras = larguras or [190 / len(cols)] * len(cols)
        self.set_line_width(0.2)
        self.set_draw_color(180, 180, 180)
        self.set_font(self.fonte, "B", 9)
        self.set_fill_color(*COR_AZUL)
        self.set_text_color(255, 255, 255)
        for col, w in zip(cols, larguras):
            self.cell(w, 7, str(col), border=1, align="C", fill=True)
        self.ln()
        self.set_font(self.fonte, "", 8)
        self.set_text_color(0, 0, 0)
        self.set_fill_color(245, 245, 245)
        fill = False
        for _, row in df.iterrows():
            for col, w in zip(cols, larguras):
                v = row[col]
                val = _br(v, 2) if isinstance(v, float) else str(v)
                if len(val) > 28:
                    val = val[:25] + "..."
                self.cell(w, 6, val, border=1, align="C", fill=fill)
            self.ln()
            fill = not fill
        self.ln(4)

    def adicionar_grafico(self, fig):
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        self.image(buf, x=20, w=170)
        self.ln(4)


def _ordem_natural(texto):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(texto))]


def _com_rodovia(tabela, df_proc):
    """Acrescenta a coluna Rodovia (CodigoSNV) quando a planilha a trouxer."""
    if "rodovia" not in df_proc:
        return tabela
    mapa = df_proc.drop_duplicates("segmento_id").set_index("segmento_id")["rodovia"]
    tabela = tabela.copy()
    tabela.insert(1, "Rodovia", tabela["Segmento"].map(mapa).fillna("").astype(str))
    return tabela


def _resumo(df_proc, resultados):
    seg = df_proc.drop_duplicates("segmento_id")
    n_seg = len(seg)
    km = seg["extensao_trecho"].sum()
    n_anos = int(seg["n_anos"].max()) if "n_anos" in seg and seg["n_anos"].notna().any() else None
    total = seg[["sem_vitima", "com_vitima", "com_obito"]].sum().sum()
    com_obito = seg["com_obito"].sum()
    periodo = f"em {n_anos} ano(s) de dados" if n_anos else "no período informado"
    return (f"A análise avaliou {n_seg} segmentos rodoviários, com extensão total de {_br(km)} km. "
            f"Foram processados {_br(total, 0)} sinistros {periodo}, dos quais {_br(com_obito, 0)} com óbito "
            f"(peso de maior valor na UPS).")


def _fontes(df_proc):
    """Fontes da segmentação automática (SNV, VMD e OpenStreetMap), quando os dados vierem dela."""
    if "codigo_snv" not in df_proc:
        return None
    resumo = df_proc.attrs.get("resumo", {})
    partes = [f"Segmentos cortados na malha do SNV do DNIT (versão {resumo.get('versao_snv', 'não informada')})."]
    vmd = resumo.get("vmd")
    if vmd:
        partes.append(f"Volume de tráfego (VMD) da modelagem do PNCT/DNIT ({vmd.get('ano') or 'ano não informado'}, "
                      f"SNV {vmd.get('versao_snv')}).")
    if "fonte" in df_proc and (df_proc["fonte"] == "OpenStreetMap").any():
        partes.append("Vias fora do SNV: © colaboradores do OpenStreetMap, dados sob a licença ODbL "
                      "(openstreetmap.org/copyright).")
    return "Fontes: " + " ".join(partes)


def _texto_metodologia(resultados, pesos):
    from models.trilha3_bayes import CRITERIOS, METODOS

    def vc(a):
        sinal = "-0,5/m (Manual)" if a.get("sinal_correcao", -1) < 0 else "+1/(2m) (literatura clássica)"
        return (f"compara o índice de cada segmento com um limite estatístico (nível de confiança de "
                f"{_br(a.get('nivel_confianca', 95), 1)}%, k = {_br(a.get('k', 1.645), 3)}, correção {sinal}). "
                "É a triagem mais simples.")

    def kde(a):
        p = float(a.get("percentil", 75))
        corte = "no quartil superior de densidade" if p == 75 else f"acima do percentil {_br(p, 0)} da densidade"
        return (f"estima a concentração espacial da UPS (banda de {_br(a.get('bandwidth', 1000), 0)} m, células de "
                f"{_br(a.get('cell_size', 500), 0)} m). São críticos os segmentos {corte}.")

    def bayes(a):
        return ("estima o número esperado de sinistros combinando o observado com uma referência, o que reduz o "
                f"efeito da regressão à média. Método: {METODOS.get(a.get('metodo'), '')}. "
                f"Critério: {CRITERIOS.get(a.get('criterio'), '')}.")

    texto = {"vc": vc, "kde": kde, "bayes": bayes}
    partes = [("As análises seguem o Manual de Identificação de Segmentos Críticos Rodoviários (2025). "
               f"A severidade é medida pela UPS, com pesos {pesos.get('sem_vitima', 1)} (sem vítima), "
               f"{pesos.get('com_vitima', 4)} (com vítima) e {pesos.get('com_obito', 28)} (com óbito).\n")]
    for chave in ORDEM_TRILHAS:
        if chave in resultados:
            partes.append(f"- {rotulo_trilha(chave)}: {texto[chave](resultados[chave].attrs)}\n")
    return "".join(partes)


def gerar_pdf_completo(df_proc, resultados, logo_path=None):
    """Gera o PDF. ``df_proc`` é a tabela já processada (com a coluna UPS)."""
    pdf = PDFRelatorio(logo_path)
    pdf.add_page()
    pesos = df_proc.attrs.get("pesos_ups", {})

    pdf.capitulo_titulo("1. Resumo Executivo")
    pdf.texto_corpo(_resumo(df_proc, resultados))
    fontes = _fontes(df_proc)
    if fontes:
        pdf.texto_corpo(fontes)
    if "UPS" in df_proc:
        ups_seg = df_proc.groupby("segmento_id")["UPS"].sum()
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.hist(ups_seg, bins=30, color="#0988C3", alpha=0.85, edgecolor="white")
        ax.set_title("Distribuição da UPS por segmento", fontsize=10, color="#64609A", fontweight="bold")
        ax.set_xlabel("UPS no período", fontsize=8)
        ax.set_ylabel("Número de segmentos", fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        pdf.adicionar_grafico(fig)
        plt.close(fig)

    pdf.capitulo_titulo("2. Metodologia Aplicada")
    pdf.texto_corpo(_texto_metodologia(resultados, pesos))
    papel = {"vc": "é uma triagem simples",
             "kde": "mostra concentrações espaciais sem depender da segmentação",
             "bayes": "é estatisticamente mais robusta, pois considera a exposição e a regressão à média"}
    pdf.destaque_box("As trilhas são complementares (Manual, cap. 3): "
                     + "; ".join(f"a Trilha {TRILHAS[c]['numero']}, {TRILHAS[c]['nome']}, {papel[c]}"
                                 for c in ORDEM_TRILHAS) + ".", tipo="aviso")

    pdf.capitulo_titulo("3. Resultados Detalhados")
    for chave in sorted(resultados, key=lambda c: TRILHAS[c]["numero"]):
        res = resultados[chave]
        criticos = res[res["Critico"].astype(bool)]
        pdf.subtitulo(f"3.{TRILHAS[chave]['numero']}. {rotulo_trilha(chave)}")
        pdf.texto_corpo(f"{len(criticos)} de {len(res)} segmentos foram classificados como críticos. "
                        "A tabela mostra os 10 primeiros.")
        if criticos.empty:
            continue
        if chave == "vc":
            t = criticos.head(10)[["segmento_id", "Indice", "Valor_Critico"]]
            t.columns = ["Segmento", "Índice observado", "Valor crítico"]
        elif chave == "bayes":
            t = criticos.head(10)[["segmento_id", "N_observado", "ajustado", "N_previsto"]]
            t.columns = ["Segmento", "UPS observada", "UPS esperada (EB)", "Referência"]
        else:
            t = criticos.head(10)[["segmento_id", "UPS", "indice_densidade"]]
            t.columns = ["Segmento", "UPS", "Índice de densidade (0-100)"]
        t = _com_rodovia(t.astype({c: float for c in t.columns[1:]}), df_proc)
        pdf.adicionar_tabela(t)

    pdf.capitulo_titulo("4. Análise Comparativa")
    conjuntos = {c: set(r.loc[r["Critico"].astype(bool), "segmento_id"].astype(str)) for c, r in resultados.items()}
    if len(conjuntos) > 1:
        linhas = []
        chaves = sorted(conjuntos, key=lambda c: TRILHAS[c]["numero"])
        for i, a in enumerate(chaves):
            for b in chaves[i + 1:]:
                linhas.append({"Trilhas": f"{TRILHAS[a]['numero']} e {TRILHAS[b]['numero']}",
                               "Críticos em ambas": float(len(conjuntos[a] & conjuntos[b]))})
        pdf.adicionar_tabela(pd.DataFrame(linhas).astype({"Críticos em ambas": int}).astype(str), [95, 95])
        todos = set.intersection(*conjuntos.values())
        if todos:
            lista = ", ".join(sorted(todos, key=_ordem_natural)[:60]) + (" ..." if len(todos) > 60 else "")
            pdf.texto_corpo(f"{len(todos)} segmento(s) foram apontados por todas as trilhas executadas. "
                            "São candidatos naturais à inspeção técnica prioritária:")
            pdf.destaque_box(lista, tipo="conclusao")
        else:
            pdf.texto_corpo("Nenhum segmento foi apontado por todas as trilhas. Isso é comum, porque cada método "
                            "mede um aspecto diferente (limite estatístico, valor esperado ou concentração espacial).")
    pdf.destaque_box("Nota de responsabilidade: relatório gerado automaticamente a partir dos dados inseridos. "
                     "Não substitui a análise técnica nem os estudos de engenharia necessários às intervenções.")
    return bytes(pdf.output())
