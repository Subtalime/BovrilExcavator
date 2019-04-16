# Works with Python 3.6
# When using Python 3.7 install https://github.com/Rapptz/discord.py/archive/rewrite.zip
# python -m pip install -U https://github.com/Rapptz/discord.py/archive/rewrite.zip

from discord.ext.commands import Bot
from discord import Embed
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.operations import add, subtract
import asyncio
import re
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from settings import BOT_DB, BOT_ID, BOT_LOG, BOT_PREFIX, STATUS_LENGTH

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("excav")
logger.setLevel(logging.DEBUG)
handler = RotatingFileHandler(filename=BOT_LOG
                                      , encoding="utf-8"
                                      , mode="a"
                                      , maxBytes=1024*10000)
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
        try:
            # handle DB entry
            self.db_action.insert({'issuer': cmdr.id
                                   , 'user': user.id
                                   , 'action': 'add'
                                   , 'amount': amount
                                   , 'when': datetime.now().timetuple()})
            query = Query()
            if self.db_lending.contains(query.id == user.id):
                self.db_lending.upsert(add('borrowed', amount), query.id == user.id)
            else:
                self.db_lending.insert({'id': user.id, 'user': user.name, 'borrowed': amount})
            logger.info("{} handed to {} \"{}\" Excavators".format(cmdr, user, amount))
            result = self.db_lending.get(query.id == user.id)
            self.errlog_add("Given {} **{}** Excavators. He has now **{}** in Total".
                            format(user.name, amount, result['borrowed']))
        except Exception as e:
            logger.error("Error occurred: {}".format(e), exc_info=True)

    @asyncio.coroutine
    def my_del(self, cmdr, user, amount):
        if not user or not amount:
            self.errlog_add("No \"client\" ({}) or \"amount\" ({}) given!".format(user, amount))
            return
        # handle DB entry
        try:
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
        except Exception as e:
            logger.error("Error occurred: {}".format(e), exc_info=True)

    @staticmethod
    def get_date(rec):
        tup = rec['when'][0:6]
        return datetime(*tup)

    def action_output(self, context, record):
        # Member may no longer exist, so get_member may fail
        try:
            issuer = context.guild.get_member(record['issuer'])
            lender = context.guild.get_member(record['user'])
            w = datetime(*record['when'][0:6])
            when = w.strftime("%Y-%m-%d %H:%M:%S")
            self.errlog_add("{} actioned \'{}\' of {} Excavators to {} on {}".
                            format(issuer.name,
                                   record['action'],
                                   record['amount'],
                                   lender.name,
                                   when))
        except Exception as e:
            logger.error("Error occurred: {}".format(e), exc_info=True)

    @asyncio.coroutine
    def my_status(self, context, messages, usr):
        query = Query()
        try:
            if usr:
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
                    ordered = sorted(result, key=lambda k: self.get_date(k), reverse=True)
                    for index, res in enumerate(ordered):
                        self.action_output(context, res)
                        if index == messages:
                            break
                else:
                    self.errlog_add("There are not Actions regarding User {}".format(usr.name))
            else:
                result = self.db_lending.all()
                if result:
                    for res in result:
                        lender = context.guild.get_member(res['id'])
                        self.errlog_add("**{}** currently has **{}** Excavators".
                                        format(lender.name, res['borrowed']))
                result = self.db_action.all()
                if result:
                    ordered = sorted(result, key=lambda k: self.get_date(k), reverse=True)
                    for index, res in enumerate(ordered):
                        self.action_output(context, res)
                        if index == messages:
                            break
        except Exception as e:
            logger.error("Error occurred: {}".format(e), exc_info=True)


my_bot = MyExcavatorBot(command_prefix=BOT_PREFIX, case_insensitive=True)


@my_bot.command(pass_context=True, hidden=False)
async def help(ctx, *cog):
    logger.debug("CMD: {} {}".format(ctx.message.author, ctx.message.clean_content))
    if not cog:
        help_msg = Embed(title="Command listing and uncategorized commands",
                         description="Use \"!help **cmd**\" to find out more about the cog",
                         color=0x27a73e)
        cogs_desc = ""
        for x in my_bot.commands:
            cogs_desc += ("{}{} - {}\n".format(my_bot.command_prefix, x.name, x.signature))
        help_msg.add_field(name="cmds", value=cogs_desc[0:len(cogs_desc)-1])
    else:
        help_msg = Embed(color=0x27a73e, title="{} Command Listing".format(cog))
        for x in my_bot.commands:
            if x.name in cog:
                help_msg.add_field(name="{0}{1.name}".format(my_bot.command_prefix, x),
                                   value="Usage: {}\n{}".format(x.signature, x.help))
    await ctx.channel.send(embed=help_msg)


# return Status of Excavators
@my_bot.command(pass_context=True,
                hidden=False,
                brief="Returns status of a given User or last X entries",
                usage="<{}>s [@User] [number of messages (default {})]".format(
                    my_bot.command_prefix, STATUS_LENGTH),
                help="Gives status of a user and last 5 actions on the user.\n"
                     "You may control the number of actions to be printed out.\n"
                     "If you omit the user, all currently borrowed and the last"
                     " {} action messages will be shown.\n".format(STATUS_LENGTH)
                )
async def s(ctx):
    logger.debug("CMD: {} {}".format(ctx.message.author, ctx.message.clean_content))
    usr = None
    if len(ctx.message.mentions) > 0:
        usr = ctx.message.mentions[0]
    res = re.findall("(\d+)$", ctx.message.content)
    messages = abs(int(res[0])) if len(res) > 0 else STATUS_LENGTH
    await my_bot.my_status(ctx, messages, usr)
    await print_errors(ctx.channel)


# handing out Excavator
@my_bot.command(pass_context=True,
                hidden=False,
                brief="Used to hand out Excavators to a User",
                usage="{}a <@User> [number of Excavators (default 5)]".format(my_bot.command_prefix),
                help="Used to log Excavators being handed out to users. "
                     "This enables us to keep track where they are.\n"
                     "Anyone with the correct rights can Give or Take back "
                     "Excavators for any User.\n"
                     "Make sure you enter the correct number of Excavators, "
                     "else it defaults to 5\n"
                )
async def a(ctx):
    logger.debug("CMD: {} {}".format(ctx.message.author, ctx.message.clean_content))
    if not len(ctx.message.mentions):
        logger.warning("No/Invalid User mentioned : {}".format(ctx.message.content))
        ctx.channel.send("No/Invalid user mentioned")
        return
    usr = ctx.message.mentions[0]
    # don't react on Bot
    if usr.id == my_bot.user.id:
        logger.warning("{} Tried to add to Bot ({}): {}".format(usr.id, my_bot.user.id,
                                                                ctx.message.clean_content))
        ctx.channel.send("Invalid user mentioned")
        return
    res = re.findall("(\d+)$", ctx.message.content)
    val = abs(int(res[0])) if len(res) > 0 else 5
    await my_bot.my_add(ctx.message.author, usr, val)
    await print_errors(ctx.channel)


# handing back Excavator
@my_bot.command(pass_context=True,
                hidden=False,
                brief="Used to register a return of Excavators from a User",
                usage="{}d <@User> [number of Excavators (default 5)]".format(my_bot.command_prefix),
                help="Used to log Excavators being handed back to the corp."
                     "This enables us to keep track where they are.\n"
                     "Anyone with the correct rights can Give or Take back Excavators "
                     "for any User.\n"
                     "Make sure you enter the correct number of Excavators, "
                     "else it defaults to 5\n"
                )
async def d(ctx):
    logger.debug("CMD: {} {}".format(ctx.message.author, ctx.message.clean_content))
    if not len(ctx.message.mentions):
        logger.warning("No/Invalid User mentioned : {}".format(ctx.message.clean_content))
        ctx.channel.send("No/Invalid user mentioned")
        return
    usr = ctx.message.mentions[0]
    # don't react on Bot
    if usr.id == my_bot.user.id:
        logger.warning("{} Tried to remove from Bot ({}): {}".format(usr.id, my_bot.user.id,
                                                                     ctx.message.clean_content))
        ctx.channel.send("Invalid user mentioned")
        return
    res = re.findall('(\d+)$', ctx.message.content)
    val = abs(int(res[0])) if len(res) > 0 else 5
    await my_bot.my_del(ctx.message.author, usr, val)
    await print_errors(ctx.channel)


@asyncio.coroutine
async def print_errors(channel):
    if my_bot.has_errors():
        for err in my_bot.errlog_fetch():
            logger.info("```{}: {}```".format(channel.name, err))
            await channel.send(err)


my_bot.run(BOT_ID)

