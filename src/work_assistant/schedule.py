"""Aritmética de cadência e janela das rotinas.

Módulo puro: sem banco e sem dependência do resto do pacote, para ser testado
isoladamente. Todas as funções que dependem de "hoje" recebem a data por
parâmetro — nada aqui chama `date.today()`.

Um *período* é a chave textual de um ciclo: `YYYY-MM` (mensal) ou `YYYY-Www`
(semanal, semana ISO). O período de um ciclo é sempre o do seu dia de abertura.
"""

import calendar
from datetime import date, timedelta

CADENCES = ("monthly", "weekly")

_WEEKDAYS_PT = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_ORDINALS_FROM_END = {-1: "último dia", -2: "penúltimo dia"}


def validate_cadence(cadence: str) -> str:
    if cadence not in CADENCES:
        raise ValueError(f"Cadência inválida '{cadence}': use monthly ou weekly")
    return cadence


def validate_anchor(cadence: str, anchor: int) -> int:
    """Valida o dia de abertura conforme a cadência.

    Mensal: 1..31 (dias 29-31 são ajustados para o último dia em meses curtos)
    ou -1..-28 contando do fim do mês (-1 = último dia).
    Semanal: 1..7 no padrão ISO (1 = segunda).
    """
    cadence = validate_cadence(cadence)
    if cadence == "weekly":
        if not 1 <= anchor <= 7:
            raise ValueError(
                f"Dia de abertura inválido '{anchor}': na cadência semanal use 1 (segunda) a 7 (domingo)"
            )
        return anchor
    if anchor == 0 or not -28 <= anchor <= 31:
        raise ValueError(
            f"Dia de abertura inválido '{anchor}': na cadência mensal use 1 a 31,"
            " ou -1 a -28 para contar do fim do mês"
        )
    return anchor


def _parse_period(cadence: str, period: str) -> tuple[int, int]:
    """Devolve (ano, mês) ou (ano, semana ISO) a partir da chave do período."""
    cadence = validate_cadence(cadence)
    try:
        if cadence == "monthly":
            year, month = period.split("-")
            value = int(month)
            if not 1 <= value <= 12:
                raise ValueError
            return int(year), value
        year, week = period.split("-W")
        value = int(week)
        if not 1 <= value <= 53:
            raise ValueError
        return int(year), value
    except ValueError:
        expected = "YYYY-MM" if cadence == "monthly" else "YYYY-Www"
        raise ValueError(f"Período inválido '{period}': use o formato {expected}") from None


def period_key(cadence: str, day: date) -> str:
    """Chave do período em que a data cai."""
    if validate_cadence(cadence) == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    year, week, _ = day.isocalendar()
    return f"{year:04d}-W{week:02d}"


def opens_on(cadence: str, anchor: int, period: str) -> date:
    """Dia de abertura do ciclo daquele período."""
    anchor = validate_anchor(cadence, anchor)
    year, value = _parse_period(cadence, period)
    if cadence == "weekly":
        return date.fromisocalendar(year, value, anchor)
    last_day = calendar.monthrange(year, value)[1]
    # Âncora positiva além do fim do mês (31 em fevereiro) cai no último dia;
    # âncora negativa conta de trás para frente (-1 = último dia).
    day = min(anchor, last_day) if anchor > 0 else max(last_day + anchor + 1, 1)
    return date(year, value, day)


def closes_on(cadence: str, anchor: int, sla_days: int, period: str) -> date:
    """Prazo do ciclo: abertura + sla_days."""
    return opens_on(cadence, anchor, period) + timedelta(days=sla_days)


def _next_period(cadence: str, period: str) -> str:
    year, value = _parse_period(cadence, period)
    if cadence == "monthly":
        return f"{year + 1:04d}-01" if value == 12 else f"{year:04d}-{value + 1:02d}"
    return period_key("weekly", date.fromisocalendar(year, value, 1) + timedelta(days=7))


def periods_between(cadence: str, anchor: int, start: date, today: date) -> list[str]:
    """Períodos cuja abertura cai em [start, today], em ordem cronológica.

    A abertura de um período está sempre dentro do próprio mês/semana, então
    basta varrer do período de `start` ao de `today` e filtrar pela abertura.
    """
    anchor = validate_anchor(cadence, anchor)
    if start > today:
        return []
    period = period_key(cadence, start)
    last = period_key(cadence, today)
    found = []
    while period <= last:
        if start <= opens_on(cadence, anchor, period) <= today:
            found.append(period)
        period = _next_period(cadence, period)
    return found


def next_open(cadence: str, anchor: int, today: date) -> date:
    """Próxima abertura depois de hoje."""
    anchor = validate_anchor(cadence, anchor)
    period = period_key(cadence, today)
    while True:
        opening = opens_on(cadence, anchor, period)
        if opening > today:
            return opening
        period = _next_period(cadence, period)


def describe(cadence: str, anchor: int, sla_days: int = 0) -> str:
    """Descrição em PT-BR da cadência, para as tabelas da CLI."""
    anchor = validate_anchor(cadence, anchor)
    if cadence == "weekly":
        base = f"semanal, {_WEEKDAYS_PT[anchor - 1]}"
    elif anchor > 0:
        base = f"mensal, dia {anchor}"
    else:
        base = f"mensal, {_ORDINALS_FROM_END.get(anchor, f'{abs(anchor)}º dia do fim')}"
    return f"{base} (+{sla_days}d)" if sla_days else base
