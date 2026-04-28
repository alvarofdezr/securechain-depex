from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import asyncio
from redis.exceptions import ResponseError
from app.schemas import PackageMessageSchema
from app.utils.redis_queue import RedisQueue

class TestRedisQueue:

    @pytest.fixture
    def mock_redis(self):
        with patch("app.utils.redis_queue.Redis") as mock:
            redis_instance = MagicMock()
            redis_instance.xgroup_create = AsyncMock()
            redis_instance.xadd = AsyncMock()
            redis_instance.xack = AsyncMock()
            mock.return_value = redis_instance
            yield redis_instance

    @pytest.fixture
    async def redis_queue(self, mock_redis):
        mock_redis.xgroup_create.return_value = None
        queue = RedisQueue(host="localhost", port=6379, db=0)
        await queue._ensure_stream() 
        return queue

    @pytest.fixture
    def package_message(self):
        return PackageMessageSchema(
            node_type="PyPIPackage",
            package="fastapi",
            vendor="n/a",
            repository_url="https://github.com/tiangolo/fastapi",
        )

    @pytest.mark.asyncio
    async def test_init_creates_stream_group(self, mock_redis):
        mock_redis.xgroup_create.return_value = None
        queue = RedisQueue(host="localhost", port=6379, db=1)
        await queue._ensure_stream()
        mock_redis.xgroup_create.assert_called()

    @pytest.mark.asyncio
    async def test_add_package_message(self, redis_queue, package_message):
        redis_queue.r.xadd.return_value = "1234567890-0"
        msg_id = await redis_queue.add_package_message(package_message)
        assert msg_id == "1234567890-0"
        redis_queue.r.xadd.assert_called()

    @pytest.mark.asyncio
    async def test_ack_message(self, redis_queue):
        redis_queue.r.xack.return_value = 1
        await redis_queue.ack("1234567890-0")
        redis_queue.r.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_dead_letter_adds_to_dlq_and_acks(self, redis_queue):
        redis_queue.r.xadd.return_value = "dlq-msg-id"
        redis_queue.r.xack.return_value = 1
        await redis_queue.dead_letter("1234567890-0", '{"test": "fail"}', "error")
        redis_queue.r.xadd.assert_called_once()
        redis_queue.r.xack.assert_called_once()