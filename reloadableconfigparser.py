import sys

if sys.version_info < (3,):
    from ConfigParser import ParsingError, SafeConfigParser
elif sys.version_info < (3, 2):
    from configparser import ParsingError, SafeConfigParser
else:
    from configparser import ParsingError, ConfigParser as SafeConfigParser

del sys

class ReloadableConfigParser(SafeConfigParser):
    __filenames = None

    def read(self, filenames):
        self.__filenames = filenames
        return SafeConfigParser.read(self, filenames)

    def reload(self):
        if self.__filenames:
            return self.read(self.__filenames)
