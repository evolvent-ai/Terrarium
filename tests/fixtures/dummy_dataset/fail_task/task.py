import time
from loguru import logger
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=[])
def task(env, agent):
    logger.info("Starting fail_task")
    time.sleep(0.5)
    logger.info("Running checks")
    time.sleep(0.5)
    logger.warning("check_b failed")
    return run_checkers({
        "check_a": lambda: True,
        "check_b": lambda: False,
    })
