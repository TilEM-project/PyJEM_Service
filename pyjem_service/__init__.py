from pigeon import Pigeon
import time
import logging
from PyJEM import TEM3
from math import pi


class PyJEMService:
    BEAM_MOVE_TIME = 0.2
    MAG_MODES = {
        "MAG1": 0,
        "MAG2": 1,
        "LM": 2,
    }
    MAG_TABLE = {
        2000: 5,
    }
    LOWMAG_TABLE = {
        50: 0,
    }

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 61616,
        username: str = None,
        password: str = None,
        logger: logging.Logger = None,
        trans_tol: int = 60,
        rot_tol: float = 0.2 * pi / 180,
    ):
        self._logger = logger if logger is not None else logging.getLogger(__name__)

        self.trans_tol = trans_tol
        self.rot_tol = rot_tol

        assert TEM3.connect()

        self.eos = TEM3.EOS3()
        self.defl = TEM3.Def3()
        self.apt = TEM3.Apt3()
        self.stage = TEM3.Stage3()
        self.gun = TEM3.Gun3()

        self.was_in_motion = False
        self.focus = 0
        self.brightness = 0

        self.x, self.y, self.z, tx, ty = self.stage.GetPos()
        self.tx = tx * pi / 180
        self.ty = ty * pi / 180

        self.last_stage_status = time.time()
        self.last_scope_status = time.time()

        self.connection = Pigeon("pyjem_service", host=host, port=port)
        self.connection.connect(username=username, password=password)
        self.connection.subscribe("stage.motion.command", self.motion_callback)
        self.connection.subscribe("stage.rotation.command", self.rotation_callback)
        self.connection.subscribe("scope.command", self.scope_callback)

    def motion_callback(self, msg):
        self.was_in_motion = True
        self.stage.SetX(msg.x)
        self.x = msg.x
        self.stage.SetY(msg.y)
        self.y = msg.y
        self.stage.SetZ(msg.z)
        self.z = msg.z

    def rotation_callback(self, msg):
        self.was_in_motion = True
        self.stage.SetTiltXAngle(msg.angle_x * 180 / pi)
        self.tx = msg.angle_x
        self.stage.SetTiltYAngle(msg.angle_y * 180 / pi)
        self.ty = msg.angle_y

    def scope_callback(self, msg):
        if msg.focus is not None:
            self.eos.SetObjFocus(msg.focus - self.focus)
        if msg.brightness is not None:
            self.eos.SetBrightness(msg.brightness - self.brightness)
            self.brightness = msg.brightness
        if msg.mag is not None:
            mag_table = self.LOWMAG_TABLE if msg.mag_mode == "LM" else self.MAG_TABLE
            assert msg.mag in mag_table
            self.eos.SelectFunctionMode(self.MAG_MODES[msg.mag_mode])
            self.eos.SetSelector(mag_table[mag.mag])
        if msg.spot_size is not None:
            self.eos.SelectSpotSize(msg.spot_size)
        if msg.beam_offset is not None:
            self.defl.SetCLA1(*msg.beam_offset)
        if msg.screen is not None:
            self.defl.SetBeamBlank(msg.screen == "down")
        time.sleep(self.BEAM_MOVE_TIME)
        if msg.focus is not None:
            self.focus = msg.focus
        if msg.brightness is not None:
            self.brightness = msg.brightness
        self.scope_status()

    def scope_status(self):
        self.connection.send(
            "scope.status",
            focus=self.focus,
            aperture=None,
            mag_mode="MAG" if self.eos.GetFunctionMode() < 2 else "LM",
            mag=self.eos.GetMagValue()[0],
            tank_voltage=self.gun.GetHtCurrentValue()[0],
            spot_size=self.eos.GetSpotSize(),
            beam_offset=self.defl.GetCLA1(),
            screen="down" if self.defl.GetBeamBlank() else "up",
        )
        self.last_scope_status = time.time()

    def stage_status(self):
        x, y, z, tx, ty = GetPos()
        self.connection.send(
            "stage.motion.status",
            x=x,
            y=y,
            z=z,
            in_motion=in_motion:=self.in_motion,
        )
        self.connection.send(
            "stage.rotation.status",
            angle_x=tx * pi / 180,
            angle_y=ty * pi / 180,
            in_motion=in_motion,
        )
        self.last_stage_status = time.time()

    @property
    def in_motion(self):
        x, y, z, tx, ty = GetPos()
        return any(
            [
                abs(s - p) > self.trans_tol
                for s, p in zip((self.x, self.y, self.z), (x, y, z))
            ]
            + [abs(s - p) > self.rot_tol for s, p in zip((self.tx, self.ty), (tx, ty))]
        )

    def run_once(self):
        period = 1 / 50 if in_motion:=self.in_motion or self.was_in_motion else 1
        self.was_in_motion = in_motion
        if time.time() - self.last_stage_status > period:
            self.stage_status()
        if time.time() - self.last_scope_status > 1:
            self.scope_status()

    def run(self):
        while True:
            self.run_once()
            time.sleep(0.01)
