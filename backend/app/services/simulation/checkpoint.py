"""Versioned JSON runtime snapshots. No pickle or executable deserialisation."""
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime

import numpy as np


def encode(value):
    if isinstance(value, np.ndarray):
        return {'$': 'array', 'dtype': str(value.dtype), 'v': value.tolist()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.random.Generator):
        return {'$': 'rng', 'v': value.bit_generator.state}
    if isinstance(value, datetime):
        return {'$': 'datetime', 'v': value.isoformat()}
    if is_dataclass(value):
        return {'$': type(value).__name__, 'v': encode(asdict(value))}
    if isinstance(value, (dict, Counter)):
        return {'$': 'counter' if isinstance(value, Counter) else 'dict', 'v': [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (set, tuple, list)):
        return {'$': 'set' if isinstance(value, set) else 'tuple' if isinstance(value, tuple) else 'list', 'v': [encode(v) for v in value]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'Unsupported checkpoint type: {type(value).__name__}')


def decode(value):
    if not isinstance(value, dict) or '$' not in value:
        return value
    kind, data = value['$'], value['v']
    if kind == 'array':
        return np.asarray(data, dtype=value['dtype'])
    if kind == 'rng':
        rng = np.random.default_rng()
        rng.bit_generator.state = data
        return rng
    if kind == 'datetime':
        return datetime.fromisoformat(data)
    if kind in ('dict', 'counter'):
        result = {decode(k): decode(v) for k, v in data}
        return Counter(result) if kind == 'counter' else result
    if kind in ('set', 'tuple', 'list'):
        result = [decode(v) for v in data]
        return set(result) if kind == 'set' else tuple(result) if kind == 'tuple' else result
    from .engine import AgentRT, PostRT
    from .projection import Surface
    classes = {'AgentRT': AgentRT, 'PostRT': PostRT, 'Surface': Surface}
    if kind in classes:
        fields = decode(data)
        if kind == 'Surface':
            for field in ('mu', 'sd', 'W', 'b', 'sigma', 'lo', 'hi'):
                fields[field] = np.asarray(fields[field])
        return classes[kind](**fields)
    raise ValueError('Unknown checkpoint version/type')


def snapshot(engine):
    skip = {'llm', 'usage', 'pop', 'writer', 'cfg', 'card', 'card_b', 'snaps', 'world_block'}
    return {'version': 1, 'state': encode({k: v for k, v in vars(engine).items() if k not in skip}),
            'writer': encode(vars(engine.writer))}


def restore(engine, saved):
    if saved.get('version') != 1:
        raise ValueError('Unsupported simulation checkpoint version')
    vars(engine).update(decode(saved['state']))
    vars(engine.writer).update(decode(saved['writer']))
