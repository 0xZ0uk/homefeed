"""Progress reporting for the command-line entry points (`python -m homefeed_core.enricher`,
`python -m homefeed_core.llm_tags`).

Long loops take an optional `Progress` callback, called with (done, total) after each
step. `ProgressLine` renders them on stderr: on a terminal, one line redrawn in place

    Enriching  [##########··········]  52/150  35%  ~1m 10s left

and elsewhere (a log file, a pipe) a plain line every 10% of the way. Log records go
through `ProgressLogHandler`, which clears the line first so warnings don't land in the
middle of the bar; the bar is redrawn on the next step.
"""

import logging
import math
import sys
import time
from collections.abc import Callable
from typing import TextIO

# Called with (done, total) after each step.
type Progress = Callable[[int, int], None]
# Makes the `Progress` of a named phase ("Re-embedding", "Enriching", "Tagging").
type Phases = Callable[[str], Progress]

BAR_WIDTH = 20


class ProgressLine:
    """Renders phases on `stream` (see the module docstring)."""

    def __init__(
        self, stream: TextIO | None = None, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._stream = stream or sys.stderr
        self._clock = clock
        self._interactive = self._stream.isatty()
        self._drawn = False  # a partial line is on screen

    def phase(self, label: str) -> Progress:
        started = self._clock()
        last_decile = -1

        def report(done: int, total: int) -> None:
            nonlocal last_decile
            if total <= 0:
                return
            done = min(done, total)
            line = _render(label, done, total, self._clock() - started)
            if self._interactive:
                self._stream.write(f"\r\x1b[K{line}")
                self._drawn = done < total
                if done == total:
                    self._stream.write("\n")
            else:
                decile = math.floor(10 * done / total)
                if decile == last_decile and done < total:
                    return
                last_decile = decile
                self._stream.write(f"{line}\n")
            self._stream.flush()

        return report

    @property
    def stream(self) -> TextIO:
        return self._stream

    def clear(self) -> None:
        """Erase a partly drawn line (before something else is written)."""
        if self._drawn:
            self._stream.write("\r\x1b[K")
            self._stream.flush()
            self._drawn = False


class ProgressLogHandler(logging.StreamHandler[TextIO]):
    """Writes log records to the progress line's stream, clearing the line first."""

    def __init__(self, line: ProgressLine) -> None:
        super().__init__(line.stream)
        self._line = line

    def emit(self, record: logging.LogRecord) -> None:
        self._line.clear()
        super().emit(record)


def configure_cli_logging(line: ProgressLine, level: int = logging.WARNING) -> None:
    """Log `level` and up through `line` (warnings by default: progress shows the rest)."""
    handler = ProgressLogHandler(line)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=level, handlers=[handler], force=True)


def _render(label: str, done: int, total: int, elapsed: float) -> str:
    filled = round(BAR_WIDTH * done / total)
    bar = "#" * filled + "·" * (BAR_WIDTH - filled)
    width = len(str(total))
    line = f"{label:<12} [{bar}] {done:>{width}}/{total}  {100 * done // total:>3}%"
    if 0 < done < total and elapsed > 0:
        line += f"  ~{_duration(elapsed / done * (total - done))} left"
    elif done == total:
        line += f"  in {_duration(elapsed)}"
    return line


def _duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
