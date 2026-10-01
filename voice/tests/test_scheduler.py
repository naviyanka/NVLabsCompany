import asyncio
import threading

from nexus_voice.scheduler import ModelScheduler


class BlockingModel:
    """Each call blocks until released; records order and overlap."""

    def __init__(self):
        self.order, self.active, self.max_active = [], 0, 0
        self.gates: dict[str, threading.Event] = {}
        self.started: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def job(self, name):
        self.gates[name], self.started[name] = threading.Event(), threading.Event()

        def run():
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.order.append(name)
            self.started[name].set()
            self.gates[name].wait(5)
            with self._lock:
                self.active -= 1
            return name

        return run

    async def until_started(self, name):
        await asyncio.to_thread(self.started[name].wait, 5)


async def test_final_never_overlaps_partial():
    m, s = BlockingModel(), ModelScheduler()
    p = asyncio.create_task(s.partial("a", m.job("p")))
    await m.until_started("p")
    f = asyncio.create_task(s.final("a", m.job("f")))
    await asyncio.sleep(0.05)
    assert m.order == ["p"]  # final waits for the running partial
    m.gates["p"].set()
    await asyncio.sleep(0)
    await m.until_started("f")
    m.gates["f"].set()
    assert (await p, await f) == ("p", "f")
    assert m.max_active == s.max_running == 1
    await s.close()


async def test_final_beats_queued_partials():
    m, s = BlockingModel(), ModelScheduler()
    running = asyncio.create_task(s.partial("a", m.job("run")))
    await m.until_started("run")
    q1 = asyncio.create_task(s.partial("b", m.job("p1")))
    q2 = asyncio.create_task(s.partial("c", m.job("p2")))
    fin = asyncio.create_task(s.final("d", m.job("fin")))
    await asyncio.sleep(0.05)
    for name in ("run", "fin", "p1", "p2"):
        m.gates[name].set()
    await asyncio.gather(running, q1, q2, fin)
    assert m.order == ["run", "fin", "p1", "p2"]
    await s.close()


async def test_stale_partial_is_superseded():
    m, s = BlockingModel(), ModelScheduler()
    busy = asyncio.create_task(s.partial("x", m.job("busy")))
    await m.until_started("busy")
    old = asyncio.create_task(s.partial("a", m.job("old")))
    await asyncio.sleep(0.02)
    new = asyncio.create_task(s.partial("a", m.job("new")))
    await asyncio.sleep(0.02)
    m.gates["busy"].set()
    await asyncio.sleep(0.02)
    m.gates["new"].set()
    assert await old is None and await new == "new"
    assert "old" not in m.order
    await busy
    await s.close()


async def test_final_discards_own_queued_partial():
    m, s = BlockingModel(), ModelScheduler()
    busy = asyncio.create_task(s.partial("x", m.job("busy")))
    await m.until_started("busy")
    part = asyncio.create_task(s.partial("a", m.job("part")))
    await asyncio.sleep(0.02)
    fin = asyncio.create_task(s.final("a", m.job("fin")))
    await asyncio.sleep(0.02)
    m.gates["busy"].set()
    await asyncio.sleep(0.02)
    m.gates["fin"].set()
    assert await part is None and await fin == "fin"
    assert "part" not in m.order
    await busy
    await s.close()


async def test_disconnect_leaves_no_queued_jobs():
    m, s = BlockingModel(), ModelScheduler()
    busy = asyncio.create_task(s.partial("x", m.job("busy")))
    await m.until_started("busy")
    queued = [
        asyncio.create_task(s.partial("gone", m.job("g"))),
        asyncio.create_task(s.final("gone", m.job("gf"))),
    ]
    await asyncio.sleep(0.02)
    s.release("gone")
    assert s.queued == 0
    m.gates["busy"].set()
    await busy
    await asyncio.gather(*queued, return_exceptions=True)
    assert m.order == ["busy"]
    await s.close()


async def test_cancelled_caller_keeps_exclusivity_until_thread_ends():
    m, s = BlockingModel(), ModelScheduler()
    first = asyncio.create_task(s.final("a", m.job("first")))
    await m.until_started("first")
    first.cancel()
    second = asyncio.create_task(s.final("b", m.job("second")))
    await asyncio.sleep(0.1)
    assert m.order == ["first"] and m.active == 1  # thread still running: second must wait
    m.gates["first"].set()
    await m.until_started("second")
    m.gates["second"].set()
    assert await second == "second"
    assert m.max_active == 1
    await s.close()


async def test_repeated_utterances_do_not_grow_the_queue():
    m, s = BlockingModel(), ModelScheduler()
    busy = asyncio.create_task(s.partial("x", m.job("busy")))
    await m.until_started("busy")
    tasks = [asyncio.create_task(s.partial("a", lambda: 1)) for _ in range(500)]
    await asyncio.sleep(0.05)
    assert s.queued == 1
    m.gates["busy"].set()
    await busy
    results = await asyncio.gather(*tasks)
    assert results.count(1) == 1 and results.count(None) == 499
    await s.close()
