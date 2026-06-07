"""Wiki lifecycle, path/slug/templates, and schema reading mixins.

These three mixins handle Wiki class lifecycle, utility helpers,
and schema/template generation. They are imported and applied
to the ``Wiki`` class via ``WikiMeta`` (the metaclass that
composes all ``WikiMixin*`` classes).
"""
from .init import WikiInitMixin
from .schema import WikiSchemaMixin
from .utility import WikiUtilityMixin

__all__ = [
    "WikiInitMixin",
    "WikiSchemaMixin",
    "WikiUtilityMixin",
]
