"""Dependency-free checks of the existing message and runtime foundation.

Run: python brain/check_foundation.py (from the repository root).
This does not test camera perception, CUDA, WebSockets, or mission completion.
"""
import asyncio
import copy
import unittest

import contract
from runtime import DelayLine, LatestSlot, dumps


class ContractChecks(unittest.TestCase):
    def test_existing_contract_examples_and_rejections(self):
        contract._selftest()

    def test_forbidden_information_at_every_object_boundary(self):
        for field in (None, "pose", "budget", "hazard", "mission", "camera"):
            with self.subTest(field=field):
                msg = copy.deepcopy(contract.EXAMPLE_OBSERVATION)
                target = msg if field is None else msg[field]
                target["ground_truth"] = [{"class": "rock", "x": 10}]
                with self.assertRaises(contract.ContractViolation):
                    contract.validate_observation(msg)

    def test_invalid_numbers_cannot_enter_budget(self):
        for value in (float("nan"), float("inf"), -1, 1001, True):
            with self.subTest(value=value):
                msg = copy.deepcopy(contract.EXAMPLE_OBSERVATION)
                msg["budget"]["remaining"] = value
                with self.assertRaises(contract.ContractViolation):
                    contract.validate_observation(msg)

    def test_wire_serialization_rejects_nan(self):
        with self.assertRaises(ValueError):
            dumps({"value": float("nan")})


class RuntimeChecks(unittest.IsolatedAsyncioTestCase):
    async def test_latest_frame_wins(self):
        slot = LatestSlot()
        slot.put("old frame")
        slot.put("new frame")
        self.assertEqual(await asyncio.wait_for(slot.take(), 1), "new frame")
        self.assertEqual(slot.take_dropped(), 1)
        self.assertEqual(slot.take_dropped(), 0)
        waiting = asyncio.create_task(slot.take())
        await asyncio.sleep(0)
        self.assertFalse(waiting.done())
        slot.put("next frame")
        self.assertEqual(await asyncio.wait_for(waiting, 1), "next frame")

    async def test_delay_preserves_order_and_does_not_deliver_early(self):
        delivered = []
        ready = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def receive(item):
            delivered.append((item, loop.time()))
            if len(delivered) == 2:
                ready.set()

        line = DelayLine(0.05, receive)
        started = loop.time()
        line.push("first")
        line.push("second")
        worker = asyncio.create_task(line.run())
        try:
            self.assertEqual(delivered, [])
            await asyncio.wait_for(ready.wait(), 2)
            self.assertEqual([v for v, _ in delivered], ["first", "second"])
            self.assertGreaterEqual(delivered[0][1] - started, 0.05)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
