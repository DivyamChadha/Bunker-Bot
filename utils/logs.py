import logging

from typing import Optional


__all__ = (
    'create_logger',
    'create_handler',
)


def create_logger(name: str, *, level=logging.WARNING) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


def create_handler(name, *, format: Optional[str] = None, datefmt: Optional[str] = None) -> logging.Handler:
    handler = logging.FileHandler(filename=f'logs/{name}.log', encoding='utf-8')
    formatter = logging.Formatter(format or '%(asctime)s:%(levelname)s:%(name)s: %(message)s', datefmt or '‘%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    return handler
