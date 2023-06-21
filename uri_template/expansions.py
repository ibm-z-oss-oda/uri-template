"""Process URI templates per http://tools.ietf.org/html/rfc6570."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, ClassVar, TYPE_CHECKING, cast

from .variable import Variable

if (TYPE_CHECKING):
    from .charset import Charset


class ExpansionFailedError(Exception):
    """Exception thrown when expansions fail."""

    variable: str

    def __init__(self, variable: str) -> None:
        self.variable = variable

    def __str__(self) -> str:
        """Convert to string."""
        return 'Bad expansion: ' + self.variable


class Expansion:
    """
    Base class for template expansions.

    https://tools.ietf.org/html/rfc6570#section-3
    """

    __slots__ = ('_charset', )

    _charset: type[Charset]

    def __init__(self, charset: type[Charset]) -> None:
        self._charset = charset

    @property
    def variables(self) -> Iterable[Variable]:
        """Get all variables in this expansion."""
        return []

    @property
    def variable_names(self) -> Iterable[str]:
        """Get the names of all variables in this expansion."""
        return []

    def _encode(self, value: str, legal: str, pct_encoded: bool) -> str:
        """Encode a string into legal values."""
        output = ''
        index = 0
        while (index < len(value)):
            codepoint = value[index]
            if (codepoint in legal):
                output += codepoint
            elif (pct_encoded and ('%' == codepoint)
                  and ((index + 2) < len(value))
                  and (value[index + 1] in self._charset.HEX_DIGIT)
                  and (value[index + 2] in self._charset.HEX_DIGIT)):
                output += value[index:index + 3]
                index += 2
            else:
                utf8 = codepoint.encode('utf8')
                for byte in utf8:
                    output += '%' + self._charset.HEX_DIGIT[int(byte / 16)] + self._charset.HEX_DIGIT[byte % 16]
            index += 1
        return output

    def _uri_encode_value(self, value: str) -> str:
        """Encode a value into uri encoding."""
        return self._encode(value, self._charset.UNRESERVED, False)

    def _uri_encode_name(self, name: (str | int)) -> str:
        """Encode a variable name into uri encoding."""
        return self._encode(str(name), self._charset.NAME, True) if (name) else ''

    def _join(self, prefix: str, joiner: str, value: str) -> str:
        """Join a prefix to a value."""
        if (prefix):
            return prefix + joiner + value
        return value

    def _encode_str(self, variable: Variable, name: str, value: str, prefix: str, joiner: str, first: bool) -> str:
        """Encode a string value for a variable."""
        if (variable.max_length):
            if (not first):
                raise ExpansionFailedError(str(variable))
            return self._join(prefix, joiner, self._uri_encode_value(value[:variable.max_length]))
        return self._join(prefix, joiner, self._uri_encode_value(value))

    def _encode_dict_item(self, variable: Variable, name: str, key: (str | int), item: Any,
                          delim: str, prefix: str, joiner: str, first: bool) -> (str | None):
        """Encode a dict item for a variable."""
        joiner = '=' if (variable.explode) else ','
        if (variable.array):
            name = self._uri_encode_name(key)
            prefix = (prefix + '[' + name + ']') if (prefix and not first) else name
        else:
            prefix = self._join(prefix, '.', self._uri_encode_name(key))
        return self._encode_var(variable, str(key), item, delim=delim, prefix=prefix, joiner=joiner, first=False)

    def _encode_list_item(self, variable: Variable, name: str, index: int, item: Any,
                          delim: str, prefix: str, joiner: str, first: bool) -> (str | None):
        """Encode a list item for a variable."""
        if (variable.array):
            prefix = prefix + '[' + str(index) + ']' if (prefix) else ''
            return self._encode_var(variable, '', item, delim=delim, prefix=prefix, joiner=joiner, first=False)
        return self._encode_var(variable, name, item, delim=delim, prefix=prefix, joiner='.', first=False)

    def _encode_var(self, variable: Variable, name: str, value: Any,
                    *, delim: str = ',', prefix: str = '', joiner: str = '=', first: bool = True) -> (str | None):
        """Encode a variable."""
        if (isinstance(value, str)):
            return self._encode_str(variable, name, value, prefix, joiner, first)
        elif (isinstance(value, Mapping)):
            if (len(value)):
                encoded_items = [self._encode_dict_item(variable, name, key, value[key], delim, prefix, joiner, first)
                                 for key in value.keys()]
                return delim.join([item for item in encoded_items if (item is not None)])
            return None
        elif (isinstance(value, Sequence)):
            if (len(value)):
                encoded_items = [self._encode_list_item(variable, name, index, item, delim, prefix, joiner, first)
                                 for index, item in enumerate(value)]
                return delim.join([item for item in encoded_items if (item is not None)])
            return None
        elif (isinstance(value, bool)):
            return self._encode_str(variable, name, str(value).lower(), prefix, joiner, first)
        else:
            return self._encode_str(variable, name, str(value), prefix, joiner, first)

    def expand(self, values: Mapping[str, Any]) -> (str | None):
        """Expand values."""
        return None

    def partial(self, values: Mapping[str, Any]) -> str:
        """Perform partial expansion."""
        return ''


class Literal(Expansion):
    """
    A literal expansion.

    https://tools.ietf.org/html/rfc6570#section-3.1
    """

    __slots__ = ('value', )

    value: str

    def __init__(self, value: str, charset: type[Charset]) -> None:
        super().__init__(charset)
        self.value = value

    def expand(self, values: Mapping[str, Any]) -> (str | None):
        """Perform exansion."""
        return self._encode(self.value, (self._charset.UNRESERVED + self._charset.RESERVED), True)

    def __str__(self) -> str:
        """Convert to string."""
        return self.value


class ExpressionExpansion(Expansion):
    """
    Base class for expression expansions.

    https://tools.ietf.org/html/rfc6570#section-3.2
    """

    __slots__ = ('vars', 'trailing_joiner')

    operator: ClassVar[str] = ''
    partial_operator: ClassVar[str] = ','
    output_prefix: ClassVar[str] = ''
    var_joiner: ClassVar[str] = ','
    partial_joiner: ClassVar[str] = ','

    vars: list[Variable]
    trailing_joiner: str

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(charset)
        if (variables and (variables[-1] in (',', '.', '/', ';', '&'))):
            self.trailing_joiner = variables[-1]
            variables = variables[:-1]
        else:
            self.trailing_joiner = ''
        self.vars = [Variable(var, charset) for var in variables.split(',')]

    @property
    def variables(self) -> Iterable[Variable]:
        """Get all variables."""
        return list(self.vars)

    @property
    def variable_names(self) -> Iterable[str]:
        """Get names of all variables."""
        return [var.name for var in self.vars]

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        return self._encode_var(variable, self._uri_encode_name(variable.name), value)

    def expand(self, values: Mapping[str, Any]) -> (str | None):
        """Expand all variables, skip missing values."""
        expanded_vars: list[str] = []
        for var in self.vars:
            value = values.get(var.key, var.default)
            if (value is not None):
                expanded_var = self._expand_var(var, value)
                if (expanded_var is not None):
                    expanded_vars.append(expanded_var)
        if (expanded_vars):
            return ((self.output_prefix if (not self.trailing_joiner) else '') + self.var_joiner.join(expanded_vars)
                    + self.trailing_joiner)
        return None

    def partial(self, values: Mapping[str, Any]) -> str:
        """Expand all variables, replace missing values with expansions."""
        expanded_vars: list[str] = []
        missing_vars: list[Variable] = []
        result: list[tuple[(list[str] | None), (list[Variable] | None)]] = []
        for var in self.vars:
            value = values.get(var.name, var.default)
            if (value is not None):
                expanded_var = self._expand_var(var, value)
                if (expanded_var is not None):
                    if (missing_vars):
                        result.append((None, missing_vars))
                        missing_vars = []
                    expanded_vars.append(expanded_var)
            else:
                if (expanded_vars):
                    result.append((expanded_vars, None))
                    expanded_vars = []
                missing_vars.append(var)
        if (expanded_vars):
            result.append((expanded_vars, None))
        if (missing_vars):
            result.append((None, missing_vars))

        output: str = ''
        first = True
        for index, (expanded, missing) in enumerate(result):
            last = (index == (len(result) - 1))
            if (expanded):
                output += ((self.output_prefix if (first and (not self.trailing_joiner)) else '')
                           + self.var_joiner.join(expanded) + self.trailing_joiner)
            else:
                output += ((self.output_prefix if (first and not last) else (self.var_joiner if (not last) else ''))
                           + '{' + (self.operator if (first) else self.partial_operator)
                           + ','.join([str(var) for var in cast('list[Variable]', missing)])
                           + (self.partial_joiner if (not last) else '') + '}')
            first = False
        return output

    def __str__(self) -> str:
        """Convert to string."""
        return ('{' + self.operator + ','.join([str(var) for var in self.vars]) + self.trailing_joiner + '}')


class SimpleExpansion(ExpressionExpansion):
    """
    Simple String expansion {var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.2

    """

    __slots__ = ()

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables, charset)


class ReservedExpansion(ExpressionExpansion):
    """
    Reserved Expansion {+var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.3
    """

    __slots__ = ()

    operator: ClassVar[str] = '+'
    partial_operator: ClassVar[str] = ',+'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _uri_encode_value(self, value: str) -> str:
        """Encode a value into uri encoding."""
        return self._encode(value, (self._charset.UNRESERVED + self._charset.RESERVED), True)


class FragmentExpansion(ReservedExpansion):
    """
    Fragment Expansion {#var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.4
    """

    __slots__ = ()

    operator: ClassVar[str] = '#'
    output_prefix: ClassVar[str] = '#'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables, charset)


class LabelExpansion(ExpressionExpansion):
    """
    Label Expansion with Dot-Prefix {.var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.5
    """

    __slots__ = ()

    operator: ClassVar[str] = '.'
    partial_operator: ClassVar[str] = '.'
    output_prefix: ClassVar[str] = '.'
    var_joiner: ClassVar[str] = '.'
    partial_joiner: ClassVar[str] = '.'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        return self._encode_var(variable, self._uri_encode_name(variable.name), value,
                                delim=('.' if variable.explode else ','))


class PathExpansion(ExpressionExpansion):
    """
    Path Segment Expansion {/var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.6
    """

    __slots__ = ()

    operator: ClassVar[str] = '/'
    partial_operator: ClassVar[str] = '/'
    output_prefix: ClassVar[str] = '/'
    var_joiner: ClassVar[str] = '/'
    partial_joiner: ClassVar[str] = '/'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        return self._encode_var(variable, self._uri_encode_name(variable.name), value,
                                delim=('/' if variable.explode else ','))


class PathStyleExpansion(ExpressionExpansion):
    """
    Path-Style Parameter Expansion {;var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.7
    """

    __slots__ = ()

    operator: ClassVar[str] = ';'
    partial_operator: ClassVar[str] = ';'
    output_prefix: ClassVar[str] = ';'
    var_joiner: ClassVar[str] = ';'
    partial_joiner: ClassVar[str] = ';'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _encode_str(self, variable: Variable, name: str, value: Any, prefix: str, joiner: str, first: bool) -> str:
        """Encode a string for a variable."""
        if (variable.array):
            if (name):
                prefix = prefix + '[' + name + ']' if (prefix) else name
        elif (variable.explode):
            prefix = self._join(prefix, '.', name)
        return super()._encode_str(variable, name, value, prefix, joiner, first)

    def _encode_dict_item(self, variable: Variable, name: str, key: (str | int), item: Any,
                          delim: str, prefix: str, joiner: str, first: bool) -> (str | None):
        """Encode a dict item for a variable."""
        if (variable.array):
            if (name):
                prefix = prefix + '[' + name + ']' if (prefix) else name
            if (prefix and not first):
                prefix = (prefix + '[' + self._uri_encode_name(key) + ']')
            else:
                prefix = self._uri_encode_name(key)
        elif (variable.explode):
            prefix = self._join(prefix, '.', name) if (not first) else ''
        else:
            prefix = self._join(prefix, '.', self._uri_encode_name(key))
            joiner = ','
        return self._encode_var(variable, self._uri_encode_name(key) if (not variable.array) else '', item,
                                delim=delim, prefix=prefix, joiner=joiner, first=False)

    def _encode_list_item(self, variable: Variable, name: str, index: int, item: Any,
                          delim: str, prefix: str, joiner: str, first: bool) -> (str | None):
        """Encode a list item for a variable."""
        if (variable.array):
            if (name):
                prefix = prefix + '[' + name + ']' if (prefix) else name
            return self._encode_var(variable, str(index), item, delim=delim, prefix=prefix, joiner=joiner, first=False)
        return self._encode_var(variable, name, item, delim=delim, prefix=prefix,
                                joiner=('=' if (variable.explode) else '.'), first=False)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        if (variable.explode):
            return self._encode_var(variable, self._uri_encode_name(variable.name), value, delim=';')
        value = self._encode_var(variable, self._uri_encode_name(variable.name), value, delim=',')
        return (self._uri_encode_name(variable.name) + '=' + value) if (value) else variable.name


class FormStyleQueryExpansion(PathStyleExpansion):
    """
    Form-Style Query Expansion {?var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.8
    """

    __slots__ = ()

    operator: ClassVar[str] = '?'
    partial_operator: ClassVar[str] = '&'
    output_prefix: ClassVar[str] = '?'
    var_joiner: ClassVar[str] = '&'
    partial_joiner: ClassVar[str] = '&'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables, charset)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        if (variable.explode):
            return self._encode_var(variable, self._uri_encode_name(variable.name), value, delim='&')
        value = self._encode_var(variable, self._uri_encode_name(variable.name), value, delim=',')
        return (self._uri_encode_name(variable.name) + '=' + value) if (value is not None) else None


class FormStyleQueryContinuation(FormStyleQueryExpansion):
    """
    Form-Style Query Continuation {&var}.

    https://tools.ietf.org/html/rfc6570#section-3.2.9
    """

    __slots__ = ()

    operator: ClassVar[str] = '&'
    output_prefix: ClassVar[str] = '&'

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables, charset)

# non-standard extension


class CommaExpansion(ExpressionExpansion):
    """
    Label Expansion with Comma-Prefix {,var}.

    Non-standard extension to support partial expansions.
    """

    __slots__ = ()

    operator: ClassVar[str] = ','
    output_prefix: ClassVar[str] = ','

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        return self._encode_var(variable, self._uri_encode_name(variable.name), value,
                                delim=('.' if variable.explode else ','))


class ReservedCommaExpansion(ReservedExpansion):
    """
    Reserved Expansion with comma prefix {,+var}.

    Non-standard extension to support partial expansions.
    """

    __slots__ = ()

    operator: ClassVar[str] = ',+'
    output_prefix: ClassVar[str] = ','

    def __init__(self, variables: str, charset: type[Charset]) -> None:
        super().__init__(variables[1:], charset)

    def _expand_var(self, variable: Variable, value: Any) -> (str | None):
        """Expand a single variable."""
        return self._encode_var(variable, self._uri_encode_name(variable.name), value,
                                delim=('.' if variable.explode else ','))
