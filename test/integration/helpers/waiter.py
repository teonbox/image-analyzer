"""等待策略实现"""
import time
import logging
from typing import Callable, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WaitConfig:
    """等待配置"""
    initial_wait: float = 1.0       # 初始等待时间（秒）
    max_wait: float = 5.0           # 最大等待时间（秒）
    backoff_factor: float = 1.5     # 退避因子
    timeout: int = 60               # 总超时时间（秒）


class Waiter:
    """等待策略实现（指数退避）"""

    def __init__(self, config: Optional[WaitConfig] = None):
        self.config = config or WaitConfig()

    def wait_until(
        self,
        condition: Callable[[], tuple[bool, Any]],
        description: str = "条件满足"
    ) -> Any:
        """
        等待直到条件满足

        Args:
            condition: 返回 (是否满足, 结果) 的函数
            description: 等待描述

        Returns:
            条件满足时的结果

        Raises:
            TimeoutError: 超时
        """
        start_time = time.time()
        wait_time = self.config.initial_wait
        iteration = 0

        while time.time() - start_time < self.config.timeout:
            iteration += 1

            satisfied, result = condition()

            if satisfied:
                elapsed = time.time() - start_time
                print(f"  ✓ {description} (耗时 {elapsed:.1f}s, {iteration} 次检查)")
                logger.info(
                    f"{description} satisfied after {elapsed:.1f}s, "
                    f"{iteration} checks"
                )
                return result

            time.sleep(wait_time)
            wait_time = min(
                wait_time * self.config.backoff_factor,
                self.config.max_wait
            )

        raise TimeoutError(
            f"{description} 在 {self.config.timeout} 秒内未满足 "
            f"({iteration} 次检查)"
        )


class RequestWaiter:
    """请求等待器（专门用于等待请求完成）"""

    def __init__(self, api_client, waiter: Optional[Waiter] = None):
        self.api_client = api_client
        self.waiter = waiter or Waiter()

    def wait_for_completion(self, request_id: str) -> str:
        """等待请求完成"""

        def check_status():
            try:
                response = self.api_client.get_request_status(request_id)
                data = response['data']
                status = data['status']
                frame_stats = data.get('frame_stats', {})
                completed = frame_stats.get('completed', 0)
                total = frame_stats.get('total', 0)

                progress = (completed / total * 100) if total > 0 else 0
                print(f"    状态: {status}, 进度: {progress:.1f}% ({completed}/{total})")
                logger.info(
                    f"Request {request_id}: status={status}, "
                    f"progress={progress:.1f}%"
                )

                if status in ['completed', 'partial_complete', 'failed']:
                    return True, status

                return False, None
            except Exception as e:
                print(f"    ⚠ 查询失败: {e}")
                logger.warning(f"Query failed for {request_id}: {e}")
                return False, None

        return self.waiter.wait_until(
            check_status,
            f"请求 {request_id} 完成"
        )
