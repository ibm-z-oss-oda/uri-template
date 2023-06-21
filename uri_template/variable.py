"""Variable class for URITemplate."""

from __future__ import annotations

from typing import TYPE_CHECKING

if (TYPE_CHECKING):
    from .charset import Charset


class VariableInvalidError(Exception):
    """Exception thrown for invalid variables."""

    variable: str

    def __init__(self, variable: str) -> None:
        self.variable = variable

    def __str__(self) -> str:
        """Convert to string."""
        return 'Bad variable: ' + self.variable


class Variable:
    """
    A template variable.

    https://tools.ietf.org/html/rfc6570#section-2.3
    """

    __slots__ = ('name', 'key', 'max_length', 'explode', 'array', 'default')

    name: str
    key: str
    max_length: int
    explode: bool
    array: bool
    default: (str | None)

    def __init__(self, var_spec: str, charset: type[Charset]) -> None:
        self.name = ''
        """Variable name."""
        self.key = ''
        """Key used to get value."""
        self.max_length = 0
        """Max length in expansions, 0 for unlimited."""
        self.explode = False
        """Explode values."""
        self.array = False
        """Array values."""
        self.default = None
        """Default value."""

        if (var_spec[0:1] not in charset.VAR_START):
            raise VariableInvalidError(var_spec)

        if ('=' in var_spec):
            var_spec, self.default = var_spec.split('=', 1)

        if (':' in var_spec):
            var_spec, max_length = var_spec.split(':', 1)
            if ((0 < len(max_length)) and (len(max_length) < 4)):
                for digit in max_length:
                    if (digit not in charset.DIGIT):
                        raise VariableInvalidError(var_spec + ':' + max_length)
                self.max_length = int(max_length)
                if (not self.max_length):
                    raise VariableInvalidError(var_spec + ':' + max_length)
            else:
                raise VariableInvalidError(var_spec + ':' + max_length)
        elif ('*' == var_spec[-1]):
            var_spec = var_spec[:-1]
            self.explode = True
        elif ('[]' == var_spec[-2:]):
            var_spec = var_spec[:-2]
            self.array = True
            self.explode = True

        index = 0
        while (index < len(var_spec)):
            codepoint = var_spec[index]
            if (('%' == codepoint)
                    and ((index + 2) < len(var_spec))
                    and (var_spec[index + 1] in charset.HEX_DIGIT)
                    and (var_spec[index + 2] in charset.HEX_DIGIT)):
                self.key += var_spec[index:index + 3]
                index += 2
            elif (codepoint in charset.VAR_CHAR):
                self.key += codepoint
            elif ('/' == codepoint):
                self.name = self.key
                self.key = ''
            else:
                raise VariableInvalidError(var_spec + ((':' + str(self.max_length)) if (self.max_length) else '')
                                           + ('[]' if (self.array) else ('*' if (self.explode) else '')))
            index += 1

        self.name = (self.name or self.key)
        self.key = (self.key or self.name)

    def __str__(self) -> str:
        """Convert to string."""
        return (self.name + (f'/{self.key}' if (self.key and (self.key != self.name)) else '')
                + (f':{self.max_length}' if (self.max_length) else '')
                + ('*' if (self.explode and not self.array) else '') + ('[]' if (self.array) else '')
                + (f'={self.default}' if (self.default is not None) else ''))
