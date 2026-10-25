# Histórico de versões

## 4.2 — em desenvolvimento

- Segmentação automática (Produto 2): a partir dos sinistros por ocorrência da PRF e do SNV do DNIT, o
  app corta a malha da UF em segmentos de comprimento escolhido (1 km por padrão, de 0,1 a 10 km) e conta
  os sinistros de cada um (`utils/segmentacao.py`).
  - Segmentos dentro de cada trecho do SNV com pista, com ID derivado do código do SNV e sobra menor que
    meio segmento somada ao anterior; trechos planejados e travessias ficam de fora.
  - BRs coincidentes contam uma vez, no trecho principal; a posição passa de uma BR para outra pela fração
    do trecho, inclusive quando a geometria está no sentido oposto.
  - Sinistro localizado pela coordenada, presa à BR informada (até 500 m); sem coordenada, pelo km.
  - Opção de separar por sentido da via; planilha dos segmentos para baixar.
- Validação contra a segmentação oficial de DF, MG e PE (2021 a 2023): nos 71 trechos que não mudaram de
  versão do SNV, 81% dos segmentos têm as mesmas contagens e a correlação da UPS fica entre 0,92 e 0,95
  (`docs/auditoria/validacao_segmentacao.py`).
- Sinistros de qualquer planilha com latitude, longitude e ano (ou data), com a gravidade em texto ou em
  contagens; arquivos da PRF “por pessoa” contam cada ocorrência uma vez.
- VMD por segmento a partir da planilha de modelagem do PNCT/DNIT (`utils/trafego.py`): mesmo código do
  SNV, com a posição pela fração do trecho, ou mesma BR e km no eixo principal (acessos, contornos e
  travessias têm quilometragem própria e recebiam o VMD de outro ponto da BR); avisos para trechos
  “Não Simulável” e para VMD de ano diferente dos sinistros.
- Vias fora do SNV pelo OpenStreetMap (`utils/osm.py`): arquivo regional `.osm.pbf`, vias federais e
  trechos a até 40 m do SNV descartados, pedaços da mesma via unidos, pista dupla tratada como uma via.
  Atribuição ODbL no app e no relatório.
- Relatório: fontes dos dados (versão do SNV, VMD do PNCT, OpenStreetMap).
- Planilha com um sinistro por linha enviada na Opção 1: o app avisa que só a Trilha 2 roda e indica a
  Opção 2; as mensagens das Trilhas 1 e 3 dizem o que fazer quando faltam extensão ou VMD. Com muitos
  sinistros longe das rodovias federais, o app sugere o arquivo do OpenStreetMap.
- Sinistro só com coordenada que cai numa rodovia federal de outra UF fica de fora e aparece no resumo.
- Tabelas de resultados mostram a rodovia e os km de cada segmento; a planilha aceita a coluna `n_anos`.
- Novas dependências: shapely, pyproj e pyogrio. Limite de envio de 1 GB (arquivos regionais do
  OpenStreetMap).

## 4.1.1 — outubro de 2026

Correções encontradas nos testes da segmentação automática, que gera muitos segmentos curtos ou sem
sinistros.

- Trilha 1: segmento sem sinistros podia sair crítico. Com a correção de −0,5/m do Manual, o valor crítico
  de um segmento curto fica negativo e o índice zero passava dele; na planilha de DF, MG e PE eram 2
  segmentos no padrão (severidade, 95%) e até 18 em outras configurações. Agora o app avisa e não os marca.
- Trilha 2: quando 75% ou mais dos segmentos não têm sinistros no raio do núcleo, o limite do quartil
  superior era zero e todos os segmentos viravam críticos; agora só a densidade positiva conta.

## 4.1 — outubro de 2026

Correções da auditoria de código (Produto 1 do TR). A versão 4 continua intacta na pasta `Versão 4`.

### Erros corrigidos

- Trilha de Bayes falhava sempre com pandas 3 (`params[0]`).
- Relatório PDF quebrava em Linux por causa dos caches `.pkl` do fpdf com caminho do Windows; migrado para
  fpdf2, sem caches.
- O adaptador descartava a coluna `segmento_id` do modelo do app.
- O `ID` repetido nos dois sentidos das planilhas oficiais misturava sentidos na Trilha 1 e duplicava
  linhas nos mapas; agora cada sentido é um segmento (`25-C`, `25-D`).
- O KDE ignorava os pesos UPS escolhidos na interface.
- O upload era reprocessado a cada clique: os resultados sumiam, registros manuais se perdiam e “Limpar”
  não limpava.
- PDF: numeração das trilhas igual à do app, histograma de UPS que nunca aparecia,
  densidade que saía “0.00”, “óbitos” que eram sinistros com óbito, contagem por segmento único.
- Colunas de sinistro reconhecidas por padrão exato (uma coluna “TOTAL_COM_VITIMA” não vira mais óbito);
  linhas sem ID ou de total são descartadas com aviso; CSV com `;` e vírgula decimal é aceito.
- Arquivo temporário do gráfico (erro no Windows) substituído por memória.
- Parâmetros obsoletos do Streamlit (`use_container_width`, `components.html`) substituídos.
- O app confere as versões das bibliotecas ao abrir e, se o ambiente for o da v4 (com o `fpdf` antigo),
  mostra os comandos para criar o ambiente certo em vez de um erro de importação.

### Métodos

- Trilha 1: os quatro métodos do Manual (número, severidade, taxa de sinistros, taxa de severidade), com
  índice por km (eq. 3.1 a 3.12). Sinal da correção e exclusão de segmentos sem sinistros configuráveis.
  Testes reproduzem os exemplos resolvidos do Manual.
- Trilha 2 (KDE): mesmo algoritmo da v4 e do código R do Manual, com resultado idêntico, calculado só nas
  células ocupadas e com KD-tree.
- Trilha 3 (Empírico de Bayes): padrão Média Global (Marshall, 1991) aplicada a cada tipo de sinistro;
  opções: Binomial Negativa por tipo (Hauer/HSM) e o procedimento da v4 (igual ao script R).
- Numeração oficial: a da v4 (1 = Valor Crítico, 2 = KDE, 3 = Empírico de Bayes), definida num só lugar
  (`utils/constantes.py`). O Manual de 2025 usa outra ordem.

### Desempenho

- KDE: 47 s e 4,5 GB (PE, 970 segmentos) passaram a 5 ms; DF+MG+PE (3.560) e SP (733 mil sinistros),
  inviáveis na v4, rodam em 0,02 s e 37 s.
- Mapas em camada GeoJSON única: 4,7 MB e 4,1 s viraram 1,0 MB e 0,1 s para 3.560 pontos.
- PDF e planilha de resultados gerados uma vez por execução, não a cada clique; mapas em cache e, acima de
  20 mil pontos, só com os segmentos críticos.

### Repositório

- Licença MIT (`LICENSE`).
- Coleta de estatísticas de uso do Streamlit desativada (`.streamlit/config.toml`); regras de lint em
  `ruff.toml`.
- `requirements.txt` com versões fixadas e só o que é usado; `requirements-dev.txt`, `.gitignore`,
  `.python-version`, `README.md`, `THIRD_PARTY_LICENSES.md`, testes em `tests/`.
- Logotipos e Manual de Utilização fora desta versão, até a confirmação das marcas com os financiadores; a
  barra lateral mostra o nome do sistema em texto (ver `assets/LEIA-ME.md`).
- Hospedagem: `Dockerfile` e `compose.yaml` para servidor próprio e guia para o Streamlit Community Cloud
  (`docs/IMPLANTACAO.md`); testes e lint rodam no GitHub a cada envio (`.github/workflows/testes.yml`).
- Só o aplicativo é publicado: nenhuma planilha real no repositório (o `.gitignore` bloqueia planilhas fora
  dos exemplos fictícios de `data/`).
- Removidos: caches `.pkl`, `__pycache__`, notebook vazio, imagens não usadas e `dados_analisados.xlsx`.
