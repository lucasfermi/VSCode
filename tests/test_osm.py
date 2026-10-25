"""Vias do OpenStreetMap fora do SNV e sinistros só com coordenada (dados sintéticos em Brasília)."""
import numpy as np
import pandas as pd
import pytest
import shapely
from pyogrio.raw import write

from test_segmentacao import GRAU_KM, LAT, snv_sintetico
from utils import osm
from utils import segmentacao as sg

GRAU_LAT_KM = 110.6   # km por grau de latitude (aprox.)


def via(lon0, lat, km, para_norte=False):
    fim = (lon0, lat + km / GRAU_LAT_KM) if para_norte else (lon0 + km / GRAU_KM, lat)
    return shapely.LineString([(lon0, lat), fim])


def vias_sinteticas(caminho):
    """Avenida em dois pedaços, a mesma avenida com pista paralela a 20 m, uma rua, a BR-010 no OSM e uma
    via colada no eixo do SNV."""
    x0 = -47.95
    linhas = [
        ("1", "Avenida Um", "primary", None, via(x0, LAT - 0.03, 1.5)),
        ("2", "Avenida Um", "primary", None, via(x0 + 1.5 / GRAU_KM, LAT - 0.03, 1.2)),
        ("3", "Avenida Um", "primary", None, via(x0, LAT - 0.03 + 0.02 / GRAU_LAT_KM, 2.7)),
        ("4", "Rua Dois", "residential", None, via(x0, LAT - 0.05, 0.8, para_norte=True)),
        ("5", None, "trunk", '"ref"=>"BR-010"', via(x0, LAT - 0.08, 2.0)),
        ("6", "Marginal", "secondary", None, via(-47.90, LAT + 0.0001, 2.0)),   # a ~10 m do SNV
    ]
    df = pd.DataFrame(linhas, columns=["osm_id", "name", "highway", "other_tags", "geometry"])
    campos = ["osm_id", "name", "highway", "other_tags"]
    write(str(caminho), shapely.to_wkb(df["geometry"].to_numpy()), [df[c].to_numpy(object) for c in campos], campos,
          geometry_type="LineString", crs="EPSG:4326", driver="GeoJSON")
    return caminho


def test_vias_do_osm_fora_do_snv(tmp_path):
    arq = vias_sinteticas(tmp_path / "vias.geojson")
    lidas = osm.ler_vias_osm(str(arq), classes=osm.CLASSES_PRINCIPAIS + osm.CLASSES_URBANAS)
    assert len(lidas) == 6
    assert bool(lidas.set_index("osm_id").loc["5", "federal"])
    vias = osm.montar_vias(lidas, snv_sintetico())
    # avenida: dois pedaços viram uma via de 2,7 km; a pista paralela some; BR-010 e marginal ficam com o SNV
    assert sorted(vias["chave"]) == ["AVENIDA UM", "RUA DOIS"]
    avenida = vias[vias["chave"] == "AVENIDA UM"].iloc[0]
    assert avenida["comprimento_m"] == pytest.approx(2700, rel=0.02)
    seg = osm.cortar_vias(vias, 1.0)
    assert seg[seg["codigo_via"] == avenida["codigo_via"]]["extensao_trecho"].sum() == pytest.approx(2.7, rel=0.02)
    assert seg["rodovia"].str.contains("Avenida Um, km 0,0 a 1,0 da via").any()


def test_sinistros_presos_a_via_mais_proxima(tmp_path):
    vias = osm.montar_vias(osm.ler_vias_osm(str(vias_sinteticas(tmp_path / "v.geojson")),
                                            classes=osm.CLASSES_PRINCIPAIS), snv_sintetico())
    seg = osm.cortar_vias(vias, 1.0)
    x0 = -47.95
    s = pd.DataFrame({"latitude": [LAT - 0.03 + 0.0002, LAT - 0.03 + 0.01, np.nan],
                      "longitude": [x0 + 0.5 / GRAU_KM, x0 + 0.5 / GRAU_KM, x0],
                      "gravidade": ["com_vitima", "com_vitima", "sem_vitima"]})
    dados, atribuidos = osm.agregar_osm(s, seg, 3)
    assert list(atribuidos) == [0]                      # o 2º está a ~1 km; o 3º não tem coordenada
    assert dados["com_vitima"].sum() == 1
    assert (dados["fonte"] == "OpenStreetMap").all()


def test_planilha_so_com_coordenada():
    bruto = pd.DataFrame({"id": [1, 2, 3, 4], "ano": [2023, 2023, 2024, 2024],
                          "latitude": [-15.70, -15.71, 236392064.0, -15.72], "longitude": [-47.9, -47.9, -47.9, -47.9],
                          "com_vitima": [0, 2, 1, 0], "com_obito": [1, 0, 0, 0]})
    s = sg.ler_sinistros_pontuais(bruto)
    assert list(s["gravidade"]) == ["com_obito", "com_vitima", "com_vitima", "sem_vitima"]
    assert s.attrs["sem_coordenada"] == 1 and pd.isna(s.loc[2, "latitude"])
    texto = sg.ler_sinistros_pontuais(pd.DataFrame({"lat": [-15.7], "lon": [-47.9], "data": ["05/03/2024"],
                                                    "gravidade": ["Com vítimas fatais"]}))
    assert texto.loc[0, "gravidade"] == "com_obito" and texto.loc[0, "ano"] == 2024
    with pytest.raises(ValueError, match="latitude"):
        sg.ler_sinistros_pontuais(pd.DataFrame({"x": [1], "ano": [2023]}))
    with pytest.raises(ValueError, match="ano"):
        sg.ler_sinistros_pontuais(pd.DataFrame({"latitude": [-15.7], "longitude": [-47.9]}))


def test_segmentacao_com_snv_e_osm(tmp_path):
    snv = snv_sintetico()
    lidas = osm.ler_vias_osm(str(vias_sinteticas(tmp_path / "v.geojson")), classes=osm.CLASSES_PRINCIPAIS)
    x0 = -47.95
    s = sg.ler_sinistros_pontuais(pd.DataFrame({
        "ano": [2023, 2023, 2023],
        "latitude": [LAT + 0.0003, LAT - 0.03 + 0.0002, LAT - 0.2],              # SNV, avenida, longe de tudo
        "longitude": [-47.90 + 1.0 / GRAU_KM, x0 + 0.5 / GRAU_KM, x0],
        "com_vitima": [1, 1, 1], "com_obito": [0, 0, 0]}))
    dados = sg.segmentar(s, snv, ["DF"], [2023], vias_osm=lidas)
    por_fonte = dados.groupby("fonte")["com_vitima"].sum().to_dict()
    assert por_fonte == {"OpenStreetMap": 1, "SNV": 1}
    r = dados.attrs["resumo"]
    assert r["osm"]["sinistros"] == 1 and r["atribuidos"] == 2
    assert r["situacoes"][sg.LOCALIZADO_OSM] == 1


def test_relatorio_cita_as_fontes(tmp_path):
    from models.trilha1_valor_critico import aplicar_valor_critico
    from utils.preprocessamento import preparar_dados
    from utils.relatorio import _fontes, gerar_pdf_completo

    snv = snv_sintetico()
    lidas = osm.ler_vias_osm(str(vias_sinteticas(tmp_path / "v.geojson")), classes=osm.CLASSES_PRINCIPAIS)
    s = sg.ler_sinistros_pontuais(pd.DataFrame({"ano": [2023, 2023], "latitude": [LAT + 0.0003, LAT - 0.03 + 0.0002],
                                                "longitude": [-47.90 + 1.0 / GRAU_KM, -47.95 + 0.5 / GRAU_KM],
                                                "com_vitima": [1, 1], "com_obito": [0, 0]}))
    df = preparar_dados(sg.segmentar(s, snv, ["DF"], [2023], vias_osm=lidas), 1, 4, 28)
    texto = _fontes(df)
    assert "SNV do DNIT (versão TESTE)" in texto and "OpenStreetMap" in texto and "ODbL" in texto
    assert _fontes(df.drop(columns="codigo_snv")) is None
    assert gerar_pdf_completo(df, {"vc": aplicar_valor_critico(df)}).startswith(b"%PDF")


def test_sinistro_preso_a_rodovia_de_outra_uf():
    """Sem UF nos dados, o sinistro que cai numa rodovia federal de outra UF fica de fora, com o motivo."""
    snv = snv_sintetico()
    snv.loc[snv["vl_codigo"] == "010CDF0012", "sg_uf"] = "GO"      # o contorno passa a ser de Goiás
    s = sg.ler_sinistros_pontuais(pd.DataFrame({
        "ano": [2023, 2023], "latitude": [LAT + 0.0003, LAT + 0.01 + 0.0003],
        "longitude": [-47.90 + 1.0 / GRAU_KM, -47.90 + 1.0 / GRAU_KM], "com_vitima": [1, 1], "com_obito": [0, 0]}))
    r = sg.segmentar(s, snv, ["DF"], [2023]).attrs["resumo"]
    assert r["atribuidos"] == 1
    assert r["situacoes"][sg.EM_OUTRA_UF] == 1
