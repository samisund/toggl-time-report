import pytest

from generate_invoice_pdf import round_up_half_hour, seconds_to_hours


def test_round_up_half_hour_examples():
    assert round_up_half_hour(12 * 60) == pytest.approx(0.5)
    assert round_up_half_hour(23 * 60) == pytest.approx(0.5)
    assert round_up_half_hour(63 * 60) == pytest.approx(1.5)


def test_round_up_half_hour_handles_zero_and_exact_blocks():
    assert round_up_half_hour(0) == pytest.approx(0.0)
    exact_block_seconds = 30 * 60
    assert round_up_half_hour(exact_block_seconds) == pytest.approx(0.5)


def test_seconds_to_hours_remains_exact_conversion():
    assert seconds_to_hours(3600) == pytest.approx(1.0)
    assert seconds_to_hours(90 * 60) == pytest.approx(1.5)
