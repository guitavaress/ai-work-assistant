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
    # sla_days é a DURAÇÃO da janela, contando a abertura: abre 01, fecha 05
    assert schedule.closes_on("monthly", 1, 5, "2026-08") == date(2026, 8, 5)
    assert schedule.closes_on("monthly", 1, 1, "2026-08") == date(2026, 8, 1)
    # janela de 3 dias a partir do último dia de janeiro cai em fevereiro
    assert schedule.closes_on("monthly", -1, 3, "2026-01") == date(2026, 2, 2)


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
    assert schedule.describe("monthly", 1, 5) == "mensal, dia 1 (janela 5d)"
    assert schedule.describe("monthly", -1, 2) == "mensal, último dia (janela 2d)"
    assert schedule.describe("monthly", -2, 1) == "mensal, penúltimo dia"
    assert schedule.describe("weekly", 1, 1) == "semanal, segunda"
    assert schedule.describe("weekly", 3, 3) == "semanal, quarta (janela 3d)"


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


# --- Cadência diária --------------------------------------------------------


def test_daily_period_key_and_opens_on():
    assert schedule.period_key("daily", date(2026, 8, 3)) == "2026-08-03"
    assert schedule.opens_on("daily", 0, "2026-08-03") == date(2026, 8, 3)


def test_daily_anchor_must_be_zero():
    assert schedule.validate_anchor("daily", 0) == 0
    with pytest.raises(ValueError, match="abre todo dia útil"):
        schedule.validate_anchor("daily", 1)


def test_daily_periods_between_skips_weekends():
    """2026-08-03 é segunda; 08 e 09 são sábado e domingo."""
    found = schedule.periods_between("daily", 0, date(2026, 8, 3), date(2026, 8, 10))
    assert found == [
        "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10",
    ]


def test_daily_periods_between_starting_on_a_weekend():
    # 2026-08-08 é sábado: o primeiro ciclo só sai na segunda
    assert schedule.periods_between("daily", 0, date(2026, 8, 8), date(2026, 8, 10)) == [
        "2026-08-10"
    ]


def test_daily_next_open_jumps_the_weekend():
    assert schedule.next_open("daily", 0, date(2026, 8, 7)) == date(2026, 8, 10)  # sexta -> segunda
    assert schedule.next_open("daily", 0, date(2026, 8, 3)) == date(2026, 8, 4)


def test_daily_closes_on():
    assert schedule.closes_on("daily", 0, 1, "2026-08-03") == date(2026, 8, 3)
    assert schedule.closes_on("daily", 0, 2, "2026-08-03") == date(2026, 8, 4)


def test_daily_invalid_period():
    with pytest.raises(ValueError, match="Período inválido"):
        schedule.opens_on("daily", 0, "2026-08")


# --- Rótulos PT-BR ----------------------------------------------------------


def test_cadence_label():
    assert schedule.cadence_label("daily") == "diária"
    assert schedule.cadence_label("weekly") == "semanal"
    assert schedule.cadence_label("monthly") == "mensal"


def test_period_label():
    assert schedule.period_label("monthly", "2026-08") == "ciclo 2026-08"
    assert schedule.period_label("weekly", "2026-W32") == "ciclo 2026-W32"
    assert schedule.period_label("daily", "2026-08-01") == "ciclo 01 ago"


def test_window_label_monthly():
    assert schedule.window_label("monthly", 1, 5) == "01–05 de cada mês"
    assert schedule.window_label("monthly", 1, 1) == "dia 01 de cada mês"
    # acima do dia 28 a faixa viraria mentira em fevereiro
    assert schedule.window_label("monthly", 28, 5) == "dia 28 + 4d de cada mês"


def test_window_label_monthly_negative_anchor():
    assert schedule.window_label("monthly", -1, 1) == "último dia de cada mês"
    assert schedule.window_label("monthly", -1, 4) == "último dia + 3d de cada mês"
    assert schedule.window_label("monthly", -2, 1) == "penúltimo dia de cada mês"
    assert schedule.window_label("monthly", -5, 1) == "5º dia do fim de cada mês"


def test_window_label_weekly_and_daily():
    assert schedule.window_label("weekly", 1, 1) == "toda segunda"
    assert schedule.window_label("weekly", 1, 5) == "de segunda a sexta"
    assert schedule.window_label("weekly", 5, 5) == "toda sexta + 4d"
    assert schedule.window_label("daily", 0, 1) == "todo dia útil"
    assert schedule.window_label("daily", 0, 2) == "todo dia útil + 1d"


def test_describe_daily():
    assert schedule.describe("daily", 0, 1) == "diária, todo dia útil"
    assert schedule.describe("daily", 0, 2) == "diária, todo dia útil (janela 2d)"


def test_invalid_cadence_message_lists_the_options():
    with pytest.raises(ValueError, match="daily, weekly, monthly, quarterly"):
        schedule.validate_cadence("anual")


# --- Cadência trimestral ----------------------------------------------------


def test_quarterly_period_key():
    assert schedule.period_key("quarterly", date(2026, 1, 15)) == "2026-T1"
    assert schedule.period_key("quarterly", date(2026, 3, 31)) == "2026-T1"
    assert schedule.period_key("quarterly", date(2026, 4, 1)) == "2026-T2"
    assert schedule.period_key("quarterly", date(2026, 12, 31)) == "2026-T4"


def test_quarterly_opens_on_first_month_of_the_quarter():
    assert schedule.opens_on("quarterly", 1, "2026-T1") == date(2026, 1, 1)
    assert schedule.opens_on("quarterly", 1, "2026-T3") == date(2026, 7, 1)
    assert schedule.opens_on("quarterly", 10, "2026-T4") == date(2026, 10, 10)


def test_quarterly_uses_the_same_anchor_rules_as_monthly():
    # clamp: 31 em abril (T2) cai no dia 30
    assert schedule.opens_on("quarterly", 31, "2026-T2") == date(2026, 4, 30)
    # âncora negativa conta do fim do primeiro mês do trimestre
    assert schedule.opens_on("quarterly", -1, "2026-T1") == date(2026, 1, 31)
    assert schedule.opens_on("quarterly", -1, "2026-T2") == date(2026, 4, 30)


def test_quarterly_closes_on_uses_duration():
    assert schedule.closes_on("quarterly", 1, 10, "2026-T3") == date(2026, 7, 10)
    assert schedule.closes_on("quarterly", 1, 1, "2026-T3") == date(2026, 7, 1)


def test_quarterly_periods_between_crosses_the_year():
    found = schedule.periods_between("quarterly", 1, date(2026, 6, 1), date(2027, 2, 1))
    # T2/2026 abriu em 01/04, antes do start; entram T3, T4 e T1 de 2027
    assert found == ["2026-T3", "2026-T4", "2027-T1"]


def test_quarterly_next_open():
    assert schedule.next_open("quarterly", 1, date(2026, 8, 2)) == date(2026, 10, 1)
    assert schedule.next_open("quarterly", 15, date(2026, 7, 1)) == date(2026, 7, 15)


def test_quarterly_labels():
    assert schedule.cadence_label("quarterly") == "trimestral"
    assert schedule.period_label("quarterly", "2026-T3") == "ciclo 2026-T3"
    assert schedule.window_label("quarterly", 1, 1) == "dia 01 do 1º mês de cada trimestre"
    assert schedule.window_label("quarterly", 1, 10) == "dia 01 do 1º mês + 9d de cada trimestre"
    assert schedule.window_label("quarterly", -1, 1) == "último dia do 1º mês de cada trimestre"
    assert schedule.describe("quarterly", 1, 10) == "trimestral, dia 1 (janela 10d)"


def test_quarterly_invalid_period():
    with pytest.raises(ValueError, match="YYYY-Tn"):
        schedule.opens_on("quarterly", 1, "2026-T5")
    with pytest.raises(ValueError, match="YYYY-Tn"):
        schedule.opens_on("quarterly", 1, "2026-08")
