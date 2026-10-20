"""Measure new frames actually painted, rather than capture requests or repaints."""
from math import ceil, isclose
from time import monotonic


class DisplayFPS:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.target = None
        self.below_target_samples = 0
        self.warning_fps = None
        self.reset()

    def set_target(self, target):
        if target != self.target:
            self.target = target
            self.below_target_samples = 0
            self.warning_fps = None
            self.reset()

    def reset(self):
        self.started = self.clock()
        self.frames = 0
        self.actual = None

    def presented(self):
        self.frames += 1

    def sample(self):
        now = self.clock()
        elapsed = now - self.started
        if elapsed < 1:
            return False
        self.actual = self.frames / elapsed
        self.started = now
        self.frames = 0
        if self.target is not None and self.target > 15 and self.warning_fps is None:
            difference = self.target - self.actual
            threshold = max(1, ceil(self.target / 4))
            if difference >= threshold or isclose(difference, threshold, abs_tol=1e-9):
                self.below_target_samples += 1
                if self.below_target_samples >= 10:
                    self.warning_fps = self.actual
        return True

    def describe(self, target):
        text = (f"목표 {target} FPS  출력 측정 중" if self.actual is None
                else f"목표 {target} FPS  출력 {self.actual:.1f} FPS")
        if target > 15 and target == self.target and self.warning_fps is not None:
            text += "\n출력 프레임이 낮습니다. 목표 프레임을 낮추세요."
        return text
