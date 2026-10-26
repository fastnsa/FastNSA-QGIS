"""Progress adapters shared by FastNSA Processing algorithms."""


class ProcessingProgress:
    STAGE_PROGRESS = {
        "Input validation": 2.0,
        "Road network conversion": 12.0,
        "Event mapping": 35.0,
        "Reusing preprocessed event mappings": 35.0,
        "backend compute": 55.0,
        "Monte Carlo batch": 72.0,
        "Output writing": 94.0,
        "Style application": 98.0,
    }

    def __init__(self, feedback):
        self.feedback = feedback
        self._last_stage = None
        self._last_progress = 0.0

    def _set_progress(self, value):
        # Inner search cancellation polls do not carry a new phase fraction.
        self._last_progress = max(self._last_progress, value)
        self.feedback.setProgress(self._last_progress)

    def stage(self, stage):
        if stage != self._last_stage:
            self.feedback.pushInfo(f"Stage: {stage}")
            self._last_stage = stage
        self._set_progress(self.STAGE_PROGRESS.get(stage, 5.0))
        if self.feedback.isCanceled():
            raise RuntimeError("FastNSA operation canceled.")

    def native(self, stage, completed, total):
        if stage != self._last_stage:
            self.feedback.pushInfo(f"Stage: {stage}")
            self._last_stage = stage
        base = self.STAGE_PROGRESS.get(stage, 55.0)
        fraction = completed / total if total > 0 else 0.0
        self._set_progress(min(93.0, base + 18.0 * max(0.0, min(1.0, fraction))))
        return self.feedback.isCanceled()
