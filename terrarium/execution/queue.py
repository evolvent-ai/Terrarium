"""TrialQueue — concurrent trial runner with retry_config."""
from __future__ import annotations

import asyncio

from loguru import logger

from terrarium.execution.trial import Trial
from terrarium.models.config import RetryConfig, TrialConfig
from terrarium.models.result import TrialResult


class TrialQueue:
    """Runs a list of TrialConfigs concurrently with optional retry_config."""

    def __init__(
        self,
        n_concurrent: int = 4,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._n_concurrent = n_concurrent
        self._retry_config = retry_config or RetryConfig()

    async def run(self, trial_configs: list[TrialConfig]) -> list[TrialResult]:
        """Execute all configs concurrently, respecting n_concurrent semaphore."""
        semaphore = asyncio.Semaphore(self._n_concurrent)
        tasks = [self._run_with_retry(cfg, semaphore) for cfg in trial_configs]
        return list(await asyncio.gather(*tasks))

    async def _run_with_retry(
        self,
        trial_config: TrialConfig,
        semaphore: asyncio.Semaphore,
    ) -> TrialResult:
        """Run a single trial with exponential-backoff retry on exception."""
        retry_config = self._retry_config

        for attempt in range(retry_config.max_retries + 1):
            async with semaphore:
                result = await Trial(trial_config).run()

            if result.exception_info is None:
                return result

            if attempt < retry_config.max_retries:
                wait_sec = min(
                    retry_config.min_wait_sec * (retry_config.wait_multiplier ** attempt),
                    retry_config.max_wait_sec,
                )
                logger.info(
                    "Trial '{}' attempt {} failed, retrying in {:.1f}s",
                    trial_config.trial_name, attempt + 1, wait_sec,
                )
                await asyncio.sleep(wait_sec)

        logger.warning(
            "Trial '{}' failed after {} attempt(s): {}",
            trial_config.trial_name, retry_config.max_retries + 1, result.exception_info.exception_message,
        )
        return result
