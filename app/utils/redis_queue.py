from json import dumps

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.schemas import PackageMessageSchema
from app.settings import settings


class RedisQueue:
    def __init__(self, host: str, port: int, db: int = 0):
        self.r = Redis(host=host, port=port, db=db, decode_responses=True)
        self._stream_initialized = False

    @classmethod
    def from_env(cls) -> RedisQueue:
        return cls(settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)

    async def _ensure_stream(self) -> None:
        if self._stream_initialized:
            return
        try:
            await self.r.xgroup_create(settings.REDIS_STREAM, settings.REDIS_GROUP, id="0-0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._stream_initialized = True

    async def add_package_message(self, message: PackageMessageSchema) -> str:
        await self._ensure_stream()
        message_dict = message.model_dump(mode="json")
        raw_json = dumps(message_dict)
        msg_id = self.r.xadd(settings.REDIS_STREAM, {"data": raw_json})
        return msg_id

    async def ack(self, msg_id: str) -> None:
        await self.r.xack(settings.REDIS_STREAM, settings.REDIS_GROUP, msg_id)

    async def dead_letter(self, msg_id: str, raw: str, error: str) -> None:
        await self.r.xadd(f"{settings.REDIS_STREAM}-dlq", {"data": raw, "error": error})
        await self.ack(msg_id)
