import logging
import sys

from twisted.internet import reactor, defer
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.words.protocols.irc import IRCClient

class ConfigurableBotFactory(ReconnectingClientFactory):
    maxDelay = 60

    bots = []

    def __init__(self, config, config_section, log_level=logging.INFO):
        self.config = config
        self.config_section = config_section
        reactor.addSystemEventTrigger('before', 'shutdown', self.__shutdown)

        if sys.stdout.isatty():
            log_format = '%(asctime)s \x1b[33m%(levelname)-8s\x1b[0m \x1b[32m%(name)-16s\x1b[0m \x1b[34m%(filename)s:%(lineno)s\x1b[0m %(message)s'
        else:
            log_format = '%(asctime)s %(levelname)-8s %(name)-16s %(filename)s:%(lineno)s %(message)s'
        # This doesn't actually do anything if logging is already configured elsewhere (e.g. you start logging before starting your bot(s))
        logging.basicConfig(format=log_format, datefmt='%Y-%m-%d %H:%M:%S %Z', level=log_level)
        self.log = logging.getLogger(self.config_section)

    def buildProtocol(self, addr): # noqa
        self.resetDelay()
        return ReconnectingClientFactory.buildProtocol(self, addr)

    def clientConnectionFailed(self, connector, reason): # noqa
        self.log.error('Connection failed: %s  Retrying in %d second%s', reason.value.args[0] if reason.value.args and len(reason.value.args[0]) else reason.value, self.delay, 's' if int(self.delay) > 1 else '')
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

    def __shutdown(self):
        if self.continueTrying:
            self.stopTrying()

class ConfigurableBot(IRCClient):
    # Seems a sane default for a bot (1 message every lineRate seconds)
    lineRate = 2

    __shutdown_callID = None

    def connectionLost(self, reason): # noqa
        log_message = 'Disconnected' if self.__shutdown_callID else 'Connection lost, trying to reconnect...'
        self.log.info(log_message)
        self.factory.bots.remove(self)
        IRCClient.connectionLost(self, reason)
        if self.__shutdown_callID and self.__shutdown_callID.active():
            self.__shutdown_callID.reset(0)

    def connectionMade(self): # noqa
        reactor.addSystemEventTrigger('before', 'shutdown', self.__shutdown)
        self.nickname = self.factory.config_section
        self.realname = self.factory.config.get(self.factory.config_section, 'real_name')
        self.factory.bots.append(self)
        self.log = self.factory.log
        self.log.info('Connected')
        IRCClient.connectionMade(self)

    def __shutdown(self):
        self.quit('Killed from console')
        d = defer.Deferred()
        self.__shutdown_callID = reactor.callLater(self.lineRate * 2, d.callback, 1)
        return d
