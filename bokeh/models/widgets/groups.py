#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2022, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------
'''

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

# Bokeh imports
from ...core.has_props import abstract
from ...core.properties import (
    Bool,
    Enum,
    Int,
    List,
    Nullable,
    String,
)
from .buttons import ButtonLike
from .widget import Widget

#-----------------------------------------------------------------------------
# Globals and constants
#-----------------------------------------------------------------------------

__all__ = (
    'AbstractGroup',
    'ButtonGroup',
    'CheckboxButtonGroup',
    'CheckboxGroup',
    'Group',
    'RadioButtonGroup',
    'RadioGroup',
)

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

@abstract
class AbstractGroup(Widget):
    ''' Abstract base class for all kinds of groups.

    '''

    labels = List(String, help="""
    List of text labels contained in this group.
    """)

@abstract
class ButtonGroup(AbstractGroup, ButtonLike):
    ''' Abstract base class for groups with items rendered as buttons.

    '''

    orientation = Enum("horizontal", "vertical", help="""
    Orient the button group either horizontally (default) or vertically.
    """)

@abstract
class Group(AbstractGroup):
    ''' Abstract base class for groups with items rendered as check/radio
    boxes.

    '''

    inline = Bool(False, help="""
    Should items be arrange vertically (``False``) or horizontally
    in-line (``True``).
    """)

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

class CheckboxGroup(Group):
    ''' A group of check boxes.

    '''

    active = List(Int, help="""
    The list of indices of selected check boxes.
    """)

class RadioGroup(Group):
    ''' A group of radio boxes.

    '''

    active = Nullable(Int, help="""
    The index of the selected radio box, or ``None`` if nothing is selected.
    """)

class CheckboxButtonGroup(ButtonGroup):
    ''' A group of check boxes rendered as toggle buttons.

    '''

    active = List(Int, help="""
    The list of indices of selected check boxes.
    """)

class RadioButtonGroup(ButtonGroup):
    ''' A group of radio boxes rendered as toggle buttons.

    '''

    active = Nullable(Int, help="""
    The index of the selected radio box, or ``None`` if nothing is
    selected.
    """)

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------
