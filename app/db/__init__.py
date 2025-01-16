from config import Config
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

database = TinyDB(Config.DATABASE, storage=CachingMiddleware(JSONStorage))

