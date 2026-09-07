"""perception.py -- BRAIN perception stage. Runs in the ONE perception thread, never on the loop.

ArUco (always; OpenCV objdetect, no contrib needed)
+ rocks   (YOLO via ultralytics if importable, else a saturation-blob fallback)
+ novelty (torchvision resnet18 embedding if torch importable, else a histogram/texture
           signature) against a running NoveltyMemory.
Same Detection shape either way, so policy.py and the audit record never care which
backend is present. `python main.py --no-yolo --no-torch` runs the whole loop on CPU.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger("perception")


@dataclass
class Observation:
    header: dict
    jpeg: bytes
    recv_real: float


@dataclass
class Detection:
    id: str
    kind: str            # marker | rock | anomaly
    label: str
    conf: float
    bbox: tuple          # x0, y0, x1, y1 px
    bearing_deg: float
    est_range_m: float
    novelty: float = 0.0


@dataclass
class PerceptionResult:
    seq: int
    sim_time: float
    header: dict
    recv_real: float
    detections: list
    thumbnail_jpeg: bytes
    crops: list                       # [(id, novelty, jpeg_bytes)] best-first
    embeddings: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    dropped_before: int = 0
    backend: str = ""


class NoveltyMemory:
    """Running memory of embeddings. novelty = clip((1 - max cosine sim) / scale).
    Habituation is free: the fifth identical striped rock scores ~0 because the first is in here."""

    def __init__(self, cap: int, scale: float) -> None:
        self.cap, self.scale = cap, scale
        self._vecs: list[np.ndarray] = []
        self._lock = threading.Lock()

    def novelty(self, v: np.ndarray) -> float:
        with self._lock:
            if not self._vecs:
                return 1.0
            M = np.stack(self._vecs)
        sim = float((M @ v).max())
        return float(np.clip((1.0 - sim) / self.scale, 0.0, 1.0))

    def add(self, v: np.ndarray) -> None:
        with self._lock:
            self._vecs.append(v)
            if len(self._vecs) > self.cap:
                self._vecs.pop(0)

    def __len__(self) -> int:
        return len(self._vecs)


class HistEmbedder:
    """Fallback signature: HSV histograms + gradient/texture stats. Not a CNN, but it makes
    novelty-as-distance-from-memory real (and habituation observable) with zero downloads."""
    name = "hist"
    default_scale = 0.12

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).ravel()
        s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).ravel()
        v = cv2.calcHist([hsv], [2], None, [8], [0, 256]).ravel()
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gx, gy = cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)
        tex = np.array([np.abs(gx).mean(), np.abs(gy).mean(), gray.std(),
                        cv2.Laplacian(gray, cv2.CV_32F).std()], np.float32)
        parts = [h / (h.sum() + 1e-6), s / (s.sum() + 1e-6), v / (v.sum() + 1e-6), tex / (tex.sum() + 1e-6)]
        vec = np.concatenate(parts).astype(np.float32)
        return vec / (np.linalg.norm(vec) + 1e-9)


class TorchEmbedder:
    """torchvision resnet18 (ImageNet weights, downloaded once), classifier head removed -> 512-d."""
    name = "resnet18"
    default_scale = 0.5

    def __init__(self, device: str) -> None:
        import torch
        from torchvision.models import ResNet18_Weights, resnet18
        w = ResNet18_Weights.DEFAULT
        m = resnet18(weights=w)
        m.fc = torch.nn.Identity()
        if device.startswith("cuda") and not torch.cuda.is_available():
            log.warning("CUDA requested but torch.cuda.is_available() is False -> cpu")
            device = "cpu"
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        self.device = device
        self.m = m.eval().to(device)
        self.tf = w.transforms()
        self.torch = torch

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        from PIL import Image
        img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        with self.torch.inference_mode():
            x = self.tf(img).unsqueeze(0).to(self.device)
            v = self.m(x)[0].float().cpu().numpy()
        return v / (np.linalg.norm(v) + 1e-9)


class Tracker:
    """Stable ids across frames by bearing proximity. Deliberately tiny."""

    def __init__(self, max_gap_frames: int = 10, max_dbearing: float = 6.0) -> None:
        self.tracks: dict[str, dict] = {}
        self.n, self.max_gap, self.max_db = 0, max_gap_frames, max_dbearing

    def match(self, bearing: float, seq: int) -> str | None:
        best, bd = None, self.max_db
        for tid, t in self.tracks.items():
            if seq - t["seq"] <= self.max_gap and abs(t["bearing"] - bearing) < bd:
                best, bd = tid, abs(t["bearing"] - bearing)
        return best

    def new_id(self, kind: str) -> str:
        self.n += 1
        return f"{'A' if kind == 'anomaly' else 'R'}{self.n:02d}"

    def update(self, tid: str, bearing: float, rng: float, seq: int, kind: str) -> None:
        self.tracks[tid] = {"bearing": bearing, "range": rng, "seq": seq, "kind": kind}

    def expire(self, seq: int) -> list[str]:
        gone = [tid for tid, t in self.tracks.items() if seq - t["seq"] > self.max_gap]
        for tid in gone:
            del self.tracks[tid]
        return gone


def _iou(a: tuple, b: tuple) -> float:
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class Perceiver:
    def __init__(self, pcfg: dict, use_yolo: bool = True, use_torch: bool = True) -> None:
        self.cfg = pcfg
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, pcfg["aruco_dict"]))
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.aruco = cv2.aruco.ArucoDetector(dictionary, params)
        self.yolo = None
        if use_yolo:
            try:
                from ultralytics import YOLO
                self.yolo = YOLO(pcfg["yolo_weights"])
                log.info("YOLO loaded: %s (%d classes)", pcfg["yolo_weights"], len(self.yolo.names))
            except Exception as e:
                log.warning("YOLO unavailable (%s) -> saturation-blob fallback for rocks", e)
        self.embedder = None
        if use_torch and pcfg.get("embedder", "auto") in ("auto", "resnet18"):
            try:
                self.embedder = TorchEmbedder(pcfg["device"])
            except Exception as e:
                log.warning("torch embedder unavailable (%s) -> histogram signature", e)
        if self.embedder is None:
            self.embedder = HistEmbedder()
        scale = pcfg["novelty_scale"] if self.embedder.name == "resnet18" else HistEmbedder.default_scale
        self.memory = NoveltyMemory(pcfg["memory_cap"], scale)
        self.tracker = Tracker()
        self.last_embeddings: dict[str, np.ndarray] = {}
        self.backend = f"aruco+{'yolo' if self.yolo else 'blobs'}+{self.embedder.name}"
        log.info("perception backend: %s", self.backend)

    def commit(self, tid: str) -> None:
        """Called by the policy on 'investigate': the thing is now in memory -> habituation."""
        v = self.last_embeddings.get(tid)
        if v is not None:
            self.memory.add(v)

    # ---- runs in the perception thread ---------------------------------------
    def perceive(self, obs: Observation) -> PerceptionResult:
        t: dict = {}
        t0 = time.perf_counter()
        hdr, cam = obs.header, obs.header["camera"]
        img = cv2.imdecode(np.frombuffer(obs.jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"seq {hdr['seq']}: JPEG decode failed")
        h, w = img.shape[:2]
        f_px = (w / 2) / math.tan(math.radians(cam["hfov_deg"] / 2))
        horizon = int(h * self.cfg["horizon_frac"])
        t1 = time.perf_counter(); t["decode"] = (t1 - t0) * 1e3
        dets: list[Detection] = []

        # 1) mission markers: real ArUco decode on the rendered pixels
        corners, ids, _ = self.aruco.detectMarkers(img)
        marker_boxes = []
        if ids is not None:
            for c, mid in zip(corners, ids.ravel()):
                pts = c[0]
                side = float(np.mean([np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)]))
                cx = float(pts[:, 0].mean())
                bearing = math.degrees(math.atan((cx - w / 2) / f_px))
                rng = self.cfg["marker_side_m"] * f_px / max(side, 1e-3)
                # ArUco has no score; decode reliability grows with pixels per cell, so confidence
                # is apparent size vs a reference. Say this out loud if asked.
                conf = float(np.clip(side / self.cfg["marker_conf_px"], 0.05, 1.0))
                x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0)
                bbox = (int(x0), int(y0), int(x1), int(y1))
                marker_boxes.append(bbox)
                lab = f"M{int(mid):02d}"
                dets.append(Detection(lab, "marker", lab, round(conf, 3), bbox, round(bearing, 2), round(rng, 2)))
        t2 = time.perf_counter(); t["aruco"] = (t2 - t1) * 1e3

        # 2) rocks: YOLO (or blobs) -> embedding -> novelty vs memory -> stable id
        boxes = self._yolo_boxes(img) if self.yolo else self._blob_boxes(img, horizon)
        t3 = time.perf_counter(); t["rocks"] = (t3 - t2) * 1e3
        crops, embeddings = [], {}
        for (x0, y0, x1, y1, conf, label) in boxes:
            if any(_iou((x0, y0, x1, y1), mb) > 0.3 for mb in marker_boxes):
                continue
            if x1 - x0 < 6 or y1 - y0 < 6:
                continue
            bearing = math.degrees(math.atan(((x0 + x1) / 2 - w / 2) / f_px))
            rng = f_px * self.cfg["camera_height_m"] / max(y1 - horizon, 1.0)   # ground-plane guess
            crop = img[max(0, y0):y1, max(0, x0):x1]
            v = self.embedder(crop)
            nov = self.memory.novelty(v)
            kind = "anomaly" if nov >= self.cfg["anomaly_threshold"] else "rock"
            tid = self.tracker.match(bearing, hdr["seq"]) or self.tracker.new_id(kind)
            self.tracker.update(tid, bearing, rng, hdr["seq"], kind)
            embeddings[tid] = v
            dets.append(Detection(tid, kind, label, round(float(conf), 3), (x0, y0, x1, y1),
                                  round(bearing, 2), round(rng, 2), round(nov, 3)))
            if kind == "anomaly":
                ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    crops.append((tid, round(nov, 3), buf.tobytes()))
        # habituation: a track that left the view is committed to memory
        for tid in self.tracker.expire(hdr["seq"]):
            v = self.last_embeddings.pop(tid, None)
            if v is not None:
                self.memory.add(v)
        self.last_embeddings.update(embeddings)
        t4 = time.perf_counter(); t["embed"] = (t4 - t3) * 1e3

        # 3) overlay thumbnail: quality priority #2 -- proof perception is real
        thumb = self._overlay(img, dets, hdr)
        t5 = time.perf_counter(); t["overlay"] = (t5 - t4) * 1e3
        t["total"] = (t5 - t0) * 1e3
        crops.sort(key=lambda c: -c[1])
        return PerceptionResult(seq=hdr["seq"], sim_time=hdr["sim_time"], header=hdr, recv_real=obs.recv_real,
                                detections=dets, thumbnail_jpeg=thumb, crops=crops[: self.cfg["max_crops"]],
                                embeddings=embeddings, timings_ms={k: round(v, 1) for k, v in t.items()},
                                backend=self.backend)

    def _yolo_boxes(self, img: np.ndarray) -> list[tuple]:
        res = self.yolo.predict(img, imgsz=self.cfg["yolo_imgsz"], conf=self.cfg["yolo_conf"],
                                device=self.cfg["device"], verbose=False)[0]
        out = []
        for xyxy, conf, cls in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
            out.append((int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]), float(conf), str(self.yolo.names[int(cls)])))
        return out

    def _blob_boxes(self, img: np.ndarray, horizon: int) -> list[tuple]:
        """Placeholder until the AI4Mars YOLO fine-tune lands: grey things on saturated ground."""
        hsv = cv2.cvtColor(img[horizon:], cv2.COLOR_BGR2HSV)
        m = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] < 235)).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        for c in cnts:
            x, y, ww, hh = cv2.boundingRect(c)
            if ww * hh < 150 or ww < 8 or hh < 6:
                continue
            conf = float(min(0.9, 0.3 + ww * hh / 6000.0))
            out.append((x, y + horizon, x + ww, y + hh + horizon, conf, "rock"))
        out.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
        return out[:12]

    def _overlay(self, img: np.ndarray, dets: list[Detection], hdr: dict) -> bytes:
        out = img.copy()
        for d in dets:
            col = (0, 220, 0) if d.kind == "marker" else (255, 0, 255) if d.kind == "anomaly" else (200, 200, 200)
            x0, y0, x1, y1 = d.bbox
            cv2.rectangle(out, (x0, y0), (x1, y1), col, 2)
            tag = f"{d.label} c={d.conf:.2f}" + (f" n={d.novelty:.2f}" if d.kind != "marker" else "") + f" {d.est_range_m:.0f}m"
            cv2.putText(out, tag, (x0, max(12, y0 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
        cv2.putText(out, f"seq {hdr['seq']} t={hdr['sim_time']:.0f}s B={hdr['budget']['remaining']:.0f}Wh {self.backend}",
                    (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        tw = self.cfg["thumb_w"]
        th = int(out.shape[0] * tw / out.shape[1])
        ok, buf = cv2.imencode(".jpg", cv2.resize(out, (tw, th)), [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else b""
