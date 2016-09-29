import re
from collections import OrderedDict
from copy import copy

from wlauto.utils.types import integer, boolean, identifier
from wlauto.exceptions import ConfigError
from wlauto.utils.serializer import is_pod
from wlauto.utils.misc import get_article, merge_config_values

# Mapping for kind conversion; see docs for convert_types below
KIND_MAP = {
    int: integer,
    bool: boolean,
    dict: OrderedDict,
}


def get_type_name(kind):
    typename = str(kind)
    if '\'' in typename:
        typename = typename.split('\'')[1]
    elif typename.startswith('<function'):
        typename = typename.split()[1]
    return typename


class ConfigurationPoint(object):
    """
    This defines a generic configuration point for workload automation. This is
    used to handle global settings, plugin parameters, etc.

    """

    def __init__(self, name,
                 kind=None,
                 mandatory=None,
                 default=None,
                 override=False,
                 allowed_values=None,
                 description=None,
                 constraint=None,
                 merge=False,
                 aliases=None,
                 global_alias=None):
        """
        Create a new Parameter object.

        :param name: The name of the parameter. This will become an instance
                     member of the plugin object to which the parameter is
                     applied, so it must be a valid python  identifier. This
                     is the only mandatory parameter.
        :param kind: The type of parameter this is. This must be a callable
                     that takes an arbitrary object and converts it to the
                     expected type, or raised ``ValueError`` if such conversion
                     is not possible. Most Python standard types -- ``str``,
                     ``int``, ``bool``, etc. -- can be used here. This
                     defaults to ``str`` if not specified.
        :param mandatory: If set to ``True``, then a non-``None`` value for
                          this parameter *must* be provided on plugin
                          object construction, otherwise ``ConfigError``
                          will be raised.
        :param default: The default value for this parameter. If no value
                        is specified on plugin construction, this value
                        will be used instead. (Note: if this is specified
                        and is not ``None``, then ``mandatory`` parameter
                        will be ignored).
        :param override: A ``bool`` that specifies whether a parameter of
                         the same name further up the hierarchy should
                         be overridden. If this is ``False`` (the
                         default), an exception will be raised by the
                         ``AttributeCollection`` instead.
        :param allowed_values: This should be the complete list of allowed
                               values for this parameter.  Note: ``None``
                               value will always be allowed, even if it is
                               not in this list.  If you want to disallow
                               ``None``, set ``mandatory`` to ``True``.
        :param constraint: If specified, this must be a callable that takes
                           the parameter value as an argument and return a
                           boolean indicating whether the constraint has been
                           satisfied. Alternatively, can be a two-tuple with
                           said callable as the first element and a string
                           describing the constraint as the second.
        :param merge: The default behaviour when setting a value on an object
                      that already has that attribute is to overrided with
                      the new value. If this is set to ``True`` then the two
                      values will be merged instead. The rules by which the
                      values are merged will be determined by the types of
                      the existing and new values -- see
                      ``merge_config_values`` documentation for details.
        :param aliases: Alternative names for the same configuration point.
                        These are largely for backwards compatibility.
        :param global_alias: An alias for this parameter that can be specified at
                            the global level. A global_alias can map onto many
                            ConfigurationPoints.
        """
        self.name = identifier(name)
        if kind in KIND_MAP:
            kind = KIND_MAP[kind]
        if kind is not None and not callable(kind):
            raise ValueError('Kind must be callable.')
        self.kind = kind
        self.mandatory = mandatory
        if not is_pod(default):
            msg = "The default for '{}' must be a Plain Old Data type, but it is of type '{}' instead."
            raise TypeError(msg.format(self.name, type(default)))
        self.default = default
        self.override = override
        self.allowed_values = allowed_values
        self.description = description
        if self.kind is None and not self.override:
            self.kind = str
        if constraint is not None and not callable(constraint) and not isinstance(constraint, tuple):
            raise ValueError('Constraint must be callable or a (callable, str) tuple.')
        self.constraint = constraint
        self.merge = merge
        self.aliases = aliases or []
        self.global_alias = global_alias

        if self.default is not None:
            try:
                self.validate_value("init", self.default)
            except ConfigError:
                raise ValueError('Default value "{}" is not valid'.format(self.default))

    def match(self, name):
        if name == self.name or name in self.aliases:
            return True
        elif name == self.global_alias:
            return True
        return False

    def set_value(self, obj, value=None, check_mandatory=True):
        if value is None:
            if self.default is not None:
                value = self.default
            elif check_mandatory and self.mandatory:
                msg = 'No values specified for mandatory parameter "{}" in {}'
                raise ConfigError(msg.format(self.name, obj.name))
        else:
            try:
                value = self.kind(value)
            except (ValueError, TypeError):
                typename = get_type_name(self.kind)
                msg = 'Bad value "{}" for {}; must be {} {}'
                article = get_article(typename)
                raise ConfigError(msg.format(value, self.name, article, typename))
        if value is not None:
            self.validate_value(obj.name, value)
        if self.merge and hasattr(obj, self.name):
            value = merge_config_values(getattr(obj, self.name), value)
        setattr(obj, self.name, value)

    def validate(self, obj):
        value = getattr(obj, self.name, None)
        if value is not None:
            self.validate_value(obj.name, value)
        else:
            if self.mandatory:
                msg = 'No value specified for mandatory parameter "{}" in {}.'
                raise ConfigError(msg.format(self.name, obj.name))

    def validate_value(self, name, value):
        if self.allowed_values:
            self.validate_allowed_values(name, value)
        if self.constraint:
            self.validate_constraint(name, value)

    def validate_allowed_values(self, name, value):
        if 'list' in str(self.kind):
            for v in value:
                if v not in self.allowed_values:
                    msg = 'Invalid value {} for {} in {}; must be in {}'
                    raise ConfigError(msg.format(v, self.name, name, self.allowed_values))
        else:
            if value not in self.allowed_values:
                msg = 'Invalid value {} for {} in {}; must be in {}'
                raise ConfigError(msg.format(value, self.name, name, self.allowed_values))

    def validate_constraint(self, name, value):
        msg_vals = {'value': value, 'param': self.name, 'plugin': name}
        if isinstance(self.constraint, tuple) and len(self.constraint) == 2:
            constraint, msg = self.constraint  # pylint: disable=unpacking-non-sequence
        elif callable(self.constraint):
            constraint = self.constraint
            msg = '"{value}" failed constraint validation for "{param}" in "{plugin}".'
        else:
            raise ValueError('Invalid constraint for "{}": must be callable or a 2-tuple'.format(self.name))
        if not constraint(value):
            raise ConfigError(value, msg.format(**msg_vals))

    def __repr__(self):
        d = copy(self.__dict__)
        del d['description']
        return 'ConfigurationPoint({})'.format(d)

    __str__ = __repr__


class RuntimeParameter(object):

    def __init__(self, name,
                 kind=None,
                 description=None,
                 merge=False):

        self.name = re.compile(name)
        if kind is not None:
            if kind in KIND_MAP:
                kind = KIND_MAP[kind]
            if not callable(kind):
                raise ValueError('Kind must be callable.')
        else:
            kind = str
        self.kind = kind
        self.description = description
        self.merge = merge

    def validate_kind(self, value, name):
        try:
            value = self.kind(value)
        except (ValueError, TypeError):
            typename = get_type_name(self.kind)
            msg = 'Bad value "{}" for {}; must be {} {}'
            article = get_article(typename)
            raise ConfigError(msg.format(value, name, article, typename))

    def match(self, name):
        if self.name.match(name):
            return True
        return False

    def update_value(self, name, new_value, source, dest):
        self.validate_kind(new_value, name)

        if name in dest:
            old_value, sources = dest[name]
        else:
            old_value = None
            sources = {}
        sources[source] = new_value

        if self.merge:
            new_value = merge_config_values(old_value, new_value)

        dest[name] = (new_value, sources)


class RuntimeParameterManager(object):

    runtime_parameters = []

    def __init__(self, target_manager):
        self.state = {}
        self.target_manager = target_manager

    def get_initial_state(self):
        """
        Should be used to load the starting state from the device. This state
        should be updated if any changes are made to the device, and they are successful.
        """
        pass

    def match(self, name):
        for rtp in self.runtime_parameters:
            if rtp.match(name):
                return True
        return False

    def update_value(self, name, value, source, dest):
        for rtp in self.runtime_parameters:
            if rtp.match(name):
                rtp.update_value(name, value, source, dest)
                break
        else:
            msg = 'Unknown runtime parameter "{}"'
            raise ConfigError(msg.format(name))

    def static_validation(self, params):
        """
        Validate values that do not require a active device connection.
        This method should also pop all runtime parameters meant for this manager
        from params, even if they are not beign statically validated.
        """
        pass

    def dynamic_validation(self, params):
        """
        Validate values that require an active device connection
        """
        pass

    def commit(self):
        """
        All values have been validated, this will now actually set values
        """
        pass


class CpuFreqParameters(object):

    runtime_parameters = {
        "cores": RuntimeParameter("(.+)_cores"),
        "min_frequency": RuntimeParameter("(.+)_min_frequency", kind=int),
        "max_frequency": RuntimeParameter("(.+)_max_frequency", kind=int),
        "frequency": RuntimeParameter("(.+)_frequency", kind=int),
        "governor": RuntimeParameter("(.+)_governor"),
        "governor_tunables": RuntimeParameter("(.+)_governor_tunables"),
    }

    def __init__(self, target):
        super(CpuFreqParameters, self).__init__(target)
        self.core_names = set(target.core_names)

    def match(self, name):
        for param in self.runtime_parameters.itervalues():
            if param.match(name):
                return True
        return False

    def update_value(self, name, value, source):
        for param in self.runtime_parameters.iteritems():
            core_name_match = param.name.match(name)
            if not core_name_match:
                continue

            core_name = core_name_match.groups()[0]
            if core_name not in self.core_names:
                msg = '"{}" in {} is not a valid core name, must be in: {}'
                raise ConfigError(msg.format(core_name, name, ", ".join(self.core_names)))

            param.update_value(name, value, source)
            break
        else:
            RuntimeError('"{}" does not belong to CpuFreqParameters'.format(name))

    def _get_merged_value(self, core, param_name):
        return self.runtime_parameters[param_name].merged_values["{}_{}".format(core, param_name)]

    def _cross_validate(self, core):
        min_freq = self._get_merged_value(core, "min_frequency")
        max_frequency = self._get_merged_value(core, "max_frequency")
        if max_frequency < min_freq:
            msg = "{core}_max_frequency must be larger than {core}_min_frequency"
            raise ConfigError(msg.format(core=core))
        frequency = self._get_merged_value(core, "frequency")
        if not min_freq < frequency < max_frequency:
            msg = "{core}_frequency must be between {core}_min_frequency and {core}_max_frequency"
            raise ConfigError(msg.format(core=core))
        # TODO: more checks

    def commit_to_device(self, target):
        pass
        # TODO: Write values to device is correct order ect
