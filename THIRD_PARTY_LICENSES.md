# Componentes de terceiros

Levantamento feito em 19/10/2026 com as versões do `requirements.txt`.

## Bibliotecas Python

| Pacote | Versão | Licença | Uso |
| --- | --- | --- | --- |
| streamlit | 1.66.0 | Apache-2.0 | interface web |
| pandas | 3.0.6 | BSD-3-Clause | tabelas |
| numpy | 2.5.4 | BSD-3-Clause (com partes 0BSD, MIT, Zlib e CC0-1.0) | cálculo |
| scipy | 1.18.1 | BSD-3-Clause | KD-tree (Trilha 2), Normal padrão |
| statsmodels | 0.15.0 | BSD-3-Clause | Binomial Negativa (Trilha 3) |
| folium | 0.20.0 | MIT | mapas |
| matplotlib | 3.11.2 | Matplotlib License (baseada na PSF, compatível com BSD) | gráfico do PDF |
| fpdf2 | 2.8.9 | LGPL-3.0-only | relatório PDF (usada como biblioteca, sem modificação) |
| xlsxwriter | 3.2.9 | BSD-2-Clause | exportação Excel |
| openpyxl | 3.1.5 | MIT | leitura de .xlsx |
| shapely | 2.2.0 | BSD-3-Clause (os pacotes binários incluem a GEOS, LGPL-2.1) | geometria da segmentação |
| pyproj | 3.8.0 | MIT (inclui a PROJ, MIT) | conversão de coordenadas |
| pyogrio | 0.13.0 | MIT (inclui a GDAL, MIT, e bibliotecas de licença permissiva) | leitura do SNV e do OpenStreetMap |

Dependências indiretas relevantes: fonttools (MIT), Pillow (MIT-CMU), defusedxml (PSF), Jinja2 e
branca (BSD/MIT), pyarrow (Apache-2.0), protobuf (BSD-3-Clause), certifi (MPL-2.0).

A v4 listava também scikit-learn, geopandas, seaborn, streamlit-folium, numexpr e pyFFTW, que não eram
importados. O pyFFTW foi retirado também por embutir o FFTW, distribuído sob GPL.

## Componentes carregados pelo navegador (via folium, por CDN)

| Componente | Licença |
| --- | --- |
| Leaflet 1.9.3 | BSD-2-Clause |
| Leaflet.heat (versão incluída no folium) | BSD-2-Clause |
| jQuery 3.7.1 | MIT |
| Bootstrap 5.2.2 e Glyphicons do Bootstrap 3 | MIT |
| Font Awesome Free 6.2.0 | ícones CC BY 4.0, fontes SIL OFL 1.1, código MIT |
| Leaflet.awesome-markers 2.0.2 | MIT |

## Dados usados na segmentação

O SNV (DNIT), os sinistros por ocorrência (PRF) e a modelagem de VMD do PNCT (DNIT) são dados públicos
enviados pelo usuário a cada uso; o repositório não os distribui.

As vias fora do SNV vêm de arquivos do OpenStreetMap enviados pelo usuário (ex.: extratos regionais da
Geofabrik). Os dados são © colaboradores do OpenStreetMap e estão sob a Open Database License (ODbL 1.0,
https://www.openstreetmap.org/copyright). A ODbL pede atribuição em tudo o que for produzido a partir deles:
o app mostra “© colaboradores do OpenStreetMap (ODbL)” ao lado dos resultados e o relatório PDF cita a
fonte. Quem publicar a planilha de segmentos com vias do OpenStreetMap (coluna `fonte`) deve citar o
OpenStreetMap e seguir as regras da ODbL para bancos de dados derivados.

## Mapa de fundo

Tiles do OpenStreetMap (dados © colaboradores do OpenStreetMap, ODbL). A atribuição aparece no mapa.
A política de uso dos tiles (https://operations.osmfoundation.org/policies/tiles/) proíbe uso pesado e
não garante disponibilidade; em produção institucional, prefira um provedor de tiles próprio ou contratado.

## Fonte

Roboto 3.009, © 2011 The Roboto Project Authors, SIL Open Font License 1.1 (`static/fonts/OFL.txt`).
A fonte é servida pelo próprio app; não há chamada ao Google Fonts.
