"""Background scheduler for proactive DJ interjections."""

import queue
import threading
import time
from datetime import datetime


class DJScheduler(threading.Thread):
    def __init__(self, brain, config: dict):
        super().__init__(daemon=True)
        self.brain = brain
        self.config = config

        sched_cfg = config.get("scheduler", {})
        self.enabled = sched_cfg.get("enabled", True)
        self.check_interval = sched_cfg.get("check_interval_seconds", 30)
        self.global_cooldown = sched_cfg.get("global_cooldown_minutes", 3)

        from .rules import RuleEngine
        self.engine = RuleEngine(sched_cfg)

        self.interjection_queue: queue.Queue = queue.Queue(maxsize=20)
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()  # extra pause gate
        self._paused_event.set()  # start unpaused
        self._last_interjection_time: float = 0
        self._last_weather_desc: str = ""

    def run(self):
        if not self.enabled:
            return

        print(f"[Scheduler] Started (interval={self.check_interval}s, "
              f"cooldown={self.global_cooldown}min)")

        while not self._stop_event.is_set():
            self._paused_event.wait()  # block when paused
            try:
                self._tick()
            except Exception as e:
                print(f"[Scheduler] Error: {e}")

            self._stop_event.wait(self.check_interval)

    def pause(self):
        self._paused_event.clear()

    def resume(self):
        self._paused_event.set()

    def stop(self):
        self._stop_event.set()
        print("[Scheduler] Stopped")

    def get_pending_interjection(self) -> dict | None:
        try:
            return self.interjection_queue.get_nowait()
        except queue.Empty:
            return None

    def _tick(self):
        state = self._gather_state()
        triggered = self.engine.evaluate_all(state)

        if not triggered:
            return

        # Global cooldown check
        now = time.time()
        if now - self._last_interjection_time < self.global_cooldown * 60:
            return

        # Take highest-priority triggered rule
        rule = triggered[0]
        now_ts = time.time()
        rule.mark_triggered(now_ts)
        self._last_interjection_time = now_ts

        # Update last weather state
        self._last_weather_desc = state.get("weather_desc", "")

        # Generate interjection
        action = self.brain.think_interjection(rule, state)
        if action and action.say:
            item = {
                "type": "interjection",
                "say": action.say,
                "reason": action.reason,
                "mood": action.mood,
                "rule": rule.name,
                "priority": rule.priority,
                "timestamp": datetime.now().isoformat(),
            }
            try:
                self.interjection_queue.put_nowait(item)
                print(f"[Scheduler] Interjection [{rule.name}] priority={rule.priority}: "
                      f"{action.say[:40]}...")
            except queue.Full:
                pass

    def _gather_state(self) -> dict:
        ctx = self.brain.get_interjection_context()
        ctx["last_weather_desc"] = self._last_weather_desc
        return ctx
