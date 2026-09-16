import pytest

from generate_invoice_pdf import (
    format_multiplier_note,
    is_non_billable,
    multiplier,
    row_hours,
    split_billable,
)


def entry(tags=None, duration=3600):
    return {
        "id": 1,
        "date": None,
        "client": "Asiakas",
        "project": "Projekti",
        "description": "Kuvaus",
        "duration": duration,
        "billable": False,
        "tags": tags if tags is not None else [],
    }


class TestIsNonBillable:
    def test_tag_present(self):
        assert is_non_billable(entry(["ei-laskutettava"])) is True

    def test_tag_matching_ignores_case(self):
        assert is_non_billable(entry(["Ei-Laskutettava"])) is True
        assert is_non_billable(entry(["EI-LASKUTETTAVA"])) is True

    def test_surrounding_whitespace_is_stripped(self):
        assert is_non_billable(entry(["  ei-laskutettava "])) is True

    def test_tag_among_others(self):
        assert is_non_billable(entry(["kokous", "ei-laskutettava", "x2"])) is True

    def test_no_tags(self):
        assert is_non_billable(entry([])) is False

    def test_other_tags_only(self):
        assert is_non_billable(entry(["kokous", "laskutettava"])) is False

    def test_missing_tags_key_is_treated_as_billable(self):
        row = entry()
        del row["tags"]
        assert is_non_billable(row) is False


class TestMultiplier:
    def test_x2_gives_two(self):
        assert multiplier(entry(["x2"])) == 2

    def test_uppercase_x2(self):
        assert multiplier(entry(["X2"])) == 2

    def test_x3_works_without_extra_code(self):
        assert multiplier(entry(["x3"])) == 3

    def test_no_tag_gives_one(self):
        assert multiplier(entry([])) == 1

    def test_alongside_other_tags(self):
        assert multiplier(entry(["ei-laskutettava", "x2"])) == 2

    @pytest.mark.parametrize("tag", ["x", "2x", "xa", "x2y", "ax2", "x-2", ""])
    def test_non_matching_tags_give_one(self, tag):
        assert multiplier(entry([tag])) == 1

    def test_missing_tags_key_gives_one(self):
        row = entry()
        del row["tags"]
        assert multiplier(row) == 1


class TestSplitBillable:
    def test_splits_into_two_lists(self):
        rows = [entry([]), entry(["ei-laskutettava"]), entry([])]
        billable, non_billable = split_billable(rows)
        assert len(billable) == 2
        assert len(non_billable) == 1

    def test_preserves_order(self):
        rows = [
            dict(entry([]), description="a"),
            dict(entry(["ei-laskutettava"]), description="b"),
            dict(entry([]), description="c"),
            dict(entry(["ei-laskutettava"]), description="d"),
        ]
        billable, non_billable = split_billable(rows)
        assert [r["description"] for r in billable] == ["a", "c"]
        assert [r["description"] for r in non_billable] == ["b", "d"]

    def test_empty_input(self):
        assert split_billable([]) == ([], [])

    def test_all_non_billable(self):
        rows = [entry(["ei-laskutettava"]), entry(["ei-laskutettava"])]
        billable, non_billable = split_billable(rows)
        assert billable == []
        assert len(non_billable) == 2


class TestRowHours:
    def test_rounds_before_multiplying(self):
        # 20 min rounds up to 0.5 h, then doubles to 1.0 h.
        # Multiplying first would give 40 min -> 1.0 h by a different path,
        # but the per-person figure must stay a clean 0.5 h block.
        per_person, total, mult = row_hours(entry(["x2"], duration=20 * 60), exact_hours=False)
        assert per_person == pytest.approx(0.5)
        assert total == pytest.approx(1.0)
        assert mult == 2

    def test_rounding_example_from_spec(self):
        per_person, total, _ = row_hours(entry(["x2"], duration=55 * 60), exact_hours=False)
        assert per_person == pytest.approx(1.0)
        assert total == pytest.approx(2.0)

    def test_without_multiplier_total_equals_per_person(self):
        per_person, total, mult = row_hours(entry([], duration=55 * 60), exact_hours=False)
        assert per_person == pytest.approx(1.0)
        assert total == pytest.approx(1.0)
        assert mult == 1

    def test_exact_hours_skips_rounding(self):
        per_person, total, _ = row_hours(entry(["x2"], duration=20 * 60), exact_hours=True)
        assert per_person == pytest.approx(0.33)
        assert total == pytest.approx(0.66)

    def test_exact_hours_without_multiplier(self):
        per_person, total, _ = row_hours(entry([], duration=90 * 60), exact_hours=True)
        assert per_person == pytest.approx(1.5)
        assert total == pytest.approx(1.5)

    def test_x3_triples(self):
        _, total, mult = row_hours(entry(["x3"], duration=3600), exact_hours=False)
        assert total == pytest.approx(3.0)
        assert mult == 3


class TestFormatMultiplierNote:
    def test_whole_hours_drop_decimals(self):
        assert format_multiplier_note(1.0, 2.0, 2) == "2 hlöä × 1 h, yhteensä 2 h"

    def test_half_hour_uses_finnish_decimal_comma(self):
        assert format_multiplier_note(0.5, 1.0, 2) == "2 hlöä × 0,5 h, yhteensä 1 h"

    def test_two_decimals_use_comma(self):
        assert format_multiplier_note(1.75, 3.5, 2) == "2 hlöä × 1,75 h, yhteensä 3,5 h"

    def test_uses_multiplication_sign_not_letter_x(self):
        note = format_multiplier_note(1.0, 2.0, 2)
        assert "×" in note
        assert "x" not in note

    def test_multiplier_count_is_shown(self):
        assert format_multiplier_note(1.0, 3.0, 3).startswith("3 hlöä")

    def test_no_trailing_zeros(self):
        note = format_multiplier_note(2.0, 4.0, 2)
        assert "2,0" not in note
        assert "4,00" not in note
