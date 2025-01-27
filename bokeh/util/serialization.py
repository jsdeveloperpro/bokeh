#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2022, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------
'''
Functions for helping with serialization and deserialization of
Bokeh objects.

Certain NumPy array dtypes can be serialized to a binary format for
performance and efficiency. The list of supported dtypes is:

{binary_array_types}

'''

#-----------------------------------------------------------------------------
# Boilerplate
#-----------------------------------------------------------------------------
from __future__ import annotations

import logging # isort:skip
log = logging.getLogger(__name__)

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

# Standard library imports
import base64
import datetime as dt
import sys
import uuid
from functools import lru_cache
from math import isinf, isnan
from threading import Lock
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Sequence,
    Set,
    Tuple,
    TypedDict,
    Union,
    cast,
)

# External imports
import numpy as np
from typing_extensions import TypeGuard

if TYPE_CHECKING:
    import numpy.typing as npt
    import pandas as pd

# Bokeh imports
from ..core.types import ID
from ..settings import settings
from .dependencies import import_optional
from .string import format_docstring

if TYPE_CHECKING:
    from ..models.sources import DataDict
    from ..protocol.message import BufferRef

#-----------------------------------------------------------------------------
# Globals and constants
#-----------------------------------------------------------------------------

@lru_cache(None)
def _compute_datetime_types() -> Set[type]:
    result = {dt.time, dt.datetime, np.datetime64}
    pd = import_optional('pandas')
    if pd:
        result.add(pd.Timestamp)
        result.add(pd.Timedelta)
        result.add(pd.Period)
        result.add(type(pd.NaT))
    return result

def __getattr__(name: str) -> Any:
    if name == "DATETIME_TYPES":
        return _compute_datetime_types()
    raise AttributeError

BINARY_ARRAY_TYPES = {
    np.dtype(np.float32),
    np.dtype(np.float64),
    np.dtype(np.uint8),
    np.dtype(np.int8),
    np.dtype(np.uint16),
    np.dtype(np.int16),
    np.dtype(np.uint32),
    np.dtype(np.int32),
}

NP_EPOCH = np.datetime64(0, 'ms')
NP_MS_DELTA = np.timedelta64(1, 'ms')

DT_EPOCH = dt.datetime.utcfromtimestamp(0)

__doc__ = format_docstring(__doc__, binary_array_types="\n".join(f"* ``np.{x}``" for x in BINARY_ARRAY_TYPES))

__all__ = (
    'array_encoding_disabled',
    'convert_date_to_datetime',
    'convert_datetime_array',
    'convert_datetime_type',
    'convert_timedelta_type',
    'decode_base64_dict',
    'encode_binary_dict',
    'encode_base64_dict',
    'is_datetime_type',
    'is_timedelta_type',
    'make_globally_unique_id',
    'make_id',
    'serialize_array',
    'transform_array',
    'transform_array_to_list',
    'transform_column_source_data',
    'traverse_data',
    'transform_series',
)

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

ByteOrder = Literal["little", "big"]

class BufferJson(TypedDict):
    __buffer__: ID
    shape: Tuple[int, ...]
    dtype: str
    order: ByteOrder

class Base64BufferJson(TypedDict):
    __ndarray__: str
    shape: Tuple[int, ...]
    dtype: str
    order: ByteOrder

SerializedColumn = Union[Base64BufferJson, BufferJson, Sequence[Any]] # mypy pukes with | and TypedDict
SerializedData = Dict[str, SerializedColumn]

if TYPE_CHECKING:
    Buffers = List[BufferRef]

def is_datetime_type(obj: Any) -> TypeGuard[dt.time | dt.datetime | np.datetime64]:
    ''' Whether an object is any date, time, or datetime type recognized by
    Bokeh.

    Arg:
        obj (object) : the object to test

    Returns:
        bool : True if ``obj`` is a datetime type

    '''
    _dt_tuple = tuple(_compute_datetime_types())

    return isinstance(obj, _dt_tuple)

def is_timedelta_type(obj: Any) -> TypeGuard[dt.timedelta | np.timedelta64]:
    ''' Whether an object is any timedelta type recognized by Bokeh.

    Arg:
        obj (object) : the object to test

    Returns:
        bool : True if ``obj`` is a timedelta type

    '''
    return isinstance(obj, (dt.timedelta, np.timedelta64))

def convert_date_to_datetime(obj: dt.date) -> float:
    ''' Convert a date object to a datetime

    Args:
        obj (date) : the object to convert

    Returns:
        datetime

    '''
    return (dt.datetime(*obj.timetuple()[:6], tzinfo=None) - DT_EPOCH).total_seconds() * 1000

def convert_timedelta_type(obj: dt.timedelta | np.timedelta64) -> float:
    ''' Convert any recognized timedelta value to floating point absolute
    milliseconds.

    Arg:
        obj (object) : the object to convert

    Returns:
        float : milliseconds

    '''
    if isinstance(obj, dt.timedelta):
        return obj.total_seconds() * 1000.
    elif isinstance(obj, np.timedelta64):
        return float(obj / NP_MS_DELTA)

    raise ValueError(f"unknonw timedelta object: {obj!r}")

# The Any here should be pd.NaT | pd.Period but mypy chokes on that for some reason
def convert_datetime_type(obj: Any | pd.Timestamp | pd.Timedelta | dt.datetime | dt.date | dt.time | np.datetime64) -> float:
    ''' Convert any recognized date, time, or datetime value to floating point
    milliseconds since epoch.

    Arg:
        obj (object) : the object to convert

    Returns:
        float : milliseconds

    '''
    pd = import_optional('pandas')

    # Pandas NaT
    if pd and obj is pd.NaT:
        return np.nan

    # Pandas Period
    if pd and isinstance(obj, pd.Period):
        return obj.to_timestamp().value / 10**6.0

    # Pandas Timestamp
    if pd and isinstance(obj, pd.Timestamp):
        return obj.value / 10**6.0

    # Pandas Timedelta
    elif pd and isinstance(obj, pd.Timedelta):
        return obj.value / 10**6.0

    # Datetime (datetime is a subclass of date)
    elif isinstance(obj, dt.datetime):
        diff = obj.replace(tzinfo=None) - DT_EPOCH
        return diff.total_seconds() * 1000

    # XXX (bev) ideally this would not be here "dates are not datetimes"
    # Date
    elif isinstance(obj, dt.date):
        return convert_date_to_datetime(obj)

    # NumPy datetime64
    elif isinstance(obj, np.datetime64):
        epoch_delta = obj - NP_EPOCH
        return float(epoch_delta / NP_MS_DELTA)

    # Time
    elif isinstance(obj, dt.time):
        return (obj.hour * 3600 + obj.minute * 60 + obj.second) * 1000 + obj.microsecond / 1000.

    raise ValueError(f"unknown datetime object: {obj!r}")


def convert_datetime_array(array: npt.NDArray[Any]) -> npt.NDArray[np.floating[Any]]:
    ''' Convert NumPy datetime arrays to arrays to milliseconds since epoch.

    Args:
        array : (obj)
            A NumPy array of datetime to convert

            If the value passed in is not a NumPy array, it will be returned as-is.

    Returns:
        array

    '''

    if not isinstance(array, np.ndarray):
        return array

    # not quite correct, truncates to ms..
    if array.dtype.kind == 'M':
        return array.astype('datetime64[us]').astype('int64') / 1000.0

    elif array.dtype.kind == 'm':
        return array.astype('timedelta64[us]').astype('int64') / 1000.0

    # XXX (bev) special case dates, not great
    elif array.dtype.kind == 'O' and len(array) > 0 and isinstance(array[0], dt.date):
        try:
            return array.astype('datetime64[us]').astype('int64') / 1000.0
        except Exception:
            pass

    return array

def make_id() -> ID:
    ''' Return a new unique ID for a Bokeh object.

    Normally this function will return simple monotonically increasing integer
    IDs (as strings) for identifying Bokeh objects within a Document. However,
    if it is desirable to have globally unique for every object, this behavior
    can be overridden by setting the environment variable ``BOKEH_SIMPLE_IDS=no``.

    Returns:
        str

    '''
    global _simple_id

    if settings.simple_ids():
        with _simple_id_lock:
            _simple_id += 1
            return ID(str(_simple_id))
    else:
        return make_globally_unique_id()

def make_globally_unique_id() -> ID:
    ''' Return a globally unique UUID.

    Some situations, e.g. id'ing dynamically created Divs in HTML documents,
    always require globally unique IDs.

    Returns:
        str

    '''
    return ID(str(uuid.uuid4()))

def array_encoding_disabled(array: npt.NDArray[Any]) -> bool:
    ''' Determine whether an array may be binary encoded.

    The NumPy array dtypes that can be encoded are:

    {binary_array_types}

    Args:
        array (np.ndarray) : the array to check

    Returns:
        bool

    '''

    # disable binary encoding for non-supported dtypes
    return array.dtype not in BINARY_ARRAY_TYPES

array_encoding_disabled.__doc__ = format_docstring(
    array_encoding_disabled.__doc__,
    binary_array_types="\n    ".join(f"* ``np.{x}``" for x in BINARY_ARRAY_TYPES),
)

def transform_array(array: npt.NDArray[Any], force_list: bool = False, buffers: Buffers | None = None) -> Base64BufferJson | BufferJson | Sequence[Any]:
    ''' Transform a NumPy arrays into serialized format

    Converts un-serializable dtypes and returns JSON serializable
    format

    Args:
        array (np.ndarray) : a NumPy array to be transformed
        force_list (bool, optional) : whether to only output to standard lists
            This function can encode some dtypes using a binary encoding, but
            setting this argument to True will override that and cause only
            standard Python lists to be emitted. (default: False)

        buffers (set, optional) :
            If binary buffers are desired, the buffers parameter may be
            provided, and any columns that may be sent as binary buffers
            will be added to the set. If None, then only base64 encoding
            will be used (default: None)

            If force_list is True, then this value will be ignored, and
            no buffers will be generated.

            **This is an "out" parameter**. The values it contains will be
            modified in-place.


    Returns:
        JSON

    '''

    array = convert_datetime_array(array)

    return serialize_array(array, force_list=force_list, buffers=buffers)

def transform_array_to_list(array: npt.NDArray[Any]) -> Sequence[Any]:
    ''' Transforms a NumPy array into a list of values

    Args:
        array (np.nadarray) : the NumPy array series to transform

    Returns:
        list or dict

    '''
    pd = import_optional('pandas')

    if (array.dtype.kind in ('u', 'i', 'f') and (~np.isfinite(array)).any()):
        transformed = array.astype('object')
        transformed[np.isnan(array)] = 'NaN'
        transformed[np.isposinf(array)] = 'Infinity'
        transformed[np.isneginf(array)] = '-Infinity'
        return transformed.tolist()
    elif (array.dtype.kind == 'O' and pd and pd.isnull(array).any()):
        transformed = array.astype('object')
        transformed[pd.isnull(array)] = 'NaN'
        return transformed.tolist()
    return array.tolist()

def transform_series(series: pd.Series | pd.Index, force_list: bool = False, buffers: Buffers | None = None) -> Base64BufferJson | BufferJson | Sequence[Any]:
    ''' Transforms a Pandas series into serialized form

    Args:
        series (pd.Series) : the Pandas series to transform
        force_list (bool, optional) : whether to only output to standard lists
            This function can encode some dtypes using a binary encoding, but
            setting this argument to True will override that and cause only
            standard Python lists to be emitted. (default: False)

        buffers (set, optional) :
            If binary buffers are desired, the buffers parameter may be
            provided, and any columns that may be sent as binary buffers
            will be added to the set. If None, then only base64 encoding
            will be used (default: None)

            If force_list is True, then this value will be ignored, and
            no buffers will be generated.

            **This is an "out" parameter**. The values it contains will be
            modified in-place.

    Returns:
        list or dict

    '''
    pd = import_optional('pandas')

    # not checking for pd here, this function should only be called if it
    # is already known that series is a Pandas Series type
    if isinstance(series, pd.PeriodIndex):
        vals = series.to_timestamp().values  # type: ignore # pandas PeriodIndex type is misunderstood somehow
    else:
        vals = series.values
    return transform_array(vals, force_list=force_list, buffers=buffers)

def serialize_array(array: npt.NDArray[Any], force_list: bool = False, buffers: Buffers | None = None) -> Base64BufferJson | BufferJson | Sequence[Any]:
    ''' Transforms a NumPy array into serialized form.

    Args:
        array (np.ndarray) : the NumPy array to transform
        force_list (bool, optional) : whether to only output to standard lists
            This function can encode some dtypes using a binary encoding, but
            setting this argument to True will override that and cause only
            standard Python lists to be emitted. (default: False)

        buffers (set, optional) :
            If binary buffers are desired, the buffers parameter may be
            provided, and any columns that may be sent as binary buffers
            will be added to the set. If None, then only base64 encoding
            will be used (default: None)

            If force_list is True, then this value will be ignored, and
            no buffers will be generated.

            **This is an "out" parameter**. The values it contains will be
            modified in-place.

    Returns:
        list or dict

    '''
    if isinstance(array, np.ma.MaskedArray):
        # Set masked values to nan
        array = array.filled(np.nan)  # type: ignore # filled is untyped
    if (array_encoding_disabled(array) or force_list):
        return transform_array_to_list(array)
    if not array.flags['C_CONTIGUOUS']:
        array = np.ascontiguousarray(array)
    if buffers is None:
        return encode_base64_dict(array)
    else:
        return encode_binary_dict(array, buffers)

def traverse_data(obj: Sequence[Any], buffers: Buffers | None = None) -> List[Any]:
    ''' Recursively traverse an object until a flat list is found.

    The flat list is converted to a numpy array and passed to transform_array()
    to handle ``nan``, ``inf``, and ``-inf``.

    Args:
        obj (list) : a list of values or lists

    '''
    if all(isinstance(el, np.ndarray) for el in obj):
        return [transform_array(el, buffers=buffers) for el in obj]
    obj_copy: List[Any] = []
    for item in obj:
        # Check the base/common case first for performance reasons
        # Also use type(x) is float because it's faster than isinstance
        if type(item) is float:
            if isnan(item):
                item = 'NaN'
            elif isinf(item):
                if item > 0:
                    item = 'Infinity'
                else:
                    item = '-Infinity'
            obj_copy.append(item)
        elif isinstance(item, (list, tuple)):  # check less common type second
            obj_copy.append(traverse_data(item))
        else:
            obj_copy.append(item)
    return obj_copy

def transform_column_source_data(data: DataDict, buffers: Buffers | None = None, cols: List[str] | None = None) -> SerializedData:
    ''' Transform ``ColumnSourceData`` data to a serialized format

    Args:
        data (dict) : the mapping of names to data columns to transform

        buffers (set, optional) :
            If binary buffers are desired, the buffers parameter may be
            provided, and any columns that may be sent as binary buffers
            will be added to the set. If None, then only base64 encoding
            will be used (default: None)

            **This is an "out" parameter**. The values it contains will be
            modified in-place.

        cols (list[str], optional) :
            Optional list of subset of columns to transform. If None, all
            columns will be transformed (default: None)

    Returns:
        JSON compatible dict

    '''
    pd = import_optional('pandas')

    to_transform = set(data) if cols is None else set(cols)

    data_copy: SerializedData = {}
    for key in to_transform:
        value = data[key]
        if pd and isinstance(value, (pd.Series, pd.Index)):
            data_copy[key] = transform_series(value, buffers=buffers)
        elif isinstance(value, np.ndarray):
            data_copy[key] = transform_array(value, buffers=buffers)
        elif isinstance(value, (list, tuple)):
            data_copy[key] = traverse_data(value, buffers=buffers)
        else:
            raise ValueError(f"Unable to transform type {type(value)!r} for a ColumnDataSource")

    return data_copy

def encode_binary_dict(array: npt.NDArray[Any], buffers: Buffers) -> BufferJson:
    ''' Send a numpy array as an unencoded binary buffer

    The encoded format is a dict with the following structure:

    .. code:: python

        {
            '__buffer__' :  << an ID to locate the buffer >>,
            'shape'      : << array shape >>,
            'dtype'      : << dtype name >>,
            'order'      : << byte order at origin (little or big)>>
        }

    Args:
        array (np.ndarray) : an array to encode

        buffers (set) :
            Set to add buffers to

            **This is an "out" parameter**. The values it contains will be
            modified in-place.

    Returns:
        dict

    '''
    from ..protocol.message import BufferHeader
    buffer_id = make_id()
    buf = (BufferHeader(id=buffer_id), array.tobytes())
    buffers.append(buf)

    return BufferJson(
        __buffer__  = buffer_id,
        shape       = array.shape,
        dtype       = str(array.dtype.name),
        order       = cast(ByteOrder, sys.byteorder),
    )

def encode_base64_dict(array: npt.NDArray[Any]) -> Base64BufferJson:
    ''' Encode a NumPy array using base64:

    The encoded format is a dict with the following structure:

    .. code:: python

        {
            '__ndarray__' : << base64 encoded array data >>,
            'shape'       : << array shape >>,
            'dtype'       : << dtype name >>,
        }

    Args:

        array (np.ndarray) : an array to encode

    Returns:
        dict

    '''
    return Base64BufferJson(
        __ndarray__ = base64.b64encode(array.data).decode('utf-8'),
        shape       = array.shape,
        dtype       = str(array.dtype.name),
        order       = cast(ByteOrder, sys.byteorder),
    )

def decode_base64_dict(data: Base64BufferJson) -> npt.NDArray[Any]:
    ''' Decode a base64 encoded array into a NumPy array.

    Args:
        data (dict) : encoded array data to decode

    Data should have the format encoded by :func:`encode_base64_dict`.

    Returns:
        np.ndarray

    '''
    b64 = base64.b64decode(data['__ndarray__'])
    array = np.copy(np.frombuffer(b64, dtype=data['dtype']))  # type: ignore # from and frombuffer are untyped
    if len(data['shape']) > 1:
        array = array.reshape(data['shape'])
    return array

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

_simple_id = 999
_simple_id_lock = Lock()

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------
