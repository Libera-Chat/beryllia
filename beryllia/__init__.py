import asyncio, ipaddress, re, time
from collections import OrderedDict
from datetime    import datetime
from typing      import Dict, List, Optional, Set, Tuple
from typing      import OrderedDict as TOrderedDict

from irctokens import build, Line
from ircrobots import Bot as BaseBot
from ircrobots import Server as BaseServer

from ircstates.numerics import *
from ircrobots.ircv3    import Capability
from ircrobots.matching import ANY, Folded, Response, SELF

from .config    import Config
from .database  import Database
from .normalise import RFC1459SearchNormaliser
from .util      import oper_up, pretty_delta

RE_CLICONN   = re.compile(r"^\*{3} Notice -- Client connecting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) \[(?P<ip>\S+)\] \S+ \S+ \[(?P<real>.*)\]$")
RE_CLIEXIT   = re.compile(r"^\*{3} Notice -- Client exiting: (?P<nick>\S+) \((?P<user>[^@]+)@(?P<host>\S+)\) .* \[(?P<ip>\S+)\]$")
RE_KLINEADD  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} added (?:temporary|global) (?P<duration>\d+) min\. K-Line for \[(?P<mask>\S+)\] \[(?P<reason>.*)\]$")
RE_KLINEDEL  = re.compile(r"^\*{3} Notice -- (?P<source>[^{]+)\{(?P<oper>[^}]+)\} has removed the (?:temporary|global) K-Line for: \[(?P<mask>\S+)\]$")
RE_KLINEEXIT = re.compile(r"^\*{3} Notice -- KLINE active for (?P<nickname>[^[]+)\[\S+ .(?P<mask>\S+).$")

CAP_OPER = Capability(None, "solanum.chat/oper")

class Server(BaseServer):
    database: Database

    def __init__(self,
            bot:    BaseBot,
            name:   str,
            config: Config):

        super().__init__(bot, name)
        self.desired_caps.add(CAP_OPER)

        self._config  = config

        self._wait_for_exit: Dict[str, str] = {}

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass

    async def line_read(self, line: Line):
        now = time.monotonic()

        if line.command == RPL_WELCOME:
            await self.send(build("MODE", [self.nickname, "+g"]))
            oper_name, oper_file, oper_pass = self._config.oper
            await oper_up(self, oper_name, oper_file, oper_pass)

        elif line.command in {RPL_ENDOFMOTD, ERR_NOMOTD}:
            # we should now know our casemap, so connect database.
            # we need the casemap for this to normalise things for searching
            self.database = await Database.connect(
                self._config.db_user,
                self._config.db_pass,
                self._config.db_host,
                self._config.db_name,
                RFC1459SearchNormaliser()
            )

        elif line.command == RPL_YOUREOPER:
            # F far cliconn
            # c near cliconn
            # k server kills
            # s oper kills, klines
            await self.send(build("MODE", [self.nickname, "-s+s", "+Fcks"]))

        elif (line.command == "NOTICE" and
                line.params[0] == "*" and
                line.source is not None and
                not "!" in line.source):

            # snote!

            message     = line.params[1]
            p_cliconn   = RE_CLICONN.search(message)
            p_cliexit   = RE_CLIEXIT.search(message)
            p_klineadd  = RE_KLINEADD.search(message)
            p_klinedel  = RE_KLINEDEL.search(message)
            p_klineexit = RE_KLINEEXIT.search(message)

            if p_cliconn is not None:
                nickname = p_cliconn.group("nick")
                username = p_cliconn.group("user")
                realname = p_cliconn.group("real")
                hostname = p_cliconn.group("host")

                ip: Optional[Union[IPv4Address, IPv6Address]] = None
                if not (ip_str := p_cliconn.group("ip")) == "0":
                    ip = ipaddress.ip_address(ip_str)

                await self.database.cliconn.add(
                    nickname, username, realname, hostname, ip
                )

            elif p_cliexit is not None:
                nickname = p_cliexit.group("nick")
                username = p_cliexit.group("user")
                hostname = p_cliexit.group("host")

                ip: Optional[str] = p_cliexit.group("ip")
                if ip == "0":
                    ip = None
                else:
                    ip = ipaddress.ip_address(ip).compressed

                if nickname in self._wait_for_exit:
                    mask     = self._wait_for_exit.pop(nickname)
                    kline_id = await self.database.kline.find(mask)
                    if kline_id is not None:
                        await self.database.kline_kill.add(
                            kline_id, nickname, username, hostname, ip
                        )

            elif p_klineadd is not None:
                source   = p_klineadd.group("source")
                oper     = p_klineadd.group("oper")
                mask     = p_klineadd.group("mask")
                duration = p_klineadd.group("duration")
                reason   = p_klineadd.group("reason")

                username, hostname  = mask.split("@")

                old_id = await self.database.kline.find(mask)
                id     = await self.database.kline.add(
                    source, oper, mask, int(duration)*60, reason
                )

                # if an existing k-line is being extended/updated, update
                # kills affected by the first k-line
                if old_id is not None:
                    db    = self.database
                    kills = await db.kline_kill.find_by_kline(old_id)
                    for kill_id in kills:
                        await db.kline_kill.set_kline(kill_id, id)

            elif p_klinedel is not None:
                source = p_klinedel.group("source")
                oper   = p_klinedel.group("oper")
                mask   = p_klinedel.group("mask")
                id     = await self.database.kline.find(mask)
                if id is not None:
                    await self.database.kline_remove.add(id, source, oper)

            elif p_klineexit is not None:
                nickname = p_klineexit.group("nickname")
                mask     = p_klineexit.group("mask")
                # we wait until cliexit because that snote has an IP in it
                self._wait_for_exit[nickname] = mask

        elif (line.command == "PRIVMSG" and
                not self.is_me(line.hostmask.nickname)):

            me  = self.nickname
            who = line.hostmask.nickname

            first, _, rest = line.params[1].partition(" ")
            if self.is_me(line.params[0]):
                # private message
                await self.cmd(who, who, first.lower(), rest, line.tags)
            elif rest:
                if first in [me, f"{me}:", f"{me},"]:
                    # highlight in channel
                    command, _, args = rest.partition(" ")
                    await self.cmd(
                        who, line.params[0], command.lower(), args, line.tags
                    )

    async def cmd(self,
            who:     str,
            target:  str,
            command: str,
            args:    str,
            tags:    Optional[Dict[str, str]]
            ):

        if tags and "solanum.chat/oper" in tags:
            attrib  = f"cmd_{command}"
            if hasattr(self, attrib):
                outs = await getattr(self, attrib)(who, args)
                for out in outs:
                    await self.send(build("NOTICE", [target, out]))

    async def cmd_help(self, nick: str, args: str):
        me      = self.nickname
        command = args.lstrip().split(" ", 1)[0]
        if not command:
            return [
                "available commands: kcheck",
                f"usage: /msg {me} help <command>"
            ]
        elif command == "kcheck":
            return [
                "search for bans that affected a nick/host/ip",
                f"usage: /msg {me} check <nick|host|ip> <query>"
            ]
        else:
            return ["unknown command"]

    async def cmd_kcheck(self, nick: str, sargs: str):
        args = sargs.split(None, 2)
        if len(args) > 1:
            type, query, *_ = args
            type = type.lower()
            now  = datetime.utcnow()

            if   type == "nick":
                fold  = self.casefold(query)
                kills = await self.database.kline_kill.find_by_nick(fold)
            elif type == "host":
                host  = query.lower()
                kills = await self.database.kline_kill.find_by_host(host)
            elif type == "ip":
                try:
                    addr = ipaddress.ip_address(query)
                except ValueError:
                    return [f"'{query}' isn't a valid IP"]
                kills = await self.database.kline_kill.find_by_ip(addr)
            else:
                return [f"unknown query type '{type}'"]

            outs: List[str] = []
            for kill_id in kills[:3]:
                kill   = await self.database.kline_kill.get(kill_id)
                kline  = await self.database.kline.get(kill.kline_id)
                remove = await self.database.kline_remove.get(
                    kill.kline_id
                )

                outs.append(
                    f"{kill.nickname}!{kill.username}@{kill.hostname}"
                    f" killed at {kill.ts.isoformat()}"
                )

                kts_human = pretty_delta(now-kline.ts)

                if remove is not None:
                    remover  = remove.oper or "unknown"
                    remove_s = f"\x0303removed\x03 by \x02{remover}\x02"
                elif kline.expire < now:
                    remove_s = "\x0303expired\x03"
                else:
                    remove_s = "\x0304active\x03"

                outs.append(
                    "  K-Line:"
                    f" {kline.mask}"
                    f" \x02{kts_human} ago\x02"
                    f" by \x02{kline.oper}\x02"
                    f" for {kline.duration//60} mins"
                    f" ({remove_s})"
                    f" {kline.reason}"
                )
            return outs or ["no results"]
        else:
            return ["please provide a type and query"]

    async def cmd_cliconn(self, nick: str, sargs: str):
        args = sargs.split(None, 2)
        if len(args) > 1:
            type, query, *_ = args
            type = type.lower()
            db   = self.database
            now  = datetime.utcnow()

            if   type == "ip":
                try:
                    ip  = ipaddress.ip_address(query)
                    ids = await db.cliconn.find_by_ip(ip)
                except ValueError:
                    try:
                        cidr = ipaddress.ip_network(query,  strict=False)
                        ids  = await db.cliconn.find_by_cidr(cidr)
                    except ValueError:
                        ids  = await db.cliconn.find_by_ip_glob(query)
            else:
                return [f"unknown query type '{type}'"]

            outs: List[str] = []
            for id in ids[:3]:
                c   = await db.cliconn.get(id)
                cts = pretty_delta(now-c.ts)
                outs.append(
                    f"\x02{cts}\x02 ago -"
                    f" {c.nickname}!{c.username}@{c.hostname}"
                    f" [{c.realname}]"
                )
            return outs or ["no results"]
        else:
            return ["please provide a type and query"]

    def line_preread(self, line: Line):
        print(f"< {line.format()}")
    def line_presend(self, line: Line):
        print(f"> {line.format()}")

class Bot(BaseBot):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config

    def create_server(self, name: str):
        return Server(self, name, self._config)

