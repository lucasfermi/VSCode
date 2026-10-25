import pandas as pd

from utils.constantes import COLUNAS_SINISTROS


def calcular_ups(df: pd.DataFrame, peso_sem_vitima: float, peso_com_vitima: float,
                 peso_com_obito: float) -> pd.Series:
    """Unidade Padrão de Severidade (Manual, equação 2.1)."""
    return (df["sem_vitima"] * peso_sem_vitima
            + df["com_vitima"] * peso_com_vitima
            + df["com_obito"] * peso_com_obito)


def preparar_dados(df: pd.DataFrame, peso_sem_vitima: float, peso_com_vitima: float,
                   peso_com_obito: float) -> pd.DataFrame:
    """Prepara os dados para as trilhas: converte sinistros em número, calcula a UPS
    e guarda os pesos usados em ``df.attrs['pesos_ups']`` (para o KDE e o relatório)."""
    df_proc = df.copy()
    numericas = [c for c in (*COLUNAS_SINISTROS, "latitude", "longitude", "extensao_trecho", "volume_trafego",
                             "n_anos") if c in df_proc]
    df_proc[numericas] = df_proc[numericas].apply(pd.to_numeric, errors="coerce")
    df_proc[COLUNAS_SINISTROS] = df_proc[COLUNAS_SINISTROS].fillna(0)
    df_proc["total_sinistros"] = df_proc[COLUNAS_SINISTROS].sum(axis=1)
    df_proc["UPS"] = calcular_ups(df_proc, peso_sem_vitima, peso_com_vitima, peso_com_obito)
    df_proc.attrs["pesos_ups"] = {
        "sem_vitima": peso_sem_vitima,
        "com_vitima": peso_com_vitima,
        "com_obito": peso_com_obito,
    }
    return df_proc
