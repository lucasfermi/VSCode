"""Constantes compartilhadas pela aplicação.

Numeração oficial das trilhas, adotada pela equipe a partir da versão 4:
Trilha 1 = Valor Crítico, Trilha 2 = Densidade de Kernel (KDE) e Trilha 3 = Empírico
de Bayes. Documentos anteriores (Manual de 2025, Manual de Utilização) usam a ordem
antiga, com Bayes como Trilha 2 e KDE como Trilha 3. Para mudar a numeração exibida,
altere só o dicionário ``TRILHAS``.
"""

# Pesos da Unidade Padrão de Severidade (Manual, equação 2.1)
PESOS_UPS_PADRAO = {"sem_vitima": 1, "com_vitima": 4, "com_obito": 28}

COLUNAS_SINISTROS = ["sem_vitima", "com_vitima", "com_obito"]

TRILHAS = {
    "vc": {"numero": 1, "nome": "Valor Crítico"},
    "kde": {"numero": 2, "nome": "Densidade de Kernel (KDE)"},
    "bayes": {"numero": 3, "nome": "Empírico de Bayes"},
}

# Chaves na ordem de exibição (pela numeração)
ORDEM_TRILHAS = sorted(TRILHAS, key=lambda c: TRILHAS[c]["numero"])


def rotulo_trilha(chave: str) -> str:
    """Rótulo completo de uma trilha, ex.: 'Trilha 3 — Empírico de Bayes'."""
    t = TRILHAS[chave]
    return f"Trilha {t['numero']} — {t['nome']}"


# Coeficiente k da Normal padrão unicaudal (Manual, Tabela 3.1).
# 97,5% (k = 1,960) foi acrescentado porque é o valor usado pela Trilha de Bayes da v4.
NIVEIS_CONFIANCA_K = {
    85.0: 1.036,
    90.0: 1.282,
    95.0: 1.645,
    97.5: 1.960,
    99.0: 2.326,
    99.5: 2.576,
}


def k_por_nivel(nivel_confianca: float) -> float:
    """Retorna o k da Tabela 3.1 do Manual; outros níveis usam a Normal padrão."""
    nivel = float(nivel_confianca)
    if nivel in NIVEIS_CONFIANCA_K:
        return NIVEIS_CONFIANCA_K[nivel]
    from scipy.stats import norm

    return float(norm.ppf(nivel / 100.0))
