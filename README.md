# Análise de Segmentos Críticos por Sinistros

Aplicação web (Streamlit) que identifica segmentos rodoviários críticos a partir de dados de sinistros,
seguindo o **Manual de Identificação de Segmentos Críticos Rodoviários (2025)**. Desenvolvida no projeto
“Aprimorando os Sistemas de Dados Rodoviários no Brasil para Prevenção de Sinistros”, coordenado pela
OPAS/OMS no Brasil e financiado pelo Fundo das Nações Unidas para a Segurança Viária (UNRSF), com a
Universidade de Brasília.

## Métodos

| Trilha | Método | Dados necessários |
| --- | --- | --- |
| 1 | Valor Crítico: número de sinistros, severidade (UPS), taxa de sinistros e taxa de severidade (Manual, item 3.1) | sinistros e extensão; VMD para os métodos de taxa |
| 2 | Densidade de Kernel (KDE), banda de 1 km, células de 500 m, quartil superior (Manual, item 3.3) | sinistros e coordenadas |
| 3 | Empírico de Bayes: Média Global por tipo de sinistro (Manual, item 3.2; Marshall, 1991); opções: Binomial Negativa por tipo de sinistro (Hauer/HSM) e o procedimento da v4 | sinistros, extensão e VMD |

A numeração é a adotada a partir da v4. O Manual de 2025 e o Manual de Utilização usam a ordem antiga
(Bayes como Trilha 2 e KDE como Trilha 3). A numeração exibida fica em `utils/constantes.py`.

A severidade usa a Unidade Padrão de Severidade: `UPS = 1 × sem vítima + 4 × com vítima + 28 × com óbito`
(pesos ajustáveis na interface).

## Como executar

Requer Python 3.13. Use um ambiente virtual só para esta versão: o pacote `fpdf` antigo, usado até a v4,
conflita com o `fpdf2` (erro `No module named 'fpdf.enums'`). Se o ambiente estiver errado, o app mostra
os comandos abaixo em vez do erro.

Windows (cmd ou PowerShell), na pasta do projeto:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

Linux ou macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

No VS Code, selecione o interpretador `.venv` (Ctrl+Shift+P → “Python: Select Interpreter”).

Para hospedar o app (Streamlit Community Cloud ou servidor próprio com Docker), veja `docs/IMPLANTACAO.md`.

Testes: instale `requirements-dev.txt` no mesmo ambiente e rode `python -m pytest`. Os testes da Trilha 1
reproduzem os exemplos resolvidos do Manual (Tabelas 5.1 a 5.5).

## Segmentação automática

Em vez de uma planilha já segmentada, o app aceita os sinistros por ocorrência e o SNV do DNIT, corta a
malha em segmentos e conta os sinistros de cada um (barra lateral, “Opção 2”).

1. **Sinistros:** dados abertos da PRF (arquivos `datatranAAAA`, em .csv ou no .zip original; os arquivos
   “por pessoa” também servem, e cada ocorrência conta uma vez) ou qualquer planilha com latitude,
   longitude e ano (ou data). A gravidade vem de uma coluna de texto ou das contagens (`com_obito` ou
   `mortos` maior que zero = com óbito; `com_vitima` ou `feridos` = com vítima). Podem ir vários arquivos
   de uma vez.
2. **SNV:** publicação do DNIT (ex.: `pub_202610A.zip`). O shapefile vem num .rar dentro do .zip: extraia e
   envie os arquivos `.shp`, `.shx`, `.dbf` e `.prj` juntos, ou compactados num .zip.
3. **VMD (opcional):** planilha de modelagem do PNCT/DNIT (ex.: `VDM_Modelagem_2019_SNV_202001A`).
4. **OpenStreetMap (opcional):** arquivo regional `.osm.pbf` da Geofabrik (download.geofabrik.de), para as
   vias que o SNV não cobre.
5. Escolha a UF, os anos e o comprimento do segmento (1 km por padrão; de 0,1 a 10 km).

Cada trecho do SNV com pista é dividido em segmentos que não atravessam o limite do trecho; uma sobra menor
que meio segmento se junta ao segmento anterior. O ID segue o código do SNV (`010BDF0010-002` é o 2º
segmento do trecho) e a coluna `rodovia` traz a BR e os km. BRs coincidentes (mesma pista) contam uma vez,
no trecho principal. Cada sinistro da PRF vai para o ponto mais próximo da BR informada pela coordenada
(até 500 m); sem coordenada, vale o km. Sinistros só com coordenada vão para o trecho mais próximo (até
100 m); se esse trecho for de outra UF, o sinistro fica de fora e aparece no resumo.

**VMD.** Cada segmento recebe o VMD do trecho de mesmo código na planilha do PNCT, com a posição levada
pela fração do trecho (o km pode mudar entre versões do SNV); se o código não existir, vale o trecho da
mesma BR que contém o km do meio do segmento, só no eixo principal (acessos, contornos, travessias, variantes
e anéis têm quilometragem própria). O VMD do segmento é a soma dos dois sentidos (com a análise
por sentido, cada sentido usa o seu). O app avisa quando o PNCT marca o trecho como “Não Simulável” e quando
o ano do VMD difere do ano dos sinistros. Sem VMD, a Trilha 3 e os métodos de taxa da Trilha 1 não rodam.
Com a planilha de 2019 e o SNV 202610A, 15% dos segmentos do país ficam sem VMD: dois terços são rodovias
não pavimentadas, que o PNCT não modela; o resto são trechos pavimentados depois de 2019, trechos que o
PNCT não conseguiu simular e trechos criados depois da versão 202001A do SNV.

**OpenStreetMap.** O app lê as vias no retângulo dos sinistros da UF (classes de via expressa a via local;
ruas residenciais são opcionais), descarta as rodovias federais e o que estiver a até 40 m do SNV, junta os
pedaços com o mesmo nome ou código (ex.: DF-001), deixa uma só pista onde a via é duplicada e corta as vias
em segmentos do mesmo comprimento (IDs `OSM000001-001`). Sinistros que não ficaram no SNV vão para o
segmento mais próximo, até 50 m. Isso só faz sentido com uma base de sinistros de todas as vias (municipal
ou estadual): os dados da PRF cobrem só rodovias federais, e o app avisa. Os dados do OpenStreetMap são
© colaboradores do OpenStreetMap, sob a licença ODbL; a atribuição aparece no app e no relatório.

Na validação com a segmentação oficial de DF, MG e PE (2021 a 2023), os trechos que não mudaram de versão
do SNV tiveram 81% dos segmentos com as mesmas contagens e correlação de 0,92 a 0,95 na UPS
(`docs/auditoria/validacao_segmentacao.py`).

## Formato dos dados

A planilha (CSV ou .xlsx) pode estar no modelo do app (botão “Baixar Exemplo”) ou no formato das planilhas
oficiais (`ID`, `CodigoSNV`, `Comprimento`, `Latitude Média`, `Longitude Média`, `Sentido`, `VMD AAAA`,
`Sinistros_SV/CV/CO AAAA`).

| Coluna | Conteúdo | Usada em |
| --- | --- | --- |
| `segmento_id` | identificador do segmento | todas |
| `sem_vitima`, `com_vitima`, `com_obito` | número de sinistros de cada tipo | todas |
| `extensao_trecho` | extensão em km (o Manual recomenda segmentos de 1 km) | Trilhas 1 e 3 |
| `volume_trafego` | VMDa | Trilha 3 e taxas da Trilha 1 |
| `latitude`, `longitude` | graus decimais | Trilha 2 e mapas |
| `ano` | ano dos dados; várias linhas do mesmo segmento são somadas | período (n anos) |

Uma planilha com um sinistro por linha (sem a extensão dos segmentos) vai na Opção 2, a segmentação
automática; na Opção 1, só a Trilha 2 roda com ela, e o app avisa. CSV com `;` e vírgula decimal (padrão do
Excel em português) é aceito. Em planilhas oficiais, o mesmo `ID`
nos dois sentidos vira dois segmentos (`25-C` e `25-D`).

## Privacidade

O app não grava os arquivos enviados: os dados ficam na memória da sessão e são descartados quando ela
termina. O repositório não traz dados reais; os arquivos de `data/` são exemplos fictícios usados nos testes.

## Estrutura

```
app.py                 interface Streamlit
models/                trilha1_valor_critico.py, trilha2_kernel.py, trilha3_bayes.py
utils/                 entrada (leitura e validação), preprocessamento (UPS), segmentacao (SNV e
                       sinistros), trafego (VMD do PNCT), osm (vias do OpenStreetMap), mapas,
                       relatorio (PDF)
static/fonts/          fonte Roboto (SIL OFL 1.1), servida localmente
assets/                marcas do projeto, vazia nesta versão (ver assets/LEIA-ME.md)
data/                  exemplos fictícios usados nos testes, inclusive os 15 segmentos do Manual
docs/                  guia de hospedagem, checklist de publicação e scripts de validação
tests/                 testes automatizados (pytest), também rodados no GitHub a cada envio
Dockerfile, compose.yaml   imagem para servidor próprio
```

## Como contribuir

Sugestões e correções são bem-vindas por *issues* e *pull requests*. Antes de enviar uma alteração, rode
`python -m pytest`.

## Licença

Código sob a licença MIT (`LICENSE`): qualquer pessoa pode usar, estudar, modificar e redistribuir o código,
inclusive em outros projetos, desde que mantenha o aviso de copyright. As dependências têm licenças
compatíveis (ver `THIRD_PARTY_LICENSES.md`); a fonte Roboto segue a SIL OFL 1.1 (`static/fonts/OFL.txt`).

## Marcas

Esta versão não traz logotipos. As marcas dos financiadores e parceiros voltam numa versão futura, depois de
confirmadas com os envolvidos, e não são cobertas pela licença do código (ver `assets/LEIA-ME.md`).
