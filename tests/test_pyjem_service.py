from __future__ import annotations

from math import cos, pi
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from pyjem_service import PyJEMService


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("pyjem_service.time.sleep", return_value=None):
        yield


@pytest.fixture
def service():
    with patch("pyjem_service.TEM3") as tem3, patch("pyjem_service.Pigeon") as pigeon:
        tem3.connect.return_value = True
        tem3.TEM3Error = RuntimeError
        tem3.EOS3.return_value = MagicMock()
        tem3.Def3.return_value = MagicMock()
        tem3.Apt3.return_value = MagicMock()
        tem3.Stage3.return_value = MagicMock()
        tem3.GUN3.return_value = MagicMock()
        tem3.Stage3.return_value.GetPos.return_value = (100, 200, 300, 45, 30)

        connection = MagicMock()
        pigeon.return_value = connection

        svc = PyJEMService()
        svc.connection = connection
        yield svc


def test_init_sets_state_and_subscribes():
    with patch("pyjem_service.TEM3") as tem3, patch("pyjem_service.Pigeon") as pigeon:
        tem3.connect.return_value = True
        tem3.TEM3Error = RuntimeError
        tem3.EOS3.return_value = MagicMock()
        tem3.Def3.return_value = MagicMock()
        tem3.Apt3.return_value = MagicMock()
        tem3.Stage3.return_value = MagicMock()
        tem3.GUN3.return_value = MagicMock()
        tem3.Stage3.return_value.GetPos.return_value = (1, 2, 3, 10, 20)

        connection = MagicMock()
        pigeon.return_value = connection

        svc = PyJEMService(host="host", port=1234, username="u", password="p")

    assert svc.x == 1
    assert svc.y == 2
    assert svc.z == 3
    assert svc.tx == pytest.approx(10 * pi / 180)
    assert svc.ty == pytest.approx(20 * pi / 180)
    assert connection.connect.called
    connection.subscribe.assert_has_calls([
        call("stage.motion.command", svc.motion_callback),
        call("stage.rotation.command", svc.rotation_callback),
        call("scope.command", svc.scope_callback),
    ])


def test_motion_callback_updates_stage_and_state(service):
    service.tx = pi / 3
    service.ty = pi / 4

    service.motion_callback(SimpleNamespace(x=10, y=20, z=30))

    service.stage.SetX.assert_called_once_with(10 / cos(pi / 3))
    service.stage.SetY.assert_called_once_with(20 / cos(pi / 4))
    service.stage.SetZ.assert_called_once_with(30)
    assert service.x == pytest.approx(10 / cos(pi / 3))
    assert service.y == pytest.approx(20 / cos(pi / 4))
    assert service.z == 30
    assert service.was_in_motion is True


def test_rotation_callback_updates_stage_and_state(service):
    service.rotation_callback(SimpleNamespace(angle_x=pi / 6, angle_y=pi / 3))

    service.stage.SetTiltXAngle.assert_called_once()
    service.stage.SetTiltYAngle.assert_called_once()
    assert service.stage.SetTiltXAngle.call_args.args[0] == pytest.approx(30)
    assert service.stage.SetTiltYAngle.call_args.args[0] == pytest.approx(60)
    assert service.tx == pytest.approx(pi / 6)
    assert service.ty == pytest.approx(pi / 3)
    assert service.was_in_motion is True


def test_scope_callback_applies_relative_updates_and_status(service):
    service.focus = 100
    service.brightness = 10
    service.scope_status = MagicMock()

    service.scope_callback(
        SimpleNamespace(
            focus=125,
            brightness=25,
            mag=None,
            mag_mode=None,
            spot_size=None,
            beam_offset=None,
            screen=None,
        )
    )

    service.eos.SetObjFocus.assert_called_once_with(25)
    service.eos.SetBrightness.assert_called_once_with(15)
    assert service.focus == 125
    assert service.brightness == 25
    service.scope_status.assert_called_once()


def test_scope_callback_changes_mag_mode_and_selector(service):
    service.eos.SelectFunctionMode = MagicMock()
    service.eos.SetSelector = MagicMock()
    service.scope_status = MagicMock()

    service.scope_callback(
        SimpleNamespace(
            focus=None,
            brightness=None,
            mag=50000,
            mag_mode="MAG",
            spot_size=None,
            beam_offset=None,
            screen=None,
        )
    )

    service.eos.SelectFunctionMode.assert_called_once_with(service.MAG_MODES["MAG1"])
    service.eos.SetSelector.assert_called_once_with(service.MAG_TABLE[50000])


def test_scope_callback_retries_mag_mode_changes(service):
    service.scope_status = MagicMock()
    service.eos.SelectFunctionMode.side_effect = [
        RuntimeError("timeout"),
        RuntimeError("timeout"),
        None,
    ]
    service._logger.warning = MagicMock()

    service.scope_callback(
        SimpleNamespace(
            focus=None,
            brightness=None,
            mag=50000,
            mag_mode="MAG",
            spot_size=None,
            beam_offset=None,
            screen=None,
        )
    )

    assert service.eos.SelectFunctionMode.call_count == 3
    assert service._logger.warning.call_count == 2


def test_scope_callback_updates_beam_controls(service):
    service.scope_status = MagicMock()

    service.scope_callback(
        SimpleNamespace(
            focus=None,
            brightness=None,
            mag=None,
            mag_mode=None,
            spot_size=2,
            beam_offset=(1, 2),
            screen="down",
        )
    )

    service.eos.SelectSpotSize.assert_called_once_with(2)
    service.defl.SetCLA1.assert_called_once_with(1, 2)
    service.defl.SetBeamBlank.assert_called_once_with(True)


def test_scope_status_sends_expected_payload(service):
    service.eos.GetFunctionMode.return_value = (0,)
    service.eos.GetMagValue.return_value = (50000,)
    service.gun.GetHtCurrentValue.return_value = (1000,)
    service.eos.GetSpotSize.return_value = 3
    service.defl.GetCLA1.return_value = (7, 8)
    service.defl.GetBeamBlank.return_value = False

    service.scope_status()

    service.connection.send.assert_called_once_with(
        "scope.status",
        focus=service.focus,
        aperture=None,
        mag_mode="MAG",
        mag=50000,
        tank_voltage=1000,
        spot_size=3,
        beam_offset=(7, 8),
        screen="up",
        brightness=service.brightness,
    )


def test_stage_status_sends_expected_payload(service):
    service.stage.GetPos.return_value = (100, 200, 300, 45, 30)

    service.stage_status()

    assert service.connection.send.call_args_list == [
        call(
            "stage.motion.status",
            x=70,
            y=173,
            z=300,
            in_motion=False,
            calibrated=True,
        ),
        call(
            "stage.rotation.status",
            angle_x=45 * pi / 180,
            angle_y=30 * pi / 180,
            eucentric_height=0,
            in_motion=False,
        ),
        call(
            "stage.aperture.status",
            current_aperture=0,
            calibrated=True,
        ),
    ]


@pytest.mark.parametrize(
    "current, target, trans_tol, rot_tol, expected",
    [
        ((100, 200, 300, 0, 0), (100, 200, 300, 0, 0), 1, 0.1, False),
        ((101.5, 200, 300, 0, 0), (100, 200, 300, 0, 0), 1, 0.1, True),
        ((100, 200, 300, 10, 0), (100, 200, 300, 0, 0), 1, 0.1, True),
    ],
)
def test_in_motion_detection(service, current, target, trans_tol, rot_tol, expected):
    service.stage.GetPos.return_value = current
    service.x, service.y, service.z, service.tx, service.ty = target
    service.trans_tol = trans_tol
    service.rot_tol = rot_tol

    assert service.in_motion is expected


def test_run_once_calls_status_methods_when_due(service):
    service.stage.GetPos.return_value = (140, 200, 300, 45, 30)
    service.trans_tol = 1
    service.last_stage_status = 0
    service.last_scope_status = 0
    service.stage_status = MagicMock()
    service.scope_status = MagicMock()

    with patch("pyjem_service.time.time", return_value=100.0):
        service.run_once()

    service.stage_status.assert_called_once()
    service.scope_status.assert_called_once()
    assert service.was_in_motion is True


def test_run_once_skips_status_when_recently_updated(service):
    service.stage.GetPos.return_value = (100, 200, 300, 45, 30)
    service.last_stage_status = 99.8
    service.last_scope_status = 99.5
    service.stage_status = MagicMock()
    service.scope_status = MagicMock()

    with patch("pyjem_service.time.time", return_value=100.0):
        service.run_once()

    service.stage_status.assert_not_called()
    service.scope_status.assert_not_called()
