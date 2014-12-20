# pyAbuseLoggerBot

> **tl;dr** An IRC bot that forwards the Wikipedia (or other MediaWiki installation) [abuse filter](https://www.mediawiki.org/wiki/Extension:AbuseFilter "AbuseFilter extension")'s log to one or more channels.

It's actually a bit more _technologic_.
It can read multiple wikis, which can be associated with one or more IRC channel.

Furthermore, you can have a master bot (more than one) with its slave (currently, only one).

## Requirements

* Python 2.7;
* [Twisted](https://twistedmatrix.com/trac/ "Twisted") – tested on Twisted 13.0.0.

Please note that – sadly – it currently doesn't work on Python 3.

## Configuration

`bots.conf.default` contains an example configuration for a master-slave scenario, configured with 2 wikis and their respective formats (actually, one has a configured format, the other'll use the _default_ format).

Let's say you want to read the abuselog for l33t.wiktionary.org and output it to #ch4nn31, and klingon.wikipedia.org's one to #worf and #highcouncil.

You also want a slave bot, just in case your master one explodes.

Copy it to `bots.conf`, adjust your settings (IRC server, nick, wikis and channels, format, ...).  Don't forget to set `start: no` in your slave's section.

Start your master bot with `python bot.py`.  You may want to use [Screen](https://www.gnu.org/software/screen/ "GNU Screen") or [tmux](http://tmux.sourceforge.net/ "tmux").  Also, check `python bot.py -h` for other options.

Copy your configuration file to the slave's machine and add `start: no` to the master's section, then remove `start: no` (or comment it out) from slave's section.  Launch it.  If you didn't touch `autofailover: yes`, your slave should start speaking automatically if your master quits for any reason.

## Available commands

You can control your bots over IRC: start or stop the slave bot and reload the current configuration.

All commands should be prepended with the bot's nickname.  In the following examples `bot` is to be replaced with the actual nickname.

* `bot: start` lets a slave bot start speaking;
* `bot, stop` kindly invites a slave bot to shut up;
* `bot rehash` re-reads the configuration file.  Does only reload wikis' configuration, as explained below.

`rehash` should be used – instead of restarting everything – if you ever add or remove a wiki, add or remove one or more channels.  You need to repeat this for every bot that resides on different machines (only one, other bots on the same machine get reloaded automatically).  Don't forget to synchronize your configuration file on all your machines.
