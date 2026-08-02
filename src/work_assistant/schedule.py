"""Aritmética de cadência e janela das rotinas.

Módulo puro: sem banco e sem dependência do resto do pacote, para ser testado
isoladamente. Todas as funções que dependem de "hoje" recebem a data por
parâmetro — nada aqui chama `date.today()`.

Um *período* é a chave textual de um ciclo: `YYYY-MM` (mensal) ou `YYYY-Www`
(semanal, semana ISO). O período de um ciclo é sempre o do seu dia de abertura.
"""

import calendar
from datetime import date, timedelta

CADENCES = ("daily", "weekly", "monthly")

_WEEKDAYS_PT = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_MONTHS_PT = (
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez",
)
_ORDINALS_FROM_END = {-1: "último dia", -2: "penúltimo dia"}
_CADENCE_LABELS = {"daily": "diária", "weekly": "semanal", "monthly": "mensal"}


def validate_cadence(cadence: str) -> str:
    if cadence not in CADENCES:
        raise ValueError(f"Cadência inválida '{cadence}': use daily, weekly ou monthly")
    return cadence


def validate_anchor(cadence: str, anchor: int) -> int:
    """Valida o dia de abertura conforme a cadência.

    Diária: não há âncora — a rotina abre todo dia útil.
    Mensal: 1..31 (dias 29-31 são ajustados para o último dia em meses curtos)
    ou -1..-28 contando do fim do mês (-1 = último dia).
    Semanal: 1..7 no padrão ISO (1 = segunda).
    """
    cadence = validate_cadence(cadence)
    if cadence == "daily":
        if anchor:
            raise ValueError(
                f"Dia de abertura inválido '{anchor}': a cadência diária abre todo dia útil,"
                " não use --opens"
            )
        return 0
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


def _parse_day(period: str) -> date:
    """Chave de período diário (YYYY-MM-DD) para data."""
    try:
        return date.fromisoformat(period)
    except ValueError:
        raise ValueError(f"Período inválido '{period}': use o formato YYYY-MM-DD") from None


def _is_workday(day: date) -> bool:
    """Segunda a sexta. Sem calendário de feriados — ver CLAUDE.md."""
    return day.weekday() < 5


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
    cadence = validate_cadence(cadence)
    if cadence == "daily":
        return day.isoformat()
    if cadence == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    year, week, _ = day.isocalendar()
    return f"{year:04d}-W{week:02d}"


def opens_on(cadence: str, anchor: int, period: str) -> date:
    """Dia de abertura do ciclo daquele período."""
    anchor = validate_anchor(cadence, anchor)
    if cadence == "daily":
        return _parse_day(period)
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
    if validate_cadence(cadence) == "daily":
        day = _parse_day(period) + timedelta(days=1)
        while not _is_workday(day):
            day += timedelta(days=1)
        return day.isoformat()
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
        opening = opens_on(cadence, anchor, period)
        # Na diária o próprio período é a data; fim de semana não gera ciclo.
        if start <= opening <= today and (cadence != "daily" or _is_workday(opening)):
            found.append(period)
        period = _next_period(cadence, period)
    return found


def next_open(cadence: str, anchor: int, today: date) -> date:
    """Próxima abertura depois de hoje."""
    anchor = validate_anchor(cadence, anchor)
    period = period_key(cadence, today)
    while True:
        opening = opens_on(cadence, anchor, period)
        if opening > today and (cadence != "daily" or _is_workday(opening)):
            return opening
        period = _next_period(cadence, period)


def cadence_label(cadence: str) -> str:
    """Nome da cadência em PT-BR: diária | semanal | mensal."""
    return _CADENCE_LABELS[validate_cadence(cadence)]


def period_label(cadence: str, period: str) -> str:
    """Rótulo curto do ciclo, como aparece no kicker do card."""
    if validate_cadence(cadence) == "daily":
        day = _parse_day(period)
        return f"ciclo {day.day:02d} {_MONTHS_PT[day.month - 1]}"
    _parse_period(cadence, period)  # valida o formato
    return f"ciclo {period}"


def window_label(cadence: str, anchor: int, sla_days: int = 0) -> str:
    """Janela recorrente em PT-BR: 'de quando a quando, todo período'."""
    anchor = validate_anchor(cadence, anchor)
    if cadence == "daily":
        return "todo dia útil" if not sla_days else f"todo dia útil + {sla_days}d"
    if cadence == "weekly":
        opening = _WEEKDAYS_PT[anchor - 1]
        if not sla_days:
            return f"toda {opening}"
        if anchor + sla_days <= 7:
            return f"de {opening} a {_WEEKDAYS_PT[anchor + sla_days - 1]}"
        return f"toda {opening} + {sla_days}d"
    if anchor < 0:
        base = _ORDINALS_FROM_END.get(anchor, f"{abs(anchor)}º dia do fim")
        return f"{base} de cada mês" if not sla_days else f"{base} + {sla_days}d de cada mês"
    if not sla_days:
        return f"dia {anchor:02d} de cada mês"
    # Acima do dia 28 a janela pode virar o mês: "30–02" seria mentira em fevereiro.
    if anchor + sla_days <= 28:
        return f"{anchor:02d}–{anchor + sla_days:02d} de cada mês"
    return f"dia {anchor:02d} + {sla_days}d de cada mês"


def describe(cadence: str, anchor: int, sla_days: int = 0) -> str:
    """Descrição em PT-BR da cadência, para as tabelas da CLI."""
    anchor = validate_anchor(cadence, anchor)
    if cadence == "daily":
        base = "diária, todo dia útil"
    elif cadence == "weekly":
        base = f"semanal, {_WEEKDAYS_PT[anchor - 1]}"
    elif anchor > 0:
        base = f"mensal, dia {anchor}"
    else:
        base = f"mensal, {_ORDINALS_FROM_END.get(anchor, f'{abs(anchor)}º dia do fim')}"
    return f"{base} (+{sla_days}d)" if sla_days else base
