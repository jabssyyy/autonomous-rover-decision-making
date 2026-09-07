"""main.py -- the BRAIN process. One asyncio loop, one perception thread, two WebSocket servers.

    SIM  --observation (JSON text + JPEG binary)-->  :8765  --action (JSON)-->  SIM
    BRAIN --telemetry (JSON + attachment JPEGs), DELAYED-->  :8766  --uplink, DELAYED-->  BRAIN

Threading model
    loop thread  : sim_handler -> LatestSlot(frames) -> perception_worker
                   perception_worker awaits run_in_executor(ONE-thread pool, Perceiver.perceive)
                   -> LatestSlot(results) -> decider (fixed cadence in SIM time) -> action to SIM
                   -> DelayLine (REAL seconds) -> broadcast to panels
                   panel_handler -> validate uplink -> DelayLine (REAL seconds) -> apply_uplink
    perception   : the only thread that touches OpenCV/torch. Latest frame wins; stale frames are
                   overwritten in the slot and counted, never queued.
    recorder     : background writer thread (runtime.Recorder). The loop never blocks on disk.

Two clocks, kept apart on purpose
    sim_time  : read ONLY from observations (SIM's onboard clock). Decision cadence and every
                *_at field in the contract use it.
    real      : time.monotonic() since start. ONLY the delay lines and the recording use it.
                comms_delay_real_s is REAL seconds by contract; never convert it into sim time
                to schedule anything.

    python main.py --tag stay                              # full stack, delay from config.yaml
    python main.py --tag dev --delay 3 --no-yolo --no-torch  # runs against stub_sim.py on any CPU
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import ConnectionClosed

import policy
from contract import (ContractViolation, validate_action, validate_jpeg, validate_observation,
                      validate_telemetry, validate_uplink)
from perception import Observation, Perceiver
from runtime import DelayLine, LatestSlot, Recorder, dumps

log = logging.getLogger("brain")


class Brain:
    def __init__(self, cfg: dict, bcfg: dict, args) -> None:
        self.cfg, self.bcfg, self.args = cfg, bcfg, args
        self.pol = bcfg["policy"]
        self.t0 = time.monotonic()
        self.st = policy.BrainState(gamma=policy.clamp_gamma(float(cfg["gamma"])))
        self.frames = LatestSlot()
        self.results = LatestSlot()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="perception")
        self.perceiver = Perceiver(bcfg["perception"], use_yolo=not args.no_yolo, use_torch=not args.no_torch)
        delay = float(args.delay if args.delay is not None else cfg["comms_delay_real_s"])
        self.down = DelayLine(delay, self.deliver)
        self.up = DelayLine(delay, self.apply_uplink)
        self.sim_ws = None
        self.panels: set = set()
        self.session_id = 0
        self.last_seq = -1
        self.stop = asyncio.Event()
        self.frames_rx = 0
        self.rec: Recorder | None = None
        if bcfg["record"]["enabled"] and not args.no_record:
            self.rec = Recorder(args.record_dir or bcfg["record"]["dir"], args.tag,
                                {"config": cfg, "brain": bcfg, "delay_real_s": delay, "wall_start": time.time(),
                                 "backend": self.perceiver.backend, "argv": vars(args)})
            log.info("recording to %s", self.rec.dir)

    def real(self) -> float:
        return time.monotonic() - self.t0

    # ------------------------------------------------------------------ SIM link
    async def sim_handler(self, ws) -> None:
        if self.sim_ws is not None:
            await ws.close(code=1008, reason="Only one SIM may control a mission")
            return
        log.info("SIM connected from %s", ws.remote_address)
        self.sim_ws = ws
        self.session_id += 1
        session_id = self.session_id
        pending_header = None
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    if pending_header is not None:
                        raise ContractViolation("observation header must be followed by one JPEG")
                    pending_header = validate_observation(json.loads(msg))
                    continue
                if pending_header is None:
                    raise ContractViolation("binary frame arrived without a preceding observation header")
                hdr, pending_header = pending_header, None
                jpeg = validate_jpeg(msg)
                if hdr["seq"] <= self.last_seq or hdr["sim_time"] < self.st.sim_time:
                    raise ContractViolation("observation clock/sequence regressed; restart BRAIN for a new mission")
                self.last_seq = hdr["seq"]
                self.st.sim_time = hdr["sim_time"]                       # the onboard clock advances here, only here
                self.frames_rx += 1
                if self.rec:
                    ref = self.rec.frame(hdr["seq"], jpeg)
                    self.rec.jsonl("observations", {**hdr, "_frame_ref": ref, "_real_s": self.real(), "_bytes": len(jpeg)})
                observation = Observation(hdr, jpeg, self.real())
                observation.session_id = session_id
                self.frames.put(observation)
        except (ContractViolation, ValueError) as e:
            log.critical("CONTRACT VIOLATION on the SIM link: %s", e)
            if not self.args.lenient:
                self.stop.set()                                          # strict: the process dies, loudly
            raise
        except ConnectionClosed:
            log.info("SIM disconnected")
        finally:
            if self.sim_ws is ws:
                self.sim_ws = None

    async def perception_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            obs = await self.frames.take()
            try:
                res = await loop.run_in_executor(self.pool, self.perceiver.perceive, obs)
            except Exception:
                log.exception("perception failed on seq %s", obs.header.get("seq"))
                raise  # supervised by serve(); SIM's command watchdog stops motion
            res.session_id = obs.session_id
            res.dropped_before = self.frames.take_dropped()
            self.results.put(res)

    async def decider(self) -> None:
        while True:
            res = await self.results.take()
            if self.sim_ws is None or res.session_id != self.session_id or self.real() - res.recv_real > 2.5:
                continue
            if res.sim_time - self.st.last_decision_sim < self.cfg["decision_interval_sim_s"]:
                continue                                                 # fixed cadence, in SIM time
            action, extras = policy.decide(res, self.st, self.cfg, self.pol)
            try:
                validate_action(action)                                  # never send what a judge could fault
            except ContractViolation:
                log.exception("BRAIN produced an invalid action; refusing to send it")
                if not self.args.lenient:
                    self.stop.set()
                continue
            self.st.last_decision_sim = res.sim_time
            if "commit_embedding" in extras:
                self.perceiver.commit(extras["commit_embedding"])
            self.perceiver.memory.protect(extras.get("protect_embedding"))
            ws = self.sim_ws
            if ws is not None:
                try:
                    await ws.send(dumps(action))
                except ConnectionClosed:
                    pass
            a = action["audit"]
            log.info("seq %5d sim %8.1f | %-15s %-5s | U %5s slack %5.2f w_c %4.2f | %d dets | perc %5.1f ms drop %d | %s",
                     res.seq, res.sim_time, action["decision"], action["target"]["label"] if action["target"] else "-",
                     next((c["U"] for c in a["candidates"] if c["id"] == a["chosen"]), "-"), a["slack"], a["w_curiosity"],
                     len(res.detections), res.timings_ms.get("total", 0.0), res.dropped_before, a["text"][:70])
            # telemetry -> delay line (the downlink is itself a decision: thumbnail + top-k anomaly crops)
            assigned = self.st.assigned_override if self.st.assigned_override is not None else res.header["mission"]["assigned_markers"]
            tele = {"type": "telemetry", "generated_at": res.sim_time, "delivered_at": res.sim_time,
                    "pose": res.header["pose"], "state": self.st.mode, "audit": a,
                    "mission": {"confirmed_markers": [m for m in res.header["mission"]["confirmed_markers"] if m in assigned],
                                "total": len(assigned)},
                    "attachments": [{"kind": "thumbnail", "frame_ref": f"f_{res.seq}"}]
                                   + [{"kind": "anomaly_crop", "id": cid, "novelty": nov} for (cid, nov, _) in res.crops]}
            validate_telemetry(tele)
            blobs = [res.thumbnail_jpeg] + [jpg for (_, _, jpg) in res.crops]
            names = []
            if self.rec:
                names = [self.rec.blob(f"thumb_{res.seq}", res.thumbnail_jpeg)] + \
                        [self.rec.blob(f"crop_{res.seq}_{cid}", jpg) for (cid, _, jpg) in res.crops]
                self.rec.jsonl("actions", {**action, "_real_s": self.real(), "_perception_ms": res.timings_ms,
                                           "_dropped_before": res.dropped_before,
                                           "_detections": [d.__dict__ for d in res.detections]})
            self.down.push({"msg": tele, "blobs": blobs, "names": names, "generated_real_s": self.real()})

    # ---------------------------------------------------------------- PANEL link
    async def deliver(self, item: dict) -> None:
        msg, now = item["msg"], self.real()
        msg["delivered_at"] = self.st.sim_time                            # onboard clock at delivery
        msg["clock"] = {"generated_real_s": round(item["generated_real_s"], 3), "delivered_real_s": round(now, 3),
                        "delay_real_s": round(now - item["generated_real_s"], 3)}
        validate_telemetry(msg)
        broadcast(self.panels, dumps(msg))                                 # JSON text frame ...
        for b in item["blobs"]:
            broadcast(self.panels, b)                                      # ... then one binary frame per attachment
        if self.rec:
            self.rec.jsonl("telemetry_delivered", {**msg, "_blobs": item["names"]})

    async def panel_handler(self, ws) -> None:
        self.panels.add(ws)
        log.info("PANEL connected from %s (%d panels)", ws.remote_address, len(self.panels))
        try:
            async for msg in ws:
                if not isinstance(msg, str):
                    continue
                try:
                    up = validate_uplink(json.loads(msg))
                except (ContractViolation, ValueError) as e:
                    log.error("INVALID uplink from panel: %s", e)
                    continue
                log.info("uplink %s received (issued at sim %.1f); lands in %.0f real s", up["command"], up["issued_at"], self.up.delay_s)
                if self.rec:
                    self.rec.jsonl("uplinks", {**up, "_event": "received", "_real_s": self.real(), "_sim_now": self.st.sim_time})
                self.up.push(up)
        except ConnectionClosed:
            pass
        finally:
            self.panels.discard(ws)
            log.info("PANEL disconnected (%d panels)", len(self.panels))

    async def apply_uplink(self, up: dict) -> None:
        st, cmd, pl = self.st, up["command"], up["payload"]
        up["arrives_at"] = st.sim_time
        stale = False
        if cmd == "halt":
            st.halted = True
        elif cmd == "ack_report":
            if st.mode == "AWAITING_UPLINK":
                st.mode, st.halted = "AUTONOMOUS", False
            else:
                stale = True
        elif cmd == "set_gamma":
            st.gamma = policy.clamp_gamma(float(pl["gamma"]))
        elif cmd == "reassign_markers":
            st.assigned_override = list(pl["assigned_markers"])
        elif cmd == "abort_investigation":
            if st.investigating:
                policy.cancel_investigation(st, "Operator aborted the current investigation.")
                self.perceiver.memory.protect(None)
            else:
                stale = True                                               # the late-interrupt beat
        elif cmd == "force_investigate":
            # A force command cannot bypass the reserve gate or visual reacquisition.
            st.notes.append("force_investigate is unsupported in Phase 1; no override executed.")
            stale = True
        event = "uplink_stale" if stale else "uplink_applied"
        log.warning("%s: %s at sim %.1f (issued at sim %.1f, %.0f sim s ago)", event, cmd, st.sim_time,
                    up["issued_at"], st.sim_time - up["issued_at"])
        st.notes.append(f"Uplink {cmd} {'landed stale' if stale else 'applied'} at sim {st.sim_time:.0f} "
                        f"(issued at {up['issued_at']:.0f}).")
        if self.rec:
            self.rec.jsonl("uplinks", {**up, "_event": event, "_real_s": self.real()})

    async def stats(self) -> None:
        while True:
            await asyncio.sleep(5)
            log.info("stats: frames %d dropped %d decisions %d | downlink queue %d | panels %d | memory %d | sim %.0f s",
                     self.frames_rx, self.frames.dropped, self.st.decisions, len(self.down), len(self.panels),
                     len(self.perceiver.memory), self.st.sim_time)

    async def serve(self) -> None:
        p = self.bcfg["ports"]
        async with serve(self.sim_handler, p["host"], p["sim"], max_size=16 * 2**20, compression=None), \
                   serve(self.panel_handler, p["host"], p["panel"], max_size=2**20, compression=None):
            log.info("BRAIN up: SIM ws://%s:%d  PANEL ws://%s:%d  delay %.0f real s  cadence %.1f sim s  backend %s",
                     p["host"], p["sim"], p["host"], p["panel"], self.down.delay_s,
                     self.cfg["decision_interval_sim_s"], self.perceiver.backend)
            tasks = [asyncio.create_task(c) for c in (self.perception_worker(), self.decider(), self.down.run(),
                                                      self.up.run(), self.stats())]
            stop_task = asyncio.create_task(self.stop.wait())
            try:
                done, _ = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not stop_task:
                        task.result()  # propagate worker failure rather than silently freezing
            finally:
                for t in [stop_task, *tasks]:
                    t.cancel()
                await asyncio.gather(stop_task, *tasks, return_exceptions=True)
                self.pool.shutdown(wait=False, cancel_futures=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--brain", default=str(Path(__file__).with_name("brain.yaml")))
    ap.add_argument("--tag", default="run")
    ap.add_argument("--delay", type=float, default=None, help="override comms_delay_real_s (REAL seconds)")
    ap.add_argument("--no-yolo", action="store_true")
    ap.add_argument("--no-torch", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--record-dir", default=None, help="override record.dir from brain.yaml")
    ap.add_argument("--lenient", action="store_true", help="do not exit on a contract violation (demo day only)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s", datefmt="%H:%M:%S")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    bcfg = yaml.safe_load(Path(args.brain).read_text(encoding="utf-8"))
    bcfg["record"]["dir"] = str((Path(args.brain).resolve().parent / bcfg["record"]["dir"]).resolve())
    if cfg["time_compression"] != 1:
        raise ValueError("Phase 1 requires physics seconds: time_compression must be 1")
    if bcfg["perception"]["marker_side_m"] != cfg["marker_side_m"]:
        raise ValueError("marker width must agree between shared and BRAIN config")
    brain = Brain(cfg, bcfg, args)
    try:
        asyncio.run(brain.serve())
    except KeyboardInterrupt:
        pass
    finally:
        if brain.rec:
            brain.rec.close()
            log.info("recording closed: %s", brain.rec.dir)


if __name__ == "__main__":
    main()
