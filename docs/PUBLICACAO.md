# Checklist de publicação no GitHub

## Decisões da equipe

- [x] Titular do código: Lucas Fermi Pereira de Oliveira (aviso de copyright em `LICENSE`).
- [x] Licença do código: MIT. Se um dia a equipe quiser obrigar versões modificadas a continuarem abertas,
      basta trocar o `LICENSE` pela GPL-3.0; as dependências são compatíveis com as duas.
- [x] Numeração das trilhas: a da v4 (1 = Valor Crítico, 2 = KDE, 3 = Empírico de Bayes). Documentos
      anteriores usam a ordem antiga.
- [x] Marcas: logotipos e Manual de Utilização fora desta versão; voltam depois da confirmação com os
      envolvidos (ver `assets/LEIA-ME.md`).
- [ ] Texto de créditos do `README.md` (projeto, OPAS/OMS, UNRSF, UnB): confirmar junto com as marcas.
- [ ] Licença da documentação e do futuro Manual de Utilização: sugestão CC BY 4.0.
- [x] Dados: o repositório publica só o aplicativo, sem planilhas reais. Os exemplos em `data/` são
      fictícios e servem aos testes.
- [ ] Publicar ou referenciar o script R usado na validação das Trilhas 2 e 3.
- [ ] Método padrão da Trilha 3 (Empírico de Bayes) e correção de continuidade da Trilha 1 (ver relatório
      de auditoria).

## Passos técnicos

- [ ] `pytest` sem falhas (`pip install -r requirements-dev.txt`).
- [ ] `streamlit run app.py` com uma planilha oficial e com o modelo do app.
- [ ] Repositório criado a partir desta pasta, sem histórico de arquivos removidos (caches `.pkl`, dados,
      logotipos).
- [ ] Descrição, tópicos e citação (`CITATION.cff`) no GitHub.
- [x] Testes e lint no GitHub Actions a cada envio (`.github/workflows/testes.yml`).
- [ ] Versão de testes no Streamlit Community Cloud e no servidor do laboratório (`docs/IMPLANTACAO.md`).
