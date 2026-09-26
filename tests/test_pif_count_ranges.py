from sqlalchemy import create_engine, literal, select

from app.services.pif_count_ranges import count_ranges_condition


def _matches(value: int, ranges: list[str]) -> bool:
    engine = create_engine("sqlite://")
    condition = count_ranges_condition(literal(value), ranges)
    with engine.connect() as connection:
        return connection.execute(select(literal(True)).where(condition)).scalar() is True


def test_count_ranges_are_combined_as_a_union():
    ranges = ["1-5", "11-25"]

    assert _matches(1, ranges)
    assert _matches(17, ranges)
    assert not _matches(8, ranges)
    assert not _matches(26, ranges)


def test_count_ranges_support_zero_and_open_ended_buckets():
    ranges = ["0-0", "101+"]

    assert _matches(0, ranges)
    assert _matches(101, ranges)
    assert _matches(500, ranges)
    assert not _matches(1, ranges)
