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

CSV com `;` e vírgula decimal (padrão do Excel em português) é aceito. Em planilhas oficiais, o mesmo `ID`
nos dois sentidos vira dois segmentos (`25-C` e `25-D`).

## Privacidade

O app não grava os arquivos enviados: os dados ficam na memória da sessão e são descartados quando ela
termina. O repositório não traz dados reais; os arquivos de `data/` são exemplos fictícios usados nos testes.

## Estrutura

```
app.py                 interface Streamlit
models/                trilha1_valor_critico.py, trilha2_kernel.py, trilha3_bayes.py
utils/                 entrada (leitura e validação), preprocessamento (UPS), mapas, relatorio (PDF)
static/fonts/          fonte Roboto (SIL OFL 1.1), servida localmente
assets/                marcas do projeto, vazia nesta versão (ver assets/LEIA-ME.md)
data/                  exemplos fictícios usados nos testes, inclusive os 15 segmentos do Manual
docs/                  guia de hospedagem, checklist de publicação e validação temporal da Trilha 3
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
