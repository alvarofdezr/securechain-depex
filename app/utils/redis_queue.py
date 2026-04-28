from json import dumps

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.schemas import PackageMessageSchema
from app.settings import settings


class RedisQueue:
    """Asynchronous Redis stream-based message queue for package processing.

    Provides a producer interface for enqueuing package analysis messages and
    managing message acknowledgments and dead-letter queue operations. Uses Redis
    Streams with consumer groups for reliable, asynchronous package processing.

    Attributes:
        r: Async Redis client instance with response decoding enabled.
        _stream_initialized: Internal flag tracking consumer group initialization state.
    """

    def __init__(self, host: str, port: int, db: int = 0):
        """Initializes a Redis queue client with connection parameters.

        Args:
            host: Redis server hostname or IP address.
            port: Redis server port number.
            db: Redis database number (default: 0).
        """
        self.r = Redis(host=host, port=port, db=db, decode_responses=True)
        self._stream_initialized = False

    @classmethod
    def from_env(cls) -> RedisQueue:
        """Creates a RedisQueue instance using environment configuration settings.

        Retrieves connection parameters from the application settings module,
        providing a convenient factory method for dependency injection.

        Returns:
            A new RedisQueue instance configured from environment variables.

        Note:
            Requires REDIS_HOST, REDIS_PORT, and REDIS_DB environment variables
            to be set in the application settings.
        """
        return cls(settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)

    async def _ensure_stream(self) -> None:
        """Ensures the Redis Stream and consumer group exist, creating them if necessary.

        Idempotent operation that initializes the stream with the configured consumer group.
        Handles the 'BUSYGROUP' error gracefully if the group already exists.
        Sets the internal flag to prevent redundant initialization on subsequent calls.

        Raises:
            ResponseError: If stream creation fails for reasons other than group already existing.
        """
        if self._stream_initialized:
            return
        try:
            await self.r.xgroup_create(
                settings.REDIS_STREAM, settings.REDIS_GROUP, id="0-0", mkstream=True
            )
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._stream_initialized = True

    async def add_package_message(self, message: PackageMessageSchema) -> str:
        """Enqueues a package analysis message to the Redis Stream.

        Serializes the package message to JSON, ensures the stream is initialized,
        and adds the message to the configured Redis Stream.

        Args:
            message: PackageMessageSchema instance containing package details,
                constraints, and analysis parameters.

        Returns:
            The Redis message ID (format: "timestamp-sequence") identifying the enqueued message.

        Raises:
            ResponseError: If Redis operation fails.
        """
        await self._ensure_stream()
        message_dict = message.model_dump(mode="json")
        raw_json = dumps(message_dict)
        msg_id = await self.r.xadd(settings.REDIS_STREAM, {"data": raw_json})
        return msg_id

    async def ack(self, msg_id: str) -> None:
        """Acknowledges successful processing of a message in the consumer group.

        Removes the message from the pending entries list, indicating that
        the consumer has successfully processed it and it can be discarded.

        Args:
            msg_id: The Redis message ID to acknowledge (format: "timestamp-sequence").

        Raises:
            ResponseError: If acknowledgment fails.
        """
        await self.r.xack(settings.REDIS_STREAM, settings.REDIS_GROUP, msg_id)

    async def dead_letter(self, msg_id: str, raw: str, error: str) -> None:
        """Routes a failed message to the dead-letter queue with error context.

        Enqueues the original message data and error information to a separate
        Redis Stream for failed messages, then acknowledges the original message
        to remove it from the active processing queue.

        Args:
            msg_id: The original message ID to acknowledge after dead-lettering.
            raw: The original message data (JSON string) that failed processing.
            error: Error description or stack trace explaining the failure reason.

        Raises:
            ResponseError: If dead-letter or acknowledgment operation fails.
        """
        await self.r.xadd(f"{settings.REDIS_STREAM}-dlq", {"data": raw, "error": error})
        await self.ack(msg_id)
