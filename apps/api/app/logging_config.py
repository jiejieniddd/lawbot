"""Keep latency telemetry visible without enabling verbose SDK/request logs."""
import logging


def configure_timing_logging() -> None:
    logger = logging.getLogger("lawbot.timing")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
