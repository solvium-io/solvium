import asyncio
from enum import StrEnum
import itertools
import random
import httpx
from typing import Dict, Optional
from loguru import logger


class TaskStatus(StrEnum):
    """Enumeration of possible task statuses from Solvium API."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    NO_STATUS = "no_status"


class TaskRejected(Exception):
    """Raised when the Solvium service rejects a task.

    The server-side error code (e.g. ``PROXY_ERROR``, ``BOT_DETECTED_BY_CLOUDFLARE``,
    ``IP_BLOCKED_BY_CLOUDFLARE``) is available as ``error_code``, and the
    rejected task id as ``task_id``.
    """

    def __init__(self, task_id: str, error_code: str) -> None:
        self.task_id = task_id
        self.error_code = error_code
        super().__init__(f"Task {task_id} rejected: {error_code}")


class Solvium:
    """
    Solvium captcha solving client.

    A Python client for the Solvium.io captcha solving service that supports
    various captcha types including Turnstile, reCAPTCHA v3, Cloudflare clearance,
    Vercel challenges, and more.

    Attributes:
        TASK_CREATED_MSG (str): Expected message when a task is successfully created.
    """

    TASK_CREATED_MSG = "Task created"

    def __init__(
        self,
        api_key: str,
        api_proxy: Optional[str] = None,
        api_base_url: str = "https://captcha.solvium.io/api/v1",
        timeout: int = 120,
        verbose: bool = False,
    ):
        """
        Initialize the Solvium client.

        Args:
            api_key (str): Your Solvium API key.
            api_proxy (Optional[str]): Proxy URL for API requests (e.g., "http://proxy:port").
            api_base_url (str): Base URL for the Solvium API.
            timeout (int): Timeout in seconds for captcha solving (default: 120).
            verbose (bool): Enable verbose logging (default: False).
        """
        self.api_key = api_key
        self.api_proxy = api_proxy
        self.verbose = verbose
        self.timeout = timeout
        self.base_url = api_base_url
        self.session = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            proxy=self.api_proxy,
            verify=False,
        )

    async def _api_call(self, api_call_coro) -> Optional[Dict]:
        """
        Make an API call with proper error handling.

        Args:
            api_call_coro: Coroutine for the API call.

        Returns:
            Optional[Dict]: JSON response or None if error occurred.
        """
        try:
            response: httpx.Response = await api_call_coro
            response_json: Dict = response.json()
        except httpx.ConnectError, httpx.NetworkError:
            logger.error(
                "Can't connect to solvium.io... "
                "Check your Internet connection or try using proxy for API calls."
            )
        except httpx.ProxyError:
            logger.error(
                "Proxy is not working... "
                "Try replacing proxy or disabling it for API calls."
            )
        except Exception as e:
            logger.error(f"Unexpected exception occurs: {e}")
        else:
            return response_json

    async def _new_task_wrapper(self, api_call_coro) -> Optional[str]:
        """
        Wrapper for creating new tasks with proper response handling.

        Args:
            api_call_coro: Coroutine for the API call.

        Returns:
            Optional[str]: Task ID if successful, None otherwise.
        """
        response = await self._api_call(api_call_coro)
        if response is not None:
            message: Optional[str] = response.get("message")
            if message is not None:
                if message == Solvium.TASK_CREATED_MSG:
                    task_id = response.get("task_id")
                    if task_id is not None:
                        if self.verbose:
                            logger.info(
                                f"The task was created with following id — {task_id}"
                            )
                        return task_id
                    else:
                        logger.error("Field `task_id` was not provided by service...")
                else:
                    logger.error(f"Service has responded with message: {message}")
            else:
                logger.error(f"Service has responded with: {response}")

    async def _create_noname_task(self, sitekey: str, pageurl: str):
        """Create a NoName captcha solving task."""
        return await self._new_task_wrapper(
            self.session.get(
                "/task/noname", params={"url": pageurl, "sitekey": sitekey}
            )
        )

    async def _create_recaptcha_v3_task(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool,
        proxy: Optional[str],
    ):
        """Create a reCAPTCHA v3 solving task."""
        params = {"url": pageurl, "sitekey": sitekey, "action": action}
        if proxy is not None:
            params["proxy"] = proxy
        if enterprise:
            params["enterprise"] = "true"
        return await self._new_task_wrapper(
            self.session.get(
                "/task/recaptcha-v3",
                params=params,
            )
        )

    async def _create_recaptcha_v2_task(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool,
        proxy: Optional[str],
    ):
        """Create a reCAPTCHA v2 solving task."""
        params = {"url": pageurl, "sitekey": sitekey, "action": action}
        if proxy is not None:
            params["proxy"] = proxy
        if enterprise:
            params["enterprise"] = "true"
        return await self._new_task_wrapper(
            self.session.get(
                "/task/recaptcha-v2",
                params=params,
            )
        )

    async def _create_turnstile_task(self, sitekey: str, pageurl: str):
        """Create a Turnstile captcha solving task."""
        return await self._new_task_wrapper(
            self.session.get(
                "/task/turnstile",
                params={"url": pageurl, "sitekey": sitekey},
                timeout=30,
            )
        )

    async def _create_vercel_task(self, challenge_token: str):
        """Create a Vercel challenge solving task."""
        return await self._new_task_wrapper(
            self.session.get(
                "/task/vercel",
                params={"challengeToken": challenge_token},
            )
        )

    async def _create_cf_clearance_task(self, pageurl: str, body_b64: str, proxy: str):
        """Create a Cloudflare clearance solving task."""
        return await self._new_task_wrapper(
            self.session.post(
                "/task/cf-clearance",
                json={"url": pageurl, "body": body_b64, "proxy": proxy},
            )
        )

    async def _wait_for_task_completion(self, task_id: str) -> Optional[str]:
        """
        Wait for a task to complete and return the solution.

        Args:
            task_id (str): The task ID to monitor.

        Returns:
            Optional[str]: The captcha solution if successful, None otherwise.
        """
        for _ in itertools.count():
            response = await self._api_call(self.session.get(f"/task/status/{task_id}"))
            if response is not None:
                status = TaskStatus(response.get("status", TaskStatus.NO_STATUS.value))
                match status:
                    case TaskStatus.PENDING | TaskStatus.RUNNING:
                        if self.verbose:
                            logger.info(
                                f"Task `{task_id}` has status {status}. "
                                "Waiting for completion..."
                            )
                    case TaskStatus.COMPLETED:
                        result: Dict = response.get("result") or {}
                        solution = result.get("solution", "NO_SOLUTION")
                        if self.verbose:
                            logger.info(
                                f"Task `{task_id}` was successfully solved and solution `{solution[: min(len(solution), 12)]}...` returned!"
                            )
                        return solution
                    case TaskStatus.REJECTED:
                        error: str = response.get("error") or "NO_ERROR_RETURNED"
                        logger.error(
                            f"Task `{task_id}` was not solved! An error was returned — {error}"
                        )
                        raise TaskRejected(task_id, error)
            await asyncio.sleep(random.randint(1, 3))

    async def turnstile(self, sitekey: str, pageurl: str) -> Optional[str]:
        """
        Solve a Turnstile captcha asynchronously.

        Args:
            sitekey (str): The site key for the Turnstile captcha.
            pageurl (str): The URL where the captcha is present.

        Returns:
            Optional[str]: The captcha solution token if successful, None otherwise.
        """
        task_id = await self._create_turnstile_task(sitekey, pageurl)
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def turnstile_sync(self, sitekey: str, pageurl: str) -> Optional[str]:
        """
        Solve a Turnstile captcha synchronously.

        Args:
            sitekey (str): The site key for the Turnstile captcha.
            pageurl (str): The URL where the captcha is present.

        Returns:
            Optional[str]: The captcha solution token if successful, None otherwise.
        """
        return asyncio.run(self.turnstile(sitekey=sitekey, pageurl=pageurl))

    async def noname(self, sitekey: str, pageurl: str) -> Optional[str]:
        """
        Solve a NoName captcha asynchronously.

        Args:
            sitekey (str): The site key for the captcha.
            pageurl (str): The URL where the captcha is present.

        Returns:
            Optional[str]: The captcha solution if successful, None otherwise.
        """
        task_id = await self._create_noname_task(sitekey, pageurl)
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def noname_sync(self, sitekey: str, pageurl: str) -> Optional[str]:
        """
        Solve a NoName captcha synchronously.

        Args:
            sitekey (str): The site key for the captcha.
            pageurl (str): The URL where the captcha is present.

        Returns:
            Optional[str]: The captcha solution if successful, None otherwise.
        """
        return asyncio.run(self.noname(sitekey=sitekey, pageurl=pageurl))

    async def cf_clearance(
        self, pageurl: str, body_b64: str, proxy: str
    ) -> Optional[str]:
        """
        Solve a Cloudflare clearance challenge asynchronously.

        Args:
            pageurl (str): The URL of the page with the challenge.
            body_b64 (str): Base64 encoded body content.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The clearance solution if successful, None otherwise.
        """
        task_id = await self._create_cf_clearance_task(pageurl, body_b64, proxy)
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def cf_clearance_sync(
        self, pageurl: str, body_b64: str, proxy: str
    ) -> Optional[str]:
        """
        Solve a Cloudflare clearance challenge synchronously.

        Args:
            pageurl (str): The URL of the page with the challenge.
            body_b64 (str): Base64 encoded body content.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The clearance solution if successful, None otherwise.
        """
        return asyncio.run(
            self.cf_clearance(pageurl=pageurl, body_b64=body_b64, proxy=proxy)
        )

    async def vercel(self, challenge_token: str) -> Optional[str]:
        """
        Solve a Vercel challenge asynchronously.

        Args:
            challenge_token (str): The Vercel challenge token.

        Returns:
            Optional[str]: The challenge solution if successful, None otherwise.
        """
        task_id = await self._create_vercel_task(challenge_token)
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def vercel_sync(self, challenge_token: str) -> Optional[str]:
        """
        Solve a Vercel challenge synchronously.

        Args:
            challenge_token (str): The Vercel challenge token.

        Returns:
            Optional[str]: The challenge solution if successful, None otherwise.
        """
        return asyncio.run(self.vercel(challenge_token=challenge_token))

    async def recaptcha_v3(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool = False,
        proxy: Optional[str] = None,
    ) -> Optional[str]:
        """
        Solve a reCAPTCHA v3 asynchronously.

        Args:
            sitekey (str): The site key for the reCAPTCHA.
            pageurl (str): The URL where the reCAPTCHA is present.
            action (str): The action parameter for reCAPTCHA v3.
            enterprise (bool): An enterprise verison of reCAPTCHA v3.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The reCAPTCHA solution token if successful, None otherwise.
        """
        task_id = await self._create_recaptcha_v3_task(
            sitekey, pageurl, action, enterprise, proxy
        )
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def recaptcha_v3_sync(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool = False,
        proxy: Optional[str] = None,
    ) -> Optional[str]:
        """
        Solve a reCAPTCHA v3 synchronously.

        Args:
            sitekey (str): The site key for the reCAPTCHA.
            pageurl (str): The URL where the reCAPTCHA is present.
            action (str): The action parameter for reCAPTCHA v3.
            enterprise (bool): An enterprise verison of reCAPTCHA v3.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The reCAPTCHA solution token if successful, None otherwise.
        """
        return asyncio.run(
            self.recaptcha_v3(
                sitekey=sitekey,
                pageurl=pageurl,
                action=action,
                enterprise=enterprise,
                proxy=proxy,
            )
        )

    async def recaptcha_v2(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool = False,
        proxy: Optional[str] = None,
    ) -> Optional[str]:
        """
        Solve a reCAPTCHA v2 asynchronously.

        Args:
            sitekey (str): The site key for the reCAPTCHA.
            pageurl (str): The URL where the reCAPTCHA is present.
            action (str): The action parameter for reCAPTCHA v2.
            enterprise (bool): An enterprise verison of reCAPTCHA v2.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The reCAPTCHA solution token if successful, None otherwise.
        """
        task_id = await self._create_recaptcha_v2_task(
            sitekey, pageurl, action, enterprise, proxy
        )
        if not task_id:
            return None
        return await asyncio.wait_for(
            self._wait_for_task_completion(task_id), timeout=self.timeout
        )

    def recaptcha_v2_sync(
        self,
        sitekey: str,
        pageurl: str,
        action: str,
        enterprise: bool = False,
        proxy: Optional[str] = None,
    ) -> Optional[str]:
        """
        Solve a reCAPTCHA v2 synchronously.

        Args:
            sitekey (str): The site key for the reCAPTCHA.
            pageurl (str): The URL where the reCAPTCHA is present.
            action (str): The action parameter for reCAPTCHA v2.
            enterprise (bool): An enterprise verison of reCAPTCHA v2.
            proxy (str): Proxy to use for the request (fmt. http://login:password@address:port).

        Returns:
            Optional[str]: The reCAPTCHA solution token if successful, None otherwise.
        """
        return asyncio.run(
            self.recaptcha_v2(
                sitekey=sitekey,
                pageurl=pageurl,
                action=action,
                enterprise=enterprise,
                proxy=proxy,
            )
        )
