"""Segmentação automática com um SNV sintético (linhas retas em Brasília, ~107 km por grau de longitude)."""
import numpy as np
import pandas as pd
import pytest
import shapely

from utils import segmentacao as sg

LAT = -15.70
GRAU_KM = 107.1   # km por grau de longitude nessa latitude (aprox.)


def linha(lon0, lat, km):
    return shapely.LineString([(lon0, lat), (lon0 + km / GRAU_KM, lat)])


def snv_sintetico(coincidente_invertido=False):
    a = linha(-47.90, LAT, 2.4)
    b = shapely.reverse(a) if coincidente_invertido else a
    trechos = [
        # código, br, tipo, coinc, lista de coincidência, km ini, km fim, superfície, geometria
        ("010BDF0010", "010", "B", "-", "010BDF0010;020BDF0010", 0.0, 2.4, "DUP", a),
        ("020BDF0010", "020", "B", "Coinc", "010BDF0010;020BDF0010", 10.0, 12.4, "DUP", b),
        ("010CDF0012", "010", "C", "-", "010CDF0012", 0.0, 2.4, "PAV", linha(-47.90, LAT + 0.01, 2.4)),
        ("010BDF0050", "010", "B", "-", "010BDF0050", 2.4, 5.0, "PLA", linha(-47.90 + 2.4 / GRAU_KM, LAT, 2.6)),
    ]
    df = pd.DataFrame(trechos, columns=["vl_codigo", "vl_br", "sg_tipo_tr", "desc_coinc", "ds_coinc", "vl_km_inic",
                                        "vl_km_fina", "ds_sup_fed", "geometry"])
    df["sg_uf"] = "DF"
    df["versao_snv"] = "TESTE"
    return sg.preparar_snv(df)


def sinistros(linhas):
    """linhas: (br, km, lat, lon, gravidade, ano, sentido)."""
    df = pd.DataFrame(linhas, columns=["br", "km", "latitude", "longitude", "gravidade", "ano", "sentido"])
    df["uf"] = "DF"
    return df


@pytest.mark.parametrize("ext, fundir, esperado", [
    (2.4, True, [0, 1, 2.4]),
    (2.4, False, [0, 1, 2, 2.4]),
    (2.5, True, [0, 1, 2, 2.5]),      # sobra de meio segmento fica separada
    (0.6, True, [0, 0.6]),
    (3.0, True, [0, 1, 2, 3]),
])
def test_cortes_do_trecho(ext, fundir, esperado):
    assert sg.cortes_do_trecho(ext, 1.0, fundir_resto=fundir) == pytest.approx(esperado)


def test_segmentos_so_na_malha_fisica_e_sem_coincidentes():
    seg = sg.cortar_segmentos(snv_sintetico())
    assert set(seg["codigo_snv"]) == {"010BDF0010", "010CDF0012"}      # sem planejado e sem coincidente
    a = seg[seg["codigo_snv"] == "010BDF0010"]
    assert list(a["segmento_id"]) == ["010BDF0010-001", "010BDF0010-002"]
    assert list(a["km_final"]) == pytest.approx([1.0, 2.4])
    assert a["extensao_trecho"].sum() == pytest.approx(2.4)
    assert a["rodovia"].iloc[1] == "BR-010/DF, km 1,0 a 2,4"
    assert np.allclose(a["latitude"], LAT, atol=1e-6)


def test_comprimento_fora_dos_limites():
    with pytest.raises(ValueError, match="entre"):
        sg.cortar_segmentos(snv_sintetico(), comprimento=0.05)


def test_coincidente_vai_ao_principal_pela_fracao():
    snv = snv_sintetico()
    loc = sg.localizar_sinistros(sinistros([("020", 10.6, np.nan, np.nan, "sem_vitima", 2023, None)]), snv, "km")
    assert loc.loc[0, "codigo_snv"] == "010BDF0010"
    assert loc.loc[0, "km_snv"] == pytest.approx(0.6)                  # 25% do trecho


def test_coincidente_digitalizado_ao_contrario():
    snv = snv_sintetico(coincidente_invertido=True)
    assert bool(snv.set_index("vl_codigo").loc["020BDF0010", "invertido"])
    loc = sg.localizar_sinistros(sinistros([("020", 10.6, np.nan, np.nan, "sem_vitima", 2023, None)]), snv, "km")
    assert loc.loc[0, "km_snv"] == pytest.approx(1.8)                  # 25% no sentido oposto


def test_coordenada_decide_entre_eixo_e_contorno():
    snv = snv_sintetico()
    meio = -47.90 + 1.2 / GRAU_KM
    s = sinistros([
        ("010", 1.2, LAT + 0.01, meio, "com_vitima", 2023, None),     # no contorno
        ("010", 1.2, np.nan, np.nan, "com_vitima", 2023, None),       # sem coordenada: eixo principal
        ("010", 1.2, LAT - 0.05, meio, "com_vitima", 2023, None),     # coordenada longe: vale o km
        ("010", 3.0, np.nan, np.nan, "com_vitima", 2023, None),       # trecho planejado
        ("116", 3.0, np.nan, np.nan, "com_vitima", 2023, None),       # BR fora do SNV da UF
    ])
    loc = sg.localizar_sinistros(s, snv)
    assert list(loc["codigo_snv"].fillna("")) == ["010CDF0012", "010BDF0010", "010BDF0010", "010BDF0050", ""]
    assert list(loc["situacao"]) == [sg.LOCALIZADO_COORD, sg.LOCALIZADO_KM, sg.LOCALIZADO_KM,
                                     sg.SEM_PISTA, "sem trecho no SNV para a BR e o km"]


def test_modo_coordenada_ignora_br():
    snv = snv_sintetico()
    s = sinistros([(None, np.nan, LAT + 0.0005, -47.90 + 0.5 / GRAU_KM, "sem_vitima", 2023, None)])
    loc = sg.localizar_sinistros(s, snv, metodo="coordenada")
    assert loc.loc[0, "codigo_snv"] == "010BDF0010"
    assert loc.loc[0, "km_snv"] == pytest.approx(0.5, abs=0.02)


def test_agregacao_conta_por_segmento_e_sentido():
    snv = snv_sintetico()
    s = sinistros([
        ("010", 0.2, np.nan, np.nan, "sem_vitima", 2022, "Crescente"),
        ("010", 0.7, np.nan, np.nan, "com_obito", 2023, "Decrescente"),
        ("010", 2.3, np.nan, np.nan, "com_vitima", 2023, "Crescente"),
        ("020", 12.0, np.nan, np.nan, "com_vitima", 2023, None),         # coincidente, sem sentido
    ])
    seg = sg.cortar_segmentos(snv)
    loc = sg.localizar_sinistros(s, snv)
    dados = sg.agregar_por_segmento(loc, seg)
    d = dados.set_index("segmento_id")
    assert d.loc["010BDF0010-001", ["sem_vitima", "com_vitima", "com_obito"]].tolist() == [1, 0, 1]
    assert d.loc["010BDF0010-002", ["sem_vitima", "com_vitima", "com_obito"]].tolist() == [0, 2, 0]
    assert d.loc["010CDF0012-001", ["sem_vitima", "com_vitima", "com_obito"]].sum() == 0
    assert (dados["n_anos"] == 2).all()
    por_sentido = sg.agregar_por_segmento(loc, seg, por_sentido=True)
    assert len(por_sentido) == 2 * len(seg)
    assert por_sentido.attrs["resumo"]["sem_sentido"] == 1
    assert por_sentido.set_index("segmento_id").loc["010BDF0010-001-D", "com_obito"] == 1


def test_leitura_da_prf():
    bruto = pd.DataFrame({
        "id": ["1", "2", "3", "4"],
        "data_inversa": ["2023-01-01", "2023-05-02", "2022-12-31", "2021-07-04"],
        "uf": ["DF", "df", "MG", "PE"],
        "br": ["20", "040", "381.0", "101"],
        "km": ["11,2", "3", "456,7", "10"],
        "classificacao_acidente": ["Com Vítimas Fatais", "Sem Vítimas", None, None],
        "mortos": ["1", "0", "2", "0"],
        "feridos": ["0", "0", "0", "3"],
        "sentido_via": ["Crescente", "Decrescente", "Não Informado", "Crescente"],
        "latitude": ["-15,7", "-15,8", "10,0", "-8,1"],
        "longitude": ["-47,9", "-47,9", "-44,0", "-35,0"],
    })
    p = sg.ler_sinistros_prf(bruto)
    assert list(p["br"]) == ["020", "040", "381", "101"]
    assert list(p["uf"]) == ["DF", "DF", "MG", "PE"]
    assert p["km"].tolist() == pytest.approx([11.2, 3.0, 456.7, 10.0])
    assert list(p["gravidade"]) == ["com_obito", "sem_vitima", "com_obito", "com_vitima"]
    assert list(p["ano"]) == [2023, 2023, 2022, 2021]
    assert (p.loc[0, "sentido"], p.loc[1, "sentido"]) == ("Crescente", "Decrescente")
    assert pd.isna(p.loc[2, "sentido"])
    assert pd.isna(p.loc[2, "latitude"])                                 # fora do Brasil


def test_leitura_dos_arquivos_enviados(tmp_path):
    """SNV como shapefile (partes soltas ou .zip) e PRF como .zip com CSV em latin-1."""
    import io
    import zipfile

    from pyogrio.raw import write

    snv = snv_sintetico()
    campos = ["vl_codigo", "vl_br", "sg_uf", "sg_tipo_tr", "desc_coinc", "ds_coinc", "vl_km_inic", "vl_km_fina",
              "ds_sup_fed", "versao_snv"]
    dados_campos = [snv[c].astype(str).to_numpy() if c not in ("vl_km_inic", "vl_km_fina")
                    else snv[c].to_numpy(float) for c in campos]
    write(str(tmp_path / "snv.shp"), shapely.to_wkb(snv["geometry"].to_numpy()), dados_campos, campos,
          geometry_type="LineString", crs="EPSG:4674", driver="ESRI Shapefile")
    partes = [(p.name, p.read_bytes()) for p in tmp_path.iterdir()]
    lido = sg.preparar_snv(sg.ler_snv_enviado(partes))
    assert set(lido["vl_codigo"]) == set(snv["vl_codigo"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in partes:
            z.writestr(nome, conteudo)
    assert len(sg.ler_snv_enviado([("snv.zip", buf.getvalue())])) == len(snv)
    with pytest.raises(ValueError, match="dbf"):
        sg.ler_snv_enviado([p for p in partes if not p[0].endswith(".dbf")])

    csv = ("id;data_inversa;uf;br;km;classificacao_acidente;latitude;longitude\n"
           "1;2023-02-01;DF;20;11,2;Sem Vítimas;-15,7;-47,9\n")
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("datatran2023.csv", csv.encode("latin-1"))
    prf = sg.ler_arquivos_prf([("datatran2023.zip", zbuf.getvalue())])
    assert prf.loc[0, "br"] == "020" and prf.loc[0, "gravidade"] == "sem_vitima"


def test_arquivo_por_pessoa_conta_cada_ocorrencia_uma_vez():
    bruto = pd.DataFrame({
        "id": ["10", "10", "10", "11"], "pesid": ["1", "2", "3", "4"],
        "data_inversa": ["2025-01-01"] * 4, "uf": ["SP"] * 4, "br": ["116"] * 4, "km": ["10"] * 4,
        "classificacao_acidente": ["Com Vítimas Feridas"] * 3 + ["Sem Vítimas"],
    })
    p = sg.ler_sinistros_prf(bruto)
    assert len(p) == 2
    assert p.attrs["linhas_repetidas"] == 2
