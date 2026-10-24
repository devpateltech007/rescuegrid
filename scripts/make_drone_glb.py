"""Generate a small quadcopter glTF binary (GLB) procedurally — no external model assets.
glTF is Y-up; Cesium rotates Y-up to Z-up and treats +X as forward.
Output: frontend/public/models/drone.glb
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "models" / "drone.glb"


def box(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0, rot_y=0.0):
    x, y, z = sx / 2, sy / 2, sz / 2
    faces = [((1, 0, 0), [(x, -y, -z), (x, y, -z), (x, y, z), (x, -y, z)]),
             ((-1, 0, 0), [(-x, -y, z), (-x, y, z), (-x, y, -z), (-x, -y, -z)]),
             ((0, 1, 0), [(-x, y, -z), (-x, y, z), (x, y, z), (x, y, -z)]),
             ((0, -1, 0), [(-x, -y, z), (-x, -y, -z), (x, -y, -z), (x, -y, z)]),
             ((0, 0, 1), [(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]),
             ((0, 0, -1), [(x, -y, -z), (-x, -y, -z), (-x, y, -z), (x, y, -z)])]
    P, N, I = [], [], []
    c, s = math.cos(rot_y), math.sin(rot_y)
    for n, quad in faces:
        b = len(P)
        for vx, vy, vz in quad:
            P.append((vx * c + vz * s + cx, vy + cy, -vx * s + vz * c + cz))
            N.append((n[0] * c + n[2] * s, n[1], -n[0] * s + n[2] * c))
        I += [b, b + 1, b + 2, b, b + 2, b + 3]
    return P, N, I


def cylinder(r, h, cx, cy, cz, seg=24):
    P, N, I = [], [], []
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        for (a, b) in ((a0, a1),):
            p0 = (cx + r * math.cos(a), cy - h / 2, cz + r * math.sin(a))
            p1 = (cx + r * math.cos(b), cy - h / 2, cz + r * math.sin(b))
            p2 = (cx + r * math.cos(b), cy + h / 2, cz + r * math.sin(b))
            p3 = (cx + r * math.cos(a), cy + h / 2, cz + r * math.sin(a))
            base = len(P)
            na, nb = (math.cos(a), 0, math.sin(a)), (math.cos(b), 0, math.sin(b))
            P += [p0, p1, p2, p3]
            N += [na, nb, nb, na]
            I += [base, base + 2, base + 1, base, base + 3, base + 2]
            # caps
            t = len(P)
            P += [(cx, cy + h / 2, cz), p3, p2, (cx, cy - h / 2, cz), p0, p1]
            N += [(0, 1, 0)] * 3 + [(0, -1, 0)] * 3
            I += [t, t + 2, t + 1, t + 3, t + 4, t + 5]
    return P, N, I


def merge(parts):
    P, N, I = [], [], []
    for p, n, i in parts:
        b = len(P)
        P += p
        N += n
        I += [x + b for x in i]
    return P, N, I


def build():
    arm = 0.62
    meshes = {
        "body": (merge([box(0.42, 0.14, 0.30), box(0.22, 0.08, 0.18, cy=0.11), box(0.10, 0.10, 0.10, cx=0.24, cy=-0.07)]),
                 {"baseColorFactor": [0.13, 0.15, 0.18, 1], "metallicFactor": 0.6, "roughnessFactor": 0.4}),
        "arms": (merge([box(arm * 2, 0.05, 0.06, rot_y=math.radians(45)), box(arm * 2, 0.05, 0.06, rot_y=math.radians(-45))]),
                 {"baseColorFactor": [0.2, 0.22, 0.25, 1], "metallicFactor": 0.5, "roughnessFactor": 0.5}),
        "motors": (merge([cylinder(0.06, 0.08, arm * math.cos(a) / math.sqrt(1), 0.05, arm * math.sin(a)) for a in
                          (math.radians(45), math.radians(135), math.radians(225), math.radians(315))]),
                   {"baseColorFactor": [0.75, 0.75, 0.78, 1], "metallicFactor": 0.9, "roughnessFactor": 0.3}),
        "rotors": (merge([cylinder(0.27, 0.012, arm * math.cos(a), 0.10, arm * math.sin(a), seg=32) for a in
                          (math.radians(45), math.radians(135), math.radians(225), math.radians(315))]),
                   {"baseColorFactor": [0.8, 0.9, 1.0, 0.35], "metallicFactor": 0, "roughnessFactor": 0.2, "alpha": True}),
        "leds": (merge([box(0.05, 0.03, 0.05, cx=arm * math.cos(a), cy=0.0, cz=arm * math.sin(a)) for a in
                        (math.radians(45), math.radians(315))] +
                       [box(0.05, 0.03, 0.05, cx=arm * math.cos(a), cy=0.0, cz=arm * math.sin(a)) for a in
                        (math.radians(135), math.radians(225))]),
                 {"baseColorFactor": [1, 1, 1, 1], "emissive": [0.2, 1.0, 0.9]}),
        "sensor": (cylinder(0.07, 0.09, 0.2, -0.15, 0.0),
                   {"baseColorFactor": [0.05, 0.05, 0.06, 1], "emissive": [0.0, 0.6, 0.8]}),
    }
    bin_ = bytearray()
    accessors, views, gl_meshes, materials, nodes = [], [], [], [], []

    def add_view(data: bytes, target: int):
        while len(bin_) % 4:
            bin_.append(0)
        off = len(bin_)
        bin_.extend(data)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        return len(views) - 1

    for name, ((P, N, I), mat) in meshes.items():
        p = np.array(P, np.float32)
        n = np.array(N, np.float32)
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
        idx = np.array(I, np.uint16)
        vp = add_view(p.tobytes(), 34962)
        vn = add_view(n.tobytes(), 34962)
        vi = add_view(idx.tobytes(), 34963)
        accessors += [
            {"bufferView": vp, "componentType": 5126, "count": len(p), "type": "VEC3", "min": p.min(0).tolist(), "max": p.max(0).tolist()},
            {"bufferView": vn, "componentType": 5126, "count": len(n), "type": "VEC3"},
            {"bufferView": vi, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ]
        m = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": mat["baseColorFactor"],
                                                     "metallicFactor": mat.get("metallicFactor", 0.2),
                                                     "roughnessFactor": mat.get("roughnessFactor", 0.6)},
             "doubleSided": True}
        if "emissive" in mat:
            m["emissiveFactor"] = mat["emissive"]
        if mat.get("alpha"):
            m["alphaMode"] = "BLEND"
        materials.append(m)
        a = len(accessors) - 3
        gl_meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": a, "NORMAL": a + 1}, "indices": a + 2,
                                                        "material": len(materials) - 1}]})
        nodes.append({"mesh": len(gl_meshes) - 1, "name": name})
    gltf = {"asset": {"version": "2.0", "generator": "RESCUEGRID3D make_drone_glb.py"},
            "scene": 0, "scenes": [{"nodes": [len(nodes)]}],
            "nodes": nodes + [{"name": "quadcopter", "children": list(range(len(nodes)))}],
            "meshes": gl_meshes, "materials": materials, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(bin_)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    while len(bin_) % 4:
        bin_.append(0)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + \
        struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(out)
    print(f"wrote {OUT} ({len(out)} bytes)")


if __name__ == "__main__":
    build()
