from datetime import date

import pytest

from work_assistant import schedule


def test_period_key():
    assert schedule.period_key("monthly", date(2026, 8, 3)) == "2026-08"
    # 2026-08-03 é segunda da semana ISO 32
    assert schedule.period_key("weekly", date(2026, 8, 3)) == "2026-W32"


def test_opens_on_monthly():
    assert schedule.opens_on("monthly", 1, "2026-08") == date(2026, 8, 1)
    assert schedule.opens_on("monthly", 15, "2026-08") == date(2026, 8, 15)


def test_opens_on_clamps_to_short_month():
    """Dia 31 em fevereiro cai no último dia em vez de estourar."""
    assert schedule.opens_on("monthly", 31, "2026-02") == date(2026, 2, 28)
    assert schedule.opens_on("monthly", 31, "2028-02") == date(2028, 2, 29)  # bissexto
    assert schedule.opens_on("monthly", 29, "2026-02") == date(2026, 2, 28)


def test_opens_on_negative_anchor_counts_from_end():
    assert schedule.opens_on("monthly", -1, "2026-02") == date(2026, 2, 28)
    assert schedule.opens_on("monthly", -1, "2026-04") == date(2026, 4, 30)
    assert schedule.opens_on("monthly", -1, "2026-12") == date(2026, 12, 31)
    assert schedule.opens_on("monthly", -2, "2026-12") == date(2026, 12, 30)


def test_opens_on_weekly():
    assert schedule.opens_on("weekly", 1, "2026-W32") == date(2026, 8, 3)
    assert schedule.opens_on("weekly", 5, "2026-W32") == date(2026, 8, 7)


def test_closes_on_crosses_the_month():
    assert schedule.closes_on("monthly", 1, 4, "2026-08") == date(2026, 8, 5)
    # último dia de janeiro + 2 dias cai em fevereiro
    assert schedule.closes_on("monthly", -1, 2, "2026-01") == date(2026, 2, 2)


def test_periods_between_monthly():
    """Só entram os períodos cuja ABERTURA cai na janela."""
    found = schedule.periods_between("monthly", 1, date(2026, 6, 15), date(2026, 9, 5))
    # a abertura de junho (01/06) é anterior ao start, então junho fica de fora
    assert found == ["2026-07", "2026-08", "2026-09"]


def test_periods_between_excludes_period_not_open_yet():
    """Hoje é dia 3 e a rotina abre dia 15: o ciclo do mês ainda não existe."""
    assert schedule.periods_between("monthly", 15, date(2026, 8, 1), date(2026, 8, 3)) == []


def test_periods_between_weekly_crosses_the_year():
    found = schedule.periods_between("weekly", 1, date(2026, 12, 20), date(2027, 1, 10))
    assert found == ["2026-W52", "2026-W53", "2027-W01"]


def test_periods_between_empty_when_start_after_today():
    assert schedule.periods_between("monthly", 1, date(2026, 9, 1), date(2026, 8, 1)) == []


def test_periods_between_single_day_window():
    """Start == today == dia da abertura: o ciclo do dia entra."""
    assert schedule.periods_between("monthly", 1, date(2026, 8, 1), date(2026, 8, 1)) == ["2026-08"]


def test_next_open():
    assert schedule.next_open("monthly", 1, date(2026, 8, 3)) == date(2026, 9, 1)
    assert schedule.next_open("monthly", 15, date(2026, 8, 3)) == date(2026, 8, 15)
    assert schedule.next_open("monthly", -1, date(2026, 8, 31)) == date(2026, 9, 30)


def test_describe():
    assert schedule.describe("monthly", 1, 4) == "mensal, dia 1 (+4d)"
    assert schedule.describe("monthly", -1, 2) == "mensal, último dia (+2d)"
    assert schedule.describe("monthly", -2, 0) == "mensal, penúltimo dia"
    assert schedule.describe("weekly", 1, 1) == "semanal, segunda (+1d)"
    assert schedule.describe("weekly", 3, 0) == "semanal, quarta"


def test_validate_cadence_error():
    with pytest.raises(ValueError, match="Cadência inválida"):
        schedule.validate_cadence("diaria")


def test_validate_anchor_errors():
    with pytest.raises(ValueError, match="Dia de abertura inválido"):
        schedule.validate_anchor("monthly", 0)
    with pytest.raises(ValueError, match="Dia de abertura inválido"):
        schedule.validate_anchor("monthly", 32)
    with pytest.raises(ValueError, match="Dia de abertura inválido"):
        schedule.validate_anchor("monthly", -29)
    with pytest.raises(ValueError, match="Dia de abertura inválido"):
        schedule.validate_anchor("weekly", 8)
    assert schedule.validate_anchor("weekly", 7) == 7
    assert schedule.validate_anchor("monthly", -28) == -28


def test_invalid_period_error():
    with pytest.raises(ValueError, match="Período inválido"):
        schedule.opens_on("monthly", 1, "agosto")
    with pytest.raises(ValueError, match="Período inválido"):
        schedule.opens_on("monthly", 1, "2026-13")
    with pytest.raises(ValueError, match="Período inválido"):
        schedule.opens_on("weekly", 1, "2026-08")
