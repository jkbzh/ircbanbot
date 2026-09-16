#!/bin/env python3

# script for downloading / uploading gline/kline bans from ngircd
# usage ircbanbot -f /path/to/configure/file
#                 -d [download glines]
#                 -u [upload glines]
#
# Author: J. Kahan (W3C)
# 14/Feb/2025
#
# Changes:
# 18/12/2025 : improve the comparison between current and previous
#              gline json files.  review the loginfo and sysexit error
#              codes to ease integration with systemd
#
import argparse
import functools
import json
import logging
import os
import shutil
import ssl
import sys

from datetime import datetime
from time import sleep

from dotenv import dotenv_values

import irc.client
import irc

log = logging.getLogger(__name__)

class IRCBanBot(irc.client.SimpleIRCClient):
    # event flow:
    # if nickname on use, write notice and quit
    # on_welcome (connected to irc server) : request oper
    ## download gline stats
    # on_youreoper : request stats gline
    # on_statskline : store glines to file
    # on_endofstats : close file
    ## upload glines
    # on_youreoper : send stats to server
    # ...
    def __init__(self, bot_nickname="banbot", bot_notices=None, oper_password=None,
                 gline_file=None, bot_action=None):
        irc.client.SimpleIRCClient.__init__(self)
        self.bot_nickname = bot_nickname
        self.bot_notices = bot_notices
        self.oper_password = oper_password
        self.gline_file = gline_file
        self.gline_fp = None
        self.bot_action = bot_action
        self.glines = None
        self.abort_msg = f"Aborting GLINE {self.bot_action}"

    #
    # helper functions
    #

    def ordered(self, obj):
        """sorts a different kinds of list structures"""
        if isinstance(obj, dict):
            return sorted((k, self.ordered(v)) for k, v in obj.items())
        elif isinstance(obj, list):
            return sorted(self.ordered(x) for x in obj)
        else:
            return obj

    def gline_file_read(self, filename):
        """reads the glines from filename and returns them.
           if file doesn't exist or is empty, returns None."""
        glines = None

        if not os.path.exists(filename):
            return None

        try:
            with open(filename, "r") as fp:
                glines = json.load(fp)
        except OSError as e:
            log.error(f"couldn't read {self.gline_file}: {e}")
            log.error("aborting")
            raise SystemExit(1)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.error(f"couldn't parse {self.gline_file}: {e}")
            log.error("aborting glines upload")
            raise SystemExit(1)

        return glines

    def on_login_failed(self, connection, event):
        log.error(f"login_failed: {event.arguments[0]}. {self.abort_msg}")
        raise SystemExit(1)

    def on_passwdmismatch(self, connection, event):
        log.error(f"passwdmismatch: wrong operator password for this account. {self.abort_msg}")
        self.connection.quit()
        raise SystemExit(1)

    def on_nicknameinuse(self, connection, event):
        # if bot's nickname is in use, log a warning on irc and quit;
        # we don't have the access rights to oper in this case
        log.error(f"nicknameinuse: {self.bot_nickname} in use. {self.abort_msg}")
        if (self.bot_notices):
            connection.nick(connection.get_nickname() + "_")
            self.connection.privmsg(
                self.bot_notices,
                f"{self.bot_nickname} can't acquire its nickname. {self.abort_msg}"
            )
        raise SystemExit(1)

    def on_error(self, connection, event):
        if event and event.target:
            # this event is called for both when there are errors
            # and each time a connection is closed. We ignore the latter.
            if event.target == "Closing connection":
                return
            log.error(event.target)
        log.error(self.abort_msg)
        raise SystemExit(1)

    def on_welcome(self, connection, event):
        log.debug("welcome")
        # register as an irc operator
        connection.oper(self.bot_nickname, self.oper_password)

    def on_youreoper(self, connection, event):
        log.debug("youreoper")

        if self.bot_action == "download":
            self.glines_download(connection)
        elif self.bot_action == "upload":
            self.glines_upload(connection)
        else:
            log.error(f"unsupported bot action : {self.bot_action}")
            log.error("aborting")
            raise SystemExit(1)

    def on_statskline(self, connection, event):
        log.debug("statskline")
        log.debug(event)

        banned_user=event.arguments[1]
        ban_time=event.arguments[2]
        ban_msg=event.arguments[3]

        gline = { 'user': banned_user, 'time': ban_time, 'msg': ban_msg }
        self.glines.append(gline)

    def on_endofstats(self, connection, event):
        log.debug("endofstats")

        if len(self.glines) == 0:
            log.info("server didn't return any glines")
            log.info("aborting")
            raise SystemExit()

        # check if the downloaded glines are different from those
        # currently stored
        glines_current = self.gline_file_read(self.gline_file)

        if self.ordered(glines_current) == self.ordered(self.glines):
            log.info("no change from previous downloaded glines, aborting")
            raise SystemExit()

        # glines changes, backup previous file and save new glines
        gline_file_new = f"{self.gline_file}.new"

        try:
            with open(f"{gline_file_new}", "w") as fp:
                json.dump(self.glines, fp, sort_keys=True, indent=" ", separators=(',', ':'))
                # next line is for avoiding the "no newline at end of file" error in txt files
                print("", file=fp)
            os.chmod(gline_file_new, 0o644)
        except OSError as e:
            log.error(f"Couldn't open {gline_file_new}: {e}")
            log.error("aborting glines download_glines")
            raise SystemExit(1)
        except TypeError as e:
            log.error(f"Couldn't dump json glines: {e}")
            log.error("aborting glines download")
            raise SystemExit(1)

        # backup the previous gline file by copying it to a timestamped filename
        if os.path.isfile(self.gline_file):
            date = datetime.today().strftime('%Y-%m-%dT%H:%M:%S')
            gline_file_old = f"{self.gline_file}.{date}"
            try:
                # preserve metadata when copying file
                shutil.copy2(self.gline_file, gline_file_old)
            except e:
                log.error(f"couldn't copy {self.gline_file} to {gline_file_old}: {e}")
                log.error("aborting glines download")
                raise SystemExit(1)
        try:
            shutil.move(gline_file_new, self.gline_file)
        except e:
            log.error(f"couldn't move {gline_file_new} to {gline_file}: {e}")
            log.error("aborting glines download")
            raise SystemExit(1)

        log.info("glines download completed")
        raise SystemExit()

    def on_disconnect(self, connection, event):
        log.debug("disconnect")

    def glines_download(self, connection):
        log.info("requesting server glines")
        self.glines = []
        connection.stats('GLINE')

    def server_gline_add(self, connection, user, bantime, banmsg):
        # the irc.client lib doesn't have a specific gline command, so
        # we made one with its primitives
        # sample line:
        # /GLINE sourcify_bot!~i_m_the_sourcify_bot@*.* 0 :unauthorized bot
        connection.send_items('GLINE', user, bantime, banmsg)

    def server_gline_del(self, connection, user):
        # sending only the user data will delete the corresponding gline
        connection.send_items('GLINE', user)

    def glines_upload(self, connection):
        log.info("uploading server glines")

        glines = self.gline_file_read(self.gline_file)

        if glines is None:
            log.info(f"gline file {self.gline_file} is empty or doesn't exist")
            log.info("aborting glines upload")
            raise SystemExit()

        for gline in glines:
            delete_gline = False

            user = gline['user']

            if 'time' in gline:
                bantime = gline['time']
            else:
                delete_gline = True

            if 'msg' in gline:
                banmsg = f":{gline['msg']}"
            else:
                banmsg = ':'

            if delete_gline:
                self.server_gline_del(self.connection, user)
            else:
                self.server_gline_add(self.connection, user, bantime, banmsg)

        log.info("glines upload completed")
        raise SystemExit()

def get_args():
    parser = argparse.ArgumentParser(
        description="download or upload the ngircd glines."
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument('-d', '--download', help='download the glines to a file',
                    action="store_true")
    group.add_argument('-u', '--upload', help='upload the glines from a file to the server',
                    action="store_true")
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-q", "--quiet", help='only log errors',
                           action="store_true")
    log_group.add_argument("--debug",
                           help='display all debug messages, including IRC protocol exchanges',
                           action="store_true")
    parser.add_argument(
        '-f', '--config-file', type=str, default='.env',
        help="path pointing to a config file (default '.env'")

    return parser.parse_args()

def read_config(config_file='.env'):
    config = {
        **dotenv_values(config_file),  # load shared development variables
        **os.environ,  # override loaded values with environment variables
    }
    return config

def main():
    args = get_args()

    if args.quiet:
        log_level = logging.ERROR
    elif args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(level=log_level)
    log.setLevel(log_level)

    if args.download:
        bot_action="download"
    elif args.upload:
        bot_action="upload"
    else:
        log.error("no action specified. aborting")
        sys.exit(-1)

    config = read_config(args.config_file)

    if not config:
        print(f"{args.config_file} configuration file is empty / non-existent",
              file=sys.stderr)
        sys.exit(-1)

    if 'BOT_NICKNAME' in config:
        bot_nickname = config['BOT_NICKNAME']
    else:
        bot_nickname = "banbot"

    bot_notices = config['BOT_NOTICES']
    server = config['IRC_SERVER']
    port = int(config['IRC_PORT'])
    oper_password = config['IRC_OPERATOR_PASSWORD']
    account_name = config['ACCOUNT_NAME']
    account_password = config['ACCOUNT_PASSWORD']
    gline_file = config['GLINE_FILE']

    if 'SERVER_WAIT' in config:
        server_wait = int(config['SERVER_WAIT'])
    else:
        server_wait = 0

    # sleep some seconds to give time for the ngircd to launch
    sleep(server_wait)

    c = IRCBanBot(
        bot_nickname=bot_nickname,
        bot_notices=bot_notices,
        oper_password=oper_password,
        gline_file=gline_file,
        bot_action=bot_action,
    )

    try:
        context = ssl.create_default_context()
        wrapper = functools.partial(context.wrap_socket, server_hostname=server)

        c.connect(
            server,
            port,
            bot_nickname,
            account_password,
            #sasl_login=account_name,
            username=account_name,
            connect_factory=irc.connection.Factory(wrapper=wrapper),
        )
    except irc.client.ServerConnectionError as e:
        print(e)
        raise SystemExit(1)

    try:
        c.start()
    finally:
        c.connection.disconnect()

if __name__ == "__main__":
    main()
