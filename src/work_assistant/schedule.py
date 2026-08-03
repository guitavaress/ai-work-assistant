"""Aritmética de cadência e janela das rotinas.

Módulo puro: sem banco e sem dependência do resto do pacote, para ser testado
isoladamente. Todas as funções que dependem de "hoje" recebem a data por
parâmetro — nada aqui chama `date.today()`.

Um *período* é a chave textual de um ciclo: `YYYY-MM-DD` (diária), `YYYY-Www`
(semanal, semana ISO), `YYYY-MM` (mensal) ou `YYYY-Tn` (trimestral). O período de
um ciclo é sempre o do seu dia de abertura.
"""

import calendar
from datetime import date, timedelta

CADENCES = ("daily", "weekly", "monthly", "quarterly")

_WEEKDAYS_PT = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_MONTHS_PT = (
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez",
)
_ORDINALS_FROM_END = {-1: "último dia", -2: "penúltimo dia"}
_CADENCE_LABELS = {
    "daily": "diária", "weekly": "semanal", "monthly": "mensal", "quarterly": "trimestral",
}


def validate_cadence(cadence: str) -> str:
    if cadence not in CADENCES:
        raise ValueError(
            f"Cadência inválida '{cadence}': use {', '.join(CADENCES)}"
        )
    return cadence


def validate_anchor(cadence: str, anchor: int) -> int:
    """Valida o dia de abertura conforme a cadência.

    Diária: não há âncora — a rotina abre todo dia útil.
    Mensal e trimestral: 1..31 (dias 29-31 são ajustados para o último dia em
    meses curtos) ou -1..-28 contando do fim do mês (-1 = último dia). No
    trimestre a âncora vale sobre o PRIMEIRO mês do trimestre.
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
        escopo = "trimestral" if cadence == "quarterly" else "mensal"
        raise ValueError(
            f"Dia de abertura inválido '{anchor}': na cadência {escopo} use 1 a 31,"
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


def _day_in_month(year: int, month: int, anchor: int) -> date:
    """Resolve a âncora dentro de um mês. Regra única do mensal e do trimestral.

    Âncora positiva além do fim do mês (31 em fevereiro) cai no último dia;
    âncora negativa conta de trás para frente (-1 = último dia).
    """
    last_day = calendar.monthrange(year, month)[1]
    day = min(anchor, last_day) if anchor > 0 else max(last_day + anchor + 1, 1)
    return date(year, month, day)


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
        if cadence == "quarterly":
            year, quarter = period.split("-T")
            value = int(quarter)
            if not 1 <= value <= 4:
                raise ValueError
            return int(year), value
        year, week = period.split("-W")
        value = int(week)
        if not 1 <= value <= 53:
            raise ValueError
        return int(year), value
    except ValueError:
        expected = {"monthly": "YYYY-MM", "quarterly": "YYYY-Tn"}.get(cadence, "YYYY-Www")
        raise ValueError(f"Período inválido '{period}': use o formato {expected}") from None


def period_key(cadence: str, day: date) -> str:
    """Chave do período em que a data cai."""
    cadence = validate_cadence(cadence)
    if cadence == "daily":
        return day.isoformat()
    if cadence == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    if cadence == "quarterly":
        return f"{day.year:04d}-T{(day.month - 1) // 3 + 1}"
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
    # No trimestre a abertura cai no primeiro mês (T1 -> jan, T2 -> abr, ...).
    month = (value - 1) * 3 + 1 if cadence == "quarterly" else value
    return _day_in_month(year, month, anchor)


def closes_on(cadence: str, anchor: int, sla_days: int, period: str) -> date:
    """Prazo do ciclo. `sla_days` é a DURAÇÃO da janela, contando a abertura:
    abre dia 1 com sla_days=5 e fecha dia 5."""
    return opens_on(cadence, anchor, period) + timedelta(days=sla_days - 1)


def _next_period(cadence: str, period: str) -> str:
    if validate_cadence(cadence) == "daily":
        day = _parse_day(period) + timedelta(days=1)
        while not _is_workday(day):
            day += timedelta(days=1)
        return day.isoformat()
    year, value = _parse_period(cadence, period)
    if cadence == "monthly":
        return f"{year + 1:04d}-01" if value == 12 else f"{year:04d}-{value + 1:02d}"
    if cadence == "quarterly":
        return f"{year + 1:04d}-T1" if value == 4 else f"{year:04d}-T{value + 1}"
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


def window_label(cadence: str, anchor: int, sla_days: int = 1) -> str:
    """Janela recorrente em PT-BR. `sla_days` é a duração, contando a abertura."""
    anchor = validate_anchor(cadence, anchor)
    extra = max(0, sla_days - 1)  # dias APÓS a abertura
    if cadence == "daily":
        return "todo dia útil" if not extra else f"todo dia útil + {extra}d"
    if cadence == "weekly":
        opening = _WEEKDAYS_PT[anchor - 1]
        if not extra:
            return f"toda {opening}"
        if anchor + extra <= 7:
            return f"de {opening} a {_WEEKDAYS_PT[anchor + extra - 1]}"
        return f"toda {opening} + {extra}d"
    escopo = "de cada trimestre" if cadence == "quarterly" else "de cada mês"
    mes = " do 1º mês" if cadence == "quarterly" else ""
    if anchor < 0:
        base = _ORDINALS_FROM_END.get(anchor, f"{abs(anchor)}º dia do fim")
        base = f"{base}{mes}"
        return f"{base} {escopo}" if not extra else f"{base} + {extra}d {escopo}"
    if not extra:
        return f"dia {anchor:02d}{mes} {escopo}"
    # Acima do dia 28 a janela pode virar o mês: "30–02" seria mentira em fevereiro.
    if anchor + extra <= 28 and not mes:
        return f"{anchor:02d}–{anchor + extra:02d} {escopo}"
    return f"dia {anchor:02d}{mes} + {extra}d {escopo}"


def describe(cadence: str, anchor: int, sla_days: int = 1) -> str:
    """Descrição em PT-BR da cadência, para as tabelas da CLI."""
    anchor = validate_anchor(cadence, anchor)
    nome = cadence_label(cadence)
    if cadence == "daily":
        base = f"{nome}, todo dia útil"
    elif cadence == "weekly":
        base = f"{nome}, {_WEEKDAYS_PT[anchor - 1]}"
    elif anchor > 0:
        base = f"{nome}, dia {anchor}"
    else:
        base = f"{nome}, {_ORDINALS_FROM_END.get(anchor, f'{abs(anchor)}º dia do fim')}"
    # "janela Nd" e não "+Nd": com duração inclusiva, o "+" seria ambíguo.
    return f"{base} (janela {sla_days}d)" if sla_days > 1 else base
