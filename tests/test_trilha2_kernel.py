import numpy as np
import pandas as pd
import pytest

from models.trilha2_kernel import aplicar_kernel, densidade_kde, projetar_mercator


def kde_referencia(x, y, w, bandwidth=1000.0, cell_size=500.0):
    """Algoritmo da v4 / código R do Manual: densidade em toda a grade + célula mais próxima."""
    x_coords = np.arange(x.min() - bandwidth, x.max() + bandwidth, cell_size)
    y_coords = np.arange(y.min() - bandwidth, y.max() + bandwidth, cell_size)
    gx, gy = np.meshgrid(x_coords + cell_size / 2, y_coords + cell_size / 2)
    grade = np.column_stack([gx.ravel(), gy.ravel()])
    pts = np.column_stack([x, y])
    dens = np.zeros(len(grade))
    for i, g in enumerate(grade):
        d = np.sqrt(((pts - g) ** 2).sum(axis=1))
        m = d <= 3 * bandwidth
        dens[i] = np.sum(w[m] * np.exp(-0.5 * (d[m] / bandwidth) ** 2)) / (len(pts) * 2 * np.pi * bandwidth ** 2)
    prox = np.argmin(((pts[:, None, :] - grade[None, :, :]) ** 2).sum(axis=2), axis=1)
    return dens[prox]


@pytest.mark.parametrize("semente", [1, 2, 3])
def test_igual_ao_algoritmo_da_v4(semente):
    rng = np.random.default_rng(semente)
    lat = -15.8 + rng.normal(0, 0.05, 120)
    lon = -47.9 + rng.normal(0, 0.05, 120)
    w = rng.integers(0, 60, 120).astype(float)
    x, y = projetar_mercator(lat, lon)
    np.testing.assert_allclose(densidade_kde(x, y, w), kde_referencia(x, y, w), rtol=1e-12, atol=0)


def _df(n=40, semente=0):
    rng = np.random.default_rng(semente)
    return pd.DataFrame({"segmento_id": [f"s{i}" for i in range(n)],
                         "latitude": -15.8 + rng.normal(0, 0.03, n), "longitude": -47.9 + rng.normal(0, 0.03, n),
                         "sem_vitima": rng.integers(0, 5, n), "com_vitima": rng.integers(0, 3, n),
                         "com_obito": rng.integers(0, 2, n)})


def test_usa_os_pesos_da_interface():
    d = _df()
    d["UPS"] = d.sem_vitima * 1 + d.com_vitima * 4 + d.com_obito * 28
    a = aplicar_kernel(d).set_index("segmento_id")["densidade"]
    d["UPS"] = d.sem_vitima * 1 + d.com_vitima * 4 + d.com_obito * 100
    b = aplicar_kernel(d).set_index("segmento_id")["densidade"]
    assert not np.allclose(a, b.reindex(a.index))                       # na v4 o resultado não mudava


def test_quartil_superior_e_segmentos_sem_coordenada():
    d = _df()
    d["UPS"] = d.sem_vitima + 4 * d.com_vitima + 28 * d.com_obito
    d.loc[[0, 1], ["latitude", "longitude"]] = np.nan
    res = aplicar_kernel(d)
    validos = res["densidade"].dropna()
    assert res["Critico"].sum() == (validos >= np.percentile(validos, 75)).sum()
    assert 9 <= res["Critico"].sum() <= 12
    assert res.loc[res["segmento_id"].isin(["s0", "s1"]), "Critico"].eq(False).all()
    assert res["indice_densidade"].max() == pytest.approx(100)
    assert any("sem coordenadas" in a for a in res.attrs["avisos"])


def test_sem_coordenadas_da_erro_claro():
    d = _df(5)
    d["latitude"] = np.nan
    with pytest.raises(ValueError, match="latitude e longitude"):
        aplicar_kernel(d)


def test_maioria_sem_sinistros_por_perto():
    """Com mais de 75% dos segmentos longe de qualquer sinistro, o limite é zero: só a densidade positiva conta."""
    d = _df(10)
    d["UPS"] = d.sem_vitima + 4 * d.com_vitima + 28 * d.com_obito + 1
    longe = pd.DataFrame({"segmento_id": [f"z{i}" for i in range(60)], "latitude": -16.5 + 0.02 * np.arange(60),
                          "longitude": -48.5, "sem_vitima": 0, "com_vitima": 0, "com_obito": 0, "UPS": 0})
    res = aplicar_kernel(pd.concat([d, longe], ignore_index=True))
    assert res.attrs["limite"] == 0
    assert set(res.loc[res["Critico"], "segmento_id"]) == set(d["segmento_id"])
    assert any("densidade zero" in a for a in res.attrs["avisos"])
