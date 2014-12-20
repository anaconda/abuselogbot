#!/usr/bin/env python
import argparse
import logging
import re
import sys

from twisted.internet import reactor, ssl
from twisted.internet.task import LoopingCall
from wikitools import api, wiki as _wiki

from configurablebot import ConfigurableBot, ConfigurableBotFactory
from reloadableconfigparser import ParsingError, ReloadableConfigParser
from silenceprint import silence_print

__version__ = '1.4.2'

class AbuseLoggerBot(ConfigurableBot):
    def connectionLost(self, reason): # noqa
        self.stop_readers()
        self.readers = {}
        ConfigurableBot.connectionLost(self, reason)

    def connectionMade(self): # noqa
        # Shorter is better
        self.config = self.factory.config
        self.config_section = self.factory.config_section

        # Server password, but freenode forwards it to NickServ
        if self.config.has_option(self.config_section, 'password') and len(self.config.get(self.config_section, 'password')):
            self.password = self.config.get(self.config_section, 'password')

        self.slave_mode = self.config.getboolean(self.config_section, 'slave')
        self.master = self.config.get(self.config_section, 'master') if self.slave_mode else None
        self.autofailover = self.config.getboolean(self.config_section, 'autofailover')
        self.admin_hosts = self.config.get(self.config_section, 'admin_hosts').split()

        self.readers = {}
        self.load_wikis_configuration()

        ConfigurableBot.connectionMade(self)

    def get_wikis_for_channel(self, channel):
        return [wiki for wiki, channels in self.wikis_channels.items() if channel in channels]

    def irc_ERR_NICKNAMEINUSE(self, prefix, params): # noqa
        ConfigurableBot.irc_ERR_NICKNAMEINUSE(self, prefix, params)
        if self.password:
            # self.nickname is our *current* nickname, self.config_section is actually our original nickname
            # Note: this works on freenode
            self.msg('NickServ', 'GHOST %s' % self.config_section)
            self.setNick(self.config_section)

    def joined(self, channel):
        wikis = self.get_wikis_for_channel(channel)
        self.log.info('Joined channel %s (wiki%s: %s)', channel, 's' if len(wikis) > 1 else '', ', '.join(wikis))
        for wiki in wikis:
            if wiki not in self.readers:
                self.setup_reader(wiki)

    def load_wikis_configuration(self, reload=False):
        if reload:
            try:
                if not self.config.reload():
                    self.log.error('Configuration reload failed: unable to read configuration file.  Maybe it was moved/deleted?  Also, check permissions.')
                    return False
            except ParsingError as e:
                self.log.error('Configuration reload failed.  %s' % e.args)
                return False

        # Slaves read from master's section
        channels_section = self.master if self.slave_mode else self.config_section
        pairs = [item.split(':') for item in self.config.get(channels_section, 'wikis_channels').strip().split('\n')]
        new_wikis_channels = {wiki.strip(): channels.strip().split() for wiki, channels in pairs}
        new_channels = set([channel for channels in new_wikis_channels.values() for channel in channels])

        if reload:
            removed_wikis = set(self.wikis_channels.keys()) - set(new_wikis_channels.keys())
            added_wikis = set(new_wikis_channels.keys()) - set(self.wikis_channels.keys())
            removed_channels = self.channels - new_channels
            added_channels = new_channels - self.channels

            self.log.info('Finished reloading configuration.  Removed wikis: %s; added: %s; removed channels: %s; added: %s', ', '.join(removed_wikis) or 'none', ', '.join(added_wikis) or 'none', ', '.join(removed_channels) or 'none', ', '.join(added_channels) or 'none')

            if removed_wikis:
                self.stop_readers([reader for wiki, reader in self.readers.items() if wiki in removed_wikis])
                self.readers = {wiki: reader for wiki, reader in self.readers.items() if wiki not in removed_wikis}

            for reader in self.readers:
                self.readers[reader].load_wiki_configuration()

            for channel in removed_channels:
                self.leave(channel)

            for wiki in added_wikis:
                if set(new_wikis_channels[wiki]).issubset(self.channels) and not set(new_wikis_channels[wiki]).issubset(added_channels):
                    self.setup_reader(wiki)

        self.wikis_channels = new_wikis_channels
        self.channels = new_channels

        if reload:
            for channel in added_channels:
                self.join(channel)

            return True

    def post_item_for_wiki(self, wiki_name, item):
        channels = self.wikis_channels[wiki_name]
        for channel in channels:
            if not self.master or not self.slave_mode:
                # Master or slave temporarily promoted to master
                self.say(channel, self.readers[wiki_name].format_line(item))

    def privmsg(self, user, channel, msg):
        # Matches 'Bot hey', 'Bot, hey' or 'Bot: hey'
        matches = re.match('^%s[,:]?\s+(.+)' % self.nickname.lower(), msg.lower())
        if matches:
            # Someone is talking to me!!1
            user_host = user.split('@')[1]
            if user_host in self.admin_hosts:
                command = matches.group(1)
                user_nick = user.split('!')[0]

                if command == 'rehash':
                    self.log.info('Rehashing wikis configuration, requested by %s', user)
                    self.say(channel, '%s: trying to reload my configuration, please hang on...' % user_nick)
                    for bot in self.factory.bots:
                        if not bot.load_wikis_configuration(reload=True):
                            self.say(channel, '%s: configuration reload failed :-(.  An error was logged.' % user_nick)
                            break
                    else:
                        if channel in self.channels:
                            self.say(channel, '%s: configuration was reloaded successfully.' % user_nick)
                        else:
                            self.msg(user_nick, 'configuration was reloaded successfully.')
                elif command == 'start':
                    if self.slave_mode:
                        self.slave_mode = False
                        self.log.info('Promoted to master by %s', user)
                        self.say(channel, '%s: thank you for promoting me to master!  Hope %s comes back shortly.' % (user_nick, self.master))
                    else:
                        self.say(channel, "%s: I'm already master." % user_nick)
                elif command == 'stop':
                    if not self.slave_mode:
                        if self.master:
                            # Slave temporarily promoted to master
                            self.slave_mode = True
                            self.log.info('Back to slave mode: requested by %s', user)
                            self.say(channel, '%s: glad to hear that %s is back.' % (user_nick, self.master))
                        else:
                            # Actual master
                            self.say(channel, "%s: wrong bot? I'm the master one." % user_nick)
                    else:
                        self.say(channel, "%s: wrong bot? I'm already operating in slave mode." % user_nick)

    def reader_logged_in(self, reader):
        self.log.debug('Starting reader for %s', reader.wiki_name)
        try:
            reader.start()
        except api.APIError as e:
            if e.args[0] == 'aflblocked':
                self.readers.pop(reader.wiki_name)
                self.log.error("Oops!  I'm blocked on %s; skipping this wiki", reader.wiki_name)

    def setup_reader(self, wiki):
        reader = AbuseLogReader(self.config, self.master if self.master else self.config_section, wiki, self.post_item_for_wiki)
        self.readers.update({wiki: reader})
        reactor.callInThread(reader.login, self.reader_logged_in)

    def signedOn(self): # noqa
        self.log.info('Signed on, joining channels...')
        for channel in self.channels:
            self.join(channel)

    def stop_readers(self, readers=None):
        if not readers:
            readers = self.readers.values()
        for reader in readers:
            if reader.loop.running:
                reader.loop.stop()

    def userJoined(self, user, channel): # noqa
        if self.master and user == self.master and not self.slave_mode and self.autofailover:
            self.slave_mode = True
            self.log.info('My master %s is back, leaving master mode', self.master)

    def userQuit(self, user, quitMessage): # noqa
        if self.slave_mode and self.autofailover and user == self.master:
            self.slave_mode = False
            self.log.info('My master %s has just quit, entering master mode', self.master)

class AbuseLogReader(object):
    last_log_id = None
    log = None

    def __init__(self, config, config_section, wiki_name, callback):
        self.config = config
        self.config_section = config_section
        self.wiki_name = wiki_name
        self.wiki = _wiki.Wiki('https://%s/w/api.php' % self.wiki_name)
        self.username = config.get(self.config_section, 'wiki_user')
        self.password = config.get(self.config_section, 'wiki_password')
        self.callback = callback

        if self.callback.__self__.log:
            # We could use .getChild(), but then %(name)s would be 'bot.wiki', we want instead 'bot:wiki'
            self.log = logging.getLogger('%s:%s' % (self.callback.__self__.nickname, self.wiki_name))

        self.load_wiki_configuration()
        self.loop = LoopingCall(self.fetch_log)

    def format_line(self, item):
        return self.irc_format.format(user=item['user'].encode('utf-8'), filter_id=item['filter_id'], action=item['action'], page=item['title'].encode('utf-8'), result=item['result'], filter_description=item['filter'].encode('utf-8'), id=item['id'], wiki_address=self.wiki_name)

    @silence_print
    def fetch_log(self, ignore_callback=False):
        query_params = {
            'action': 'query',
            'list': 'abuselog',
            'aflprop': 'ids|user|title|action|result|filter'
        }
        request = api.APIRequest(self.wiki, query_params)

        try:
            result = request.query(querycontinue=False)
        except api.APIError as e:
            self.log.debug('Caught APIError in fetch_log: %s, isLoggedIn(%s)=%s', e, self.username, self.wiki.isLoggedIn(self.username))
            return

        items = result['query']['abuselog']
        items.reverse()
        if self.last_log_id:
            items = [item for item in items if item['id'] > self.last_log_id]

        if items:
            self.last_log_id = items[-1]['id']

        # Exclude ignored filters
        items = [item for item in items if item['filter_id'] not in self.ignored_filters]

        if not ignore_callback:
            for item in items:
                self.callback(self.wiki_name, item)

    def load_wiki_configuration(self):
        pairs = [item.split(':') for item in self.config.get(self.config_section, 'ignored_filters').strip().split('\n')]
        try:
            filters = [filter_ids for wiki, filter_ids in pairs if wiki == self.wiki_name]
            self.ignored_filters = filters[0].split()
        except (IndexError, ValueError):
            self.ignored_filters = []

        pairs = [item.split(':', 1) for item in self.config.get(self.config_section, 'formats').strip().split('\n')]
        self.irc_format = [irc_format.strip() for wiki, irc_format in pairs if wiki == self.wiki_name]
        if not self.irc_format:
            self.irc_format = [irc_format.strip() for wiki, irc_format in pairs if wiki == 'default']
        self.irc_format = self.irc_format[0]

    def login(self, callback):
        self.wiki.login(self.username, self.password)
        callback(self)

    def start(self):
        # Just to get the latest item ID
        self.fetch_log(ignore_callback=True)
        if self.log:
            self.log.debug('Reader initialized with log entry ID #%d', self.last_log_id)
        self.loop.start(5)

if __name__ == '__main__':
    argparser = argparse.ArgumentParser()
    argparser.add_argument('-v', '--version', action='version', version='pyAbuseLoggerBot %s' % __version__)
    argparser.add_argument('-l', '--log-level', default='info', choices=['debug', 'info', 'warning', 'error', 'critical'], help="only show log messages equal or above this level.  Default is `info`", metavar='LEVEL')
    argparser.add_argument('-c', '--config', default='bots.conf', help='configuration file name', metavar='FILE')
    args = argparser.parse_args()
    args.log_level = args.log_level.upper()

    if sys.stdout.isatty():
        log_format = '%(asctime)s \x1b[33m%(levelname)-8s\x1b[0m \x1b[32m%(name)-16s\x1b[0m \x1b[34m%(filename)s:%(lineno)s\x1b[0m %(message)s'
    else:
        log_format = '%(asctime)s %(levelname)-8s %(name)-16s %(filename)s:%(lineno)s %(message)s'
    logging.basicConfig(format=log_format, datefmt='%Y-%m-%d %H:%M:%S %Z', level=getattr(logging, args.log_level))
    log = logging.getLogger(__name__)

    config = ReloadableConfigParser(defaults={'__version__': __version__})
    try:
        if not config.read(args.config):
            log.critical('Unable to read configuration file.  Please check its name and permissions.')
            sys.exit(1)
    except ParsingError as e:
        log.critical('Unable to read configuration file.  %s' % e.args)
        sys.exit(1)
    else:
        del sys

    for bot in config.sections():
        if config.getboolean(bot, 'start'):
            if config.getboolean(bot, 'slave'):
                if not config.has_option(bot, 'master') or not len(config.get(bot, 'master')):
                    log.info('%s: no master configured for this slave, skipping', bot)
                    continue
                else:
                    master = config.get(bot, 'master')
                    if not config.has_option(master, 'wikis_channels') or not len(config.get(master, 'wikis_channels').strip()):
                        log.info('%s: the master for this slave (%s) has no wikis-channels dictionary configured, skipping this slave', bot, master)
                        continue
            else:
                if not config.has_option(bot, 'wikis_channels') or not len(config.get(bot, 'wikis_channels').strip()):
                    log.info('%s: no wikis-channels dictionary configured for this master, skipping', bot)
                    continue

            # Ok, we should be safe now...
            log.info('Starting %s', bot)
            factory = ConfigurableBotFactory.forProtocol(AbuseLoggerBot, config, bot, log_level=args.log_level)
            if config.getboolean(bot, 'ssl'):
                reactor.connectSSL(config.get(bot, 'host'), config.getint(bot, 'port'), factory, ssl.ClientContextFactory())
            else:
                reactor.connectTCP(config.get(bot, 'host'), config.getint(bot, 'port'), factory)

    reactor.run()
