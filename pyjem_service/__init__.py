from pigeon import Pigeon
import time
import logging
from PyJEM import TEM3
from math import pi
from threading import RLock


class PyJEMService:
    BEAM_MOVE_TIME = 0.2
    MAG_MODES = {
        "MAG1": 0,
        "MAG2": 1,
        "LM": 2,
    }
    MAG_TABLE = {
        2000: 0,
        2500: 1,
        3000: 2,
        4000: 3,
        5000: 4,
        6000: 5,
        8000: 6,
        10000: 7,
        12000: 8,
        15000: 9,
        20000: 10,
        25000: 11,
        30000: 12,
        40000: 13,
        50000: 14,
        60000: 15,
        80000: 16,
        100000: 17,
        120000: 18,
        150000: 19,
        200000: 20,
        250000: 21,
        300000: 22,
        500000: 23,
        600000: 24,
        800000: 25,
        1000000: 26,
        1200000: 27,
    }
    LOWMAG_TABLE = {
        50: 0,
        100: 1,
        120: 2,
        150: 3,
        200: 4,
        250: 5,
        300: 6,
        400: 7,
        500: 8,
        600: 9,
        800: 10,
        1000: 11,
        1200: 12,
        1500: 13,
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

        self.scope_lock = RLock()

        with self.scope_lock:
            assert TEM3.connect()

        self.eos = TEM3.EOS3()
        self.defl = TEM3.Def3()
        self.apt = TEM3.Apt3()
        self.stage = TEM3.Stage3()
        self.gun = TEM3.GUN3()

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
        with self.scope_lock:
            self.was_in_motion = True
            if msg.x is not None:
                self.stage.SetX(msg.x)
                self.x = msg.x
            if msg.y is not None:
                self.stage.SetY(msg.y)
                self.y = msg.y
            if msg.z is not None:
                self.stage.SetZ(msg.z)
                self.z = msg.z

    def rotation_callback(self, msg):
        with self.scope_lock:
            self.was_in_motion = True
            if msg.angle_x is not None:
                self.stage.SetTiltXAngle(msg.angle_x * 180 / pi)
                self.tx = msg.angle_x
            if msg.angle_y is not None:
                self.stage.SetTiltYAngle(msg.angle_y * 180 / pi)
                self.ty = msg.angle_y

    def scope_callback(self, msg):
        with self.scope_lock:
            if msg.focus is not None:
                self.eos.SetObjFocus(msg.focus - self.focus)
            if msg.brightness is not None:
                self.eos.SetBrightness(msg.brightness - self.brightness)
                self.brightness = msg.brightness
            if msg.mag is not None:
                mag_table = self.LOWMAG_TABLE if msg.mag_mode == "LM" else self.MAG_TABLE
                assert msg.mag in mag_table
                retry = 3
                while retry:
                    try:
                        self.eos.SelectFunctionMode(self.MAG_MODES[msg.mag_mode])
                    except TEM3.TEM3Error as e:
                        self._logger.warning("Timeout error when changing mag mode.")
                        if retry == 1:
                            raise e
                    finally:
                        retry -= 1
                self.eos.SetSelector(mag_table[msg.mag])
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
        with self.scope_lock:
            self.connection.send(
                "scope.status",
                focus=self.focus,
                aperture=None,
                mag_mode="MAG" if self.eos.GetFunctionMode()[0] < 2 else "LM",
                mag=self.eos.GetMagValue()[0],
                tank_voltage=self.gun.GetHtCurrentValue()[0],
                spot_size=self.eos.GetSpotSize(),
                beam_offset=self.defl.GetCLA1(),
                screen="down" if self.defl.GetBeamBlank() else "up",
                brightness=self.brightness,
            )
            self.last_scope_status = time.time()

    def stage_status(self):
        with self.scope_lock:
            x, y, z, tx, ty = self.stage.GetPos()
            self.connection.send(
                "stage.motion.status",
                x=int(x),
                y=int(y),
                z=int(z),
                in_motion=(in_motion:=self.in_motion),
            )
            self.connection.send(
                "stage.rotation.status",
                angle_x=tx * pi / 180,
                angle_y=ty * pi / 180,
                eucentric_height=0,
                in_motion=in_motion,
            )
            self.last_stage_status = time.time()

    @property
    def in_motion(self):
        with self.scope_lock:
            x, y, z, tx, ty = self.stage.GetPos()
            return any(
                [
                    abs(s - p) > self.trans_tol
                    for s, p in zip((self.x, self.y, self.z), (x, y, z))
                ]
                + [abs(s - p) > self.rot_tol for s, p in zip((self.tx, self.ty), (tx, ty))]
            )

    def run_once(self):
        period = 1 / 50 if (in_motion:=self.in_motion) or self.was_in_motion else 1
        self.was_in_motion = in_motion
        if time.time() - self.last_stage_status > period:
            self.stage_status()
        if time.time() - self.last_scope_status > 1:
            self.scope_status()

    def run(self):
        while True:
            self.run_once()
            time.sleep(0.01)
