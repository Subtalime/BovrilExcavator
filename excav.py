# Works with Python 3.6
# When using Python 3.7 install https://github.com/Rapptz/discord.py/archive/rewrite.zip
# python -m pip install -U https://github.com/Rapptz/discord.py/archive/rewrite.zip

from discord.ext.commands import Bot, Context
from discord import Embed
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.operations import add, subtract
import asyncio
import re

from datetime import datetime
import logging
from settings import BOT_DB, BOT_ID, BOT_LOG, BOT_PREFIX

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("excav")
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename=BOT_LOG, encoding="utf-8", mode="w")
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


class MyExcavatorBot(Bot):

    def __init__(self, command_prefix, formatter=None, description=None, **options):
        super().__init__(command_prefix, formatter, description, **options)
        self.db = TinyDB(BOT_DB, storage=JSONStorage, sort_keys=True, indent=3)
        self.errors = []
        self.db_lending = self.db.table('lendings')
        self.db_action = self.db.table('action')

    def __del__(self):
        if self.db:
            self.db.close()

    def has_errors(self):
        return len(self.errors)

    def errlog_fetch(self):
        for error in self.errors:
            yield error
        self.errors = []

    def errlog_add(self, msg):
        self.errors.append(msg)

    @asyncio.coroutine
    def my_add(self, cmdr, user, amount: int):
        if not user or not amount:
            self.errlog_add("No \"client\" ({}) or \"amount\" ({}) given!".format(user.name
                                                                                  , amount))
            return
        # handle DB entry
        self.db_action.insert({'issuer': cmdr.id
                               , 'user': user.id
                               , 'action': 'add'
                               , 'amount': amount
                               , 'when': datetime.now().timetuple()})
        query = Query()
        if self.db_lending.contains(query.id == user.id):
            self.db_lending.update(add('borrowed', amount), query.id == user.id)
        else:
            self.db_lending.insert({'id': user.id, 'user': user.name, 'borrowed': amount})
        logger.info("{} handed to {} \"{}\" Excavators".format(cmdr, user, amount))
        result = self.db_lending.get(query.id == user.id)
        self.errlog_add("Given {} **{}** Excavators. He has now **{}** in Total".format(user.name, amount, result['borrowed']))

    @asyncio.coroutine
    def my_del(self, cmdr, user, amount):
        if not user or not amount:
            self.errlog_add("No \"client\" ({}) or \"amount\" ({}) given!".format(user, amount))
            return
        # handle DB entry
        self.db_action.insert({'issuer': cmdr.id
                               , 'user': user.id
                               , 'action': 'delete'
                               , 'amount': amount
                               , 'when': datetime.now().timetuple()
                               })
        query = Query()
        if self.db_lending.contains(query.id == user.id):
            self.db_lending.update(subtract('borrowed', amount), query.id == user.id)
        else:
            self.errlog_add("User {} never borrowed any Excavators. Ignored!".format(user.name))
            return
        if self.db_lending.contains((query.id == user.id) & (query.borrowed <= 0)):
            self.db_lending.remove(query.id == user.id)
        logger.info("{} handed back from {} {} Excavators".format(cmdr, user, amount))
        result = self.db_lending.get(query.id == user.id)
        if len(result) == 0:
            result['borrowed'] = 0
        self.errlog_add("{} returned **{}** Excavators. He now has **{}**".
                        format(user.name, amount, result['borrowed']))

    @staticmethod
    def get_date(rec):
        return datetime(*rec['when'][0:6])


    @asyncio.coroutine
    def my_status(self, usr=None, messages=5):
        if usr:
            query = Query()
            # current Borrowing
            result = self.db_lending.get(query.id == usr.id)
            if result:
                self.errlog_add("**{}** currently has **{}** Excavators".
                                format(usr.name, result['borrowed']))
            else:
                self.errlog_add("**{}** has no Excavators".format(usr.name))
            # Status Logs
            result = self.db_action.search(query.user == usr.id)
            if result:
                # TODO: sort by timestamp
                ordered = sorted(result, key=lambda k: self.get_date(k), reverse=True)
                for index, res in enumerate(ordered):
                    self.errlog_add("{}".format(res))
                    if index == messages:
                        break


my_bot = MyExcavatorBot(command_prefix=BOT_PREFIX, case_insensitive=True)


# return Status of Excavators
@my_bot.command(pass_context=True, hidden=False)
async def s(ctx):
    usr = None
    if len(ctx.message.mentions) > 0:
        usr = ctx.message.mentions[0]
    res = re.findall("(\d+)$", ctx.message.content)
    messages = abs(int(res[0])) if len(res) > 0 else None
    await my_bot.my_status(usr, messages)
    await print_errors(ctx.channel)


# handing out Excavator
@my_bot.command(pass_context=True, hidden=False)
async def a(ctx):
    assert len(ctx.message.mentions), logger.warning("No User mentioned : {}".
                                                     format(ctx.message.content))
    usr = ctx.message.mentions[0]
    # don't react on Bot
    assert usr.id == my_bot.user.id, logger.warning("Tried to add to Bot : {}".
                                                    format(ctx.message.content))
    res = re.findall("(\d+)$", ctx.message.content)
    val = abs(int(res[0])) if len(res) > 0 else 5
    await my_bot.my_add(ctx.message.author, usr, val)
    await print_errors(ctx.channel)


# handing back Excavator
@my_bot.command(pass_context=True, hidden=False)
async def d(ctx):
    assert len(ctx.message.mentions), logger.warning("No User mentioned : {}".
                                                     format(ctx.message.content))
    usr = ctx.message.mentions[0]
    # don't react on Bot
    assert usr.id == my_bot.user.id, logger.warning("Tried to delete from Bot : {}".
                                                    format(ctx.message.content))
    res = re.findall('(\d+)$', ctx.message.content)
    val = abs(int(res[0])) if len(res) > 0 else 5
    await my_bot.my_del(ctx.message.author, usr, val)
    await print_errors(ctx.channel)


@asyncio.coroutine
async def print_errors(channel):
    if my_bot.has_errors():
        # await channel.send("")
        for err in my_bot.errlog_fetch():
            logging.info("```{}: {}```".format(channel.name, err))
            await channel.send(err)
        # await channel.send("```")


my_bot.run(BOT_ID)

