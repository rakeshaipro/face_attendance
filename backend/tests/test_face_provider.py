"""Tests for the face provider's pose parsing (SRS §3.3.5).

The real InsightFace model isn't available in CI, so we unit-test the
pure parsing helper that maps its raw ``face.pose`` array onto the
project's yaw/pitch sign convention. This guards against the regression
where step 2 (turn left) and steps 4/5 (tilt up/down) were always
rejected with "Face pose not in target range".
"""
from __future__ import annotations

from app.engine.face_provider import parse_insightface_pose
from app.engine.pose import pose_in_range


def test_parses_pitch_yaw_roll_order():
    # InsightFace pose = [pitch, yaw, roll]. Pitch passes through unchanged
    # (its sign already matches the protocol); yaw is negated.
    yaw, pitch, roll = parse_insightface_pose([5.0, -10.0, 2.0])
    assert pitch == 5.0    # pose[0] unchanged
    assert yaw == 10.0     # pose[1] negated
    assert roll == 2.0     # pose[2] unchanged


def test_left_turn_lands_in_step2_range():
    # A real left turn reports positive yaw in InsightFace's convention.
    # After parsing it must be negative to satisfy step 2 (yaw in [-45,-30]).
    yaw, _pitch, _roll = parse_insightface_pose([0.0, 38.0, 0.0])
    assert -45 <= yaw <= -30
    assert pose_in_range(2, yaw, 0.0)


def test_tilt_up_lands_in_step4_range():
    # Tilting up reports positive pitch in InsightFace's convention, which
    # already matches the protocol (step 4 pitch in [20,35]); it is NOT
    # negated. Passing a negative raw pitch (tilt down) must NOT satisfy step 4.
    _yaw, pitch, _roll = parse_insightface_pose([28.0, 0.0, 0.0])
    assert 20 <= pitch <= 35
    assert pose_in_range(4, 0.0, pitch)

    _yaw, pitch_down, _roll = parse_insightface_pose([-28.0, 0.0, 0.0])
    assert not pose_in_range(4, 0.0, pitch_down)


def test_handles_missing_or_short_pose():
    assert parse_insightface_pose(None) == (None, None, None)
    assert parse_insightface_pose([1.0]) == (None, None, None)
    assert parse_insightface_pose([]) == (None, None, None)
