import io
import logging

from homefeed_core.progress import ProgressLine, ProgressLogHandler


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_terminal_line_is_redrawn_in_place_with_time_left() -> None:
    stream, clock = Terminal(), Clock()
    report = ProgressLine(stream, clock=clock).phase("Enriching")

    clock.now = 10
    report(1, 4)
    clock.now = 40
    report(4, 4)

    first, last = stream.getvalue().split("\r\x1b[K")[1:]
    assert first == "Enriching    [#####···············] 1/4   25%  ~30s left"
    assert last == "Enriching    [####################] 4/4  100%  in 40s\n"


def test_elsewhere_a_line_every_tenth_of_the_way() -> None:
    stream = io.StringIO()
    report = ProgressLine(stream, clock=Clock()).phase("Tagging")

    for done in range(1, 201):
        report(done, 200)

    lines = stream.getvalue().splitlines()
    # The first step (so the total shows at once), then each 10%.
    assert len(lines) == 11
    assert "  1/200 " in lines[0] and " 20/200 " in lines[1]
    assert lines[-1].endswith("200/200  100%  in 0s")


def test_log_records_clear_the_line_first() -> None:
    stream = Terminal()
    line = ProgressLine(stream, clock=Clock())
    logger = logging.getLogger("test_progress")
    logger.addHandler(ProgressLogHandler(line))
    logger.propagate = False

    line.phase("Tagging")(1, 2)
    logger.warning("Could not tag x")

    assert stream.getvalue().endswith("1/2   50%\r\x1b[KCould not tag x\n")
