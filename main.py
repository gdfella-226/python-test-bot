from json import load
from os.path import join
from sys import exit
from loguru import logger
from tools.bot_core import Bot


if __name__ == '__main__':
    test_ext_data = dict()
    with open(join('./', 'config.json'), 'r') as conf_file:
        test_ext_data = load(conf_file)
    
    if test_ext_data:
        bot = Bot(test_ext_data)
        bot.run()
    else:
        logger.error("Couldn't load config")
        exit(-1)
        
