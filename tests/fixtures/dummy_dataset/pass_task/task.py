import time
from loguru import logger
from terrarium.task.decorator import entry
from terrarium.task.checking import run_checkers


@entry(capabilities=[])
def task(env, agent):
    logger.info("Starting pass_task")
    time.sleep(0.5)
    logger.info("Running checks")
    time.sleep(0.5)
    logger.info("All checks passed")
    return run_checkers({"always_pass": lambda: True})
