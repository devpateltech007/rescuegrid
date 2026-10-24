"""Simulated reconnaissance drone: waypoint following with terrain-relative altitude,
flight state machine and a simple battery model. Parameters are SIMULATION values, not
approved flight plans or operational safety limits."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.models.schemas import FlightState


@dataclass
class Waypoint:
    x: float
    y: float
    agl: float = 40.0
    action: str = "survey"         # survey | inspect | transit | land
    hold_s: float = 0.0
    target: tuple[float, float] | None = None
    label: str = ""
    task_id: str | None = None
    close_inspection: bool = False


@dataclass
class DroneConfig:
    drone_id: str
    callsign: str
    role: str
    color: str
    sector_id: str
    cruise_mps: float = 7.0
    climb_mps: float = 3.0
    survey_agl_m: float = 40.0
    fov_deg: float = 70.0
    battery_wh: float = 75.0
    cruise_w: float = 165.0
    hover_w: float = 185.0
    climb_w: float = 230.0
    scan_interval_s: float = 1.0


@dataclass
class Drone:
    cfg: DroneConfig
    home: tuple[float, float]
    plan: list[Waypoint]
    state: FlightState = FlightState.IDLE
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0           # MSL
    ground: float = 0.0
    heading: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    speed: float = 0.0
    wp: int = 0
    hold_left: float = 0.0
    consumed_wh: float = 0.0
    scans: int = 0
    distance_m: float = 0.0
    task: str = "Awaiting launch"
    pending_capture: Waypoint | None = None
    events: list[dict] = field(default_factory=list)
    sensor_mode: str = "STANDBY"
    camera_pitch: float = -90.0
    camera_target: tuple[float, float] | None = None

    @property
    def battery_pct(self) -> float:
        return max(0.0, 100.0 * (1 - self.consumed_wh / self.cfg.battery_wh))

    def insert_task(self, wps: list[Waypoint]) -> None:
        """Insert waypoints immediately after the current one (retasking)."""
        if self.state in (FlightState.COMPLETE, FlightState.RETURNING, FlightState.IDLE):
            # rejoin: put tasks before the final landing leg
            idx = max(0, len(self.plan) - 1)
            self.plan[idx:idx] = wps
            self.wp = min(self.wp, idx)
            if self.state in (FlightState.COMPLETE, FlightState.RETURNING):
                self.state = FlightState.SURVEYING if self.state == FlightState.RETURNING else FlightState.TAKEOFF
        else:
            self.plan[self.wp:self.wp] = wps

    def step(self, dt: float, ground_fn) -> None:
        """Advance dt seconds. ground_fn(x, y) -> true surface height under the drone."""
        self.events.clear()
        self.ground = ground_fn(self.x, self.y)
        if self.state in (FlightState.IDLE, FlightState.COMPLETE):
            self.speed, self.sensor_mode = 0.0, "STANDBY"
            return
        if self.state == FlightState.TAKEOFF:
            target_z = self.ground + self.cfg.survey_agl_m
            self.z = min(target_z, self.z + self.cfg.climb_mps * dt)
            self.speed, self.pitch, self.sensor_mode = 0.0, 0.0, "LIDAR+EO"
            self.consumed_wh += self.cfg.climb_w * dt / 3600
            self.task = "Climbing to survey altitude"
            if self.z >= target_z - 0.05:
                self.state = FlightState.SURVEYING
            return
        if self.wp >= len(self.plan):
            self.state = FlightState.COMPLETE
            return
        w = self.plan[self.wp]
        if self.hold_left > 0:
            self.hold_left -= dt
            self.speed, self.pitch = 0.0, 0.0
            self.roll *= 0.5
            if w.target:
                self.heading = math.degrees(math.atan2(w.target[0] - self.x, w.target[1] - self.y)) % 360
            self._alt(dt, w.agl)
            self.consumed_wh += self.cfg.hover_w * dt / 3600
            if self.hold_left <= 0:
                self._advance()
            return
        dx, dy = w.x - self.x, w.y - self.y
        dist = math.hypot(dx, dy)
        v = self.cfg.cruise_mps * (0.6 if w.action == "inspect" and dist < 30 else 1.0)
        if w.action == "land":
            self.state = FlightState.RETURNING
            self.task = "Returning to staging"
        elif self.state == FlightState.RETURNING:
            pass
        elif w.action == "inspect":
            self.state = FlightState.INSPECTING
            self.task = w.label or "Inspecting target"
        else:
            self.state = FlightState.SURVEYING
            self.task = w.label or "Corridor survey"
        if dist < max(v * dt, 0.5):
            self.x, self.y = w.x, w.y
            self.distance_m += dist
            self.events.append({"type": "drone.waypoint_reached", "waypoint": self.wp, "label": w.label, "action": w.action})
            if w.action == "inspect" and w.target:
                self.pending_capture = w
            if w.action == "land":
                # descend and finish
                self.z = self.ground + 0.3
                self.state = FlightState.COMPLETE
                self.task = "Landed at staging"
                self.speed = 0
                self.wp += 1
                return
            if w.hold_s > 0:
                self.hold_left = w.hold_s
            else:
                self._advance()
            self.consumed_wh += self.cfg.hover_w * dt / 3600
            return
        new_heading = math.degrees(math.atan2(dx, dy)) % 360
        turn = ((new_heading - self.heading + 540) % 360) - 180
        max_turn = 45 * dt
        turn_applied = max(-max_turn, min(max_turn, turn))
        self.heading = (self.heading + turn_applied) % 360
        self.roll = max(-25, min(25, turn_applied * 0.6 / max(dt, 1e-3)))
        self.pitch = -8.0 * (v / self.cfg.cruise_mps)
        step = v * dt
        h = math.radians(self.heading)
        # move along the heading but snap towards the waypoint to avoid orbiting
        mx, my = math.sin(h) * step, math.cos(h) * step
        if abs(turn) < 60:
            mx, my = dx / dist * step, dy / dist * step
        self.x += mx
        self.y += my
        self.distance_m += step
        self.speed = v
        self._alt(dt, w.agl)
        self.consumed_wh += self.cfg.cruise_w * dt / 3600

    def _alt(self, dt: float, agl: float) -> None:
        target = self.ground + agl
        dz = target - self.z
        lim = self.cfg.climb_mps * dt
        self.z += max(-lim, min(lim, dz))
        self.z = max(self.z, self.ground + 8)  # never descend below 8 m AGL in flight

    def _advance(self) -> None:
        self.wp += 1
        if self.wp >= len(self.plan):
            self.state = FlightState.COMPLETE
