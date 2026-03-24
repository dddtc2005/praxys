from sync.stryd_sync import _workout_type_from_name


def test_workout_type_from_name():
    assert _workout_type_from_name("Day 46 - Steady Aerobic") == "steady aerobic"
    assert _workout_type_from_name("Day 48 - Long") == "long"
    assert _workout_type_from_name("Day 47 - Recovery") == "recovery"
    assert _workout_type_from_name("Custom Name") == "custom name"
