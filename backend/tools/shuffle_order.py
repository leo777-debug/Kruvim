"""Seeded test ordering, for repeatable shared-state audits without extra dependencies."""
import random


def pytest_addoption(parser):
    parser.addoption("--shuffle-seed", type=int, default=None)


def pytest_collection_modifyitems(config, items):
    seed = config.getoption("--shuffle-seed")
    if seed is not None:
        random.Random(seed).shuffle(items)
