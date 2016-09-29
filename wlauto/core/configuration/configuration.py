#    Copyright 2014-2016 ARM Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from copy import copy
from collections import OrderedDict, defaultdict

from wlauto.exceptions import ConfigError
from wlauto.utils.types import list_of_strings, toggle_set, obj_dict, identifier
from wlauto.core.configuration.tree import SectionNode
from wlauto.core.configuration.configuration_points import (ConfigurationPoint)


ITERATION_STATUS = [
    'NOT_STARTED',
    'RUNNING',

    'OK',
    'NONCRITICAL',
    'PARTIAL',
    'FAILED',
    'ABORTED',
    'SKIPPED',
]


class RebootPolicy(object):
    """
    Represents the reboot policy for the execution -- at what points the device
    should be rebooted. This, in turn, is controlled by the policy value that is
    passed in on construction and would typically be read from the user's settings.
    Valid policy values are:

    :never: The device will never be rebooted.
    :as_needed: Only reboot the device if it becomes unresponsive, or needs to be flashed, etc.
    :initial: The device will be rebooted when the execution first starts, just before
              executing the first workload spec.
    :each_spec: The device will be rebooted before running a new workload spec.
    :each_iteration: The device will be rebooted before each new iteration.

    """

    valid_policies = ['never', 'as_needed', 'initial', 'each_spec', 'each_iteration']

    def __init__(self, policy):
        policy = policy.strip().lower().replace(' ', '_')
        if policy not in self.valid_policies:
            message = 'Invalid reboot policy {}; must be one of {}'.format(policy, ', '.join(self.valid_policies))
            raise ConfigError(message)
        self.policy = policy

    @property
    def can_reboot(self):
        return self.policy != 'never'

    @property
    def perform_initial_boot(self):
        return self.policy not in ['never', 'as_needed']

    @property
    def reboot_on_each_spec(self):
        return self.policy in ['each_spec', 'each_iteration']

    @property
    def reboot_on_each_iteration(self):
        return self.policy == 'each_iteration'

    def __str__(self):
        return self.policy

    __repr__ = __str__

    def __cmp__(self, other):
        if isinstance(other, RebootPolicy):
            return cmp(self.policy, other.policy)
        else:
            return cmp(self.policy, other)

    def to_pod(self):
        return self.policy

    @staticmethod
    def from_pod(pod):
        return RebootPolicy(pod)


class status_list(list):

    def append(self, item):
        list.append(self, str(item).upper())


class LoggingConfig(dict):

    defaults = {
        'file_format': '%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        'verbose_format': '%(asctime)s %(levelname)-8s %(name)s: %(message)s',
        'regular_format': '%(levelname)-8s %(message)s',
        'color': True,
    }

    def __init__(self, config=None):
        dict.__init__(self)
        if isinstance(config, dict):
            config = {identifier(k.lower()): v for k, v in config.iteritems()}
            self['regular_format'] = config.pop('regular_format', self.defaults['regular_format'])
            self['verbose_format'] = config.pop('verbose_format', self.defaults['verbose_format'])
            self['file_format'] = config.pop('file_format', self.defaults['file_format'])
            self['color'] = config.pop('colour_enabled', self.defaults['color'])  # legacy
            self['color'] = config.pop('color', self.defaults['color'])
            if config:
                message = 'Unexpected logging configuation parameters: {}'
                raise ValueError(message.format(bad_vals=', '.join(config.keys())))
        elif config is None:
            for k, v in self.defaults.iteritems():
                self[k] = v
        else:
            raise ValueError(config)


class Configuration(object):

    config_points = []
    name = ""
    parser_attribute_name = None
    # The below line must be added to all subclasses
    configuration = {cp.name: cp for cp in config_points}

    def __init__(self):
        # Load default values for configuration points
        for confpoint in self.configuration.itervalues():
            confpoint.set_value(self, check_mandatory=False)

    def set(self, name, value, check_mandatory=True):
        if name not in self.configuration:
            raise ConfigError('Unknown {} configuration "{}"'.format(self.name, name))
        self.configuration[name].set_value(self, value, check_mandatory=check_mandatory)

    def update_config(self, values, check_mandatory=True):
        for k, v in values.iteritems():
            self.set(k, v, check_mandatory=check_mandatory)

    def validate(self):
        for cfg_point in self.configuration.itervalues():
            cfg_point.validate(self)

    def to_pod(self):
        pod = {}
        for cfg_point_name in self.configuration.iterkeys():
            value = getattr(self, cfg_point_name, None)
            if value is not None:
                pod[cfg_point_name] = value
        return pod

    @classmethod
    # pylint: disable=unused-argument
    def from_pod(cls, pod, plugin_cache):
        instance = cls()
        for name, cfg_point in cls.configuration.iteritems():
            if name in pod:
                cfg_point.set_value(instance, pod.pop(name))
        if pod:
            msg = 'Invalid entry(ies) for "{}": "{}"'
            raise ConfigError(msg.format(cls.name, '", "'.join(pod.keys())))
        instance.validate()
        return instance

    def fetch_config(self, sources, *args):
        for source in sources:
            for parser in args:
                parser_value = getattr(parser, self.parser_attribute_name)
                if source not in parser_value:
                    continue
                for name, cfg_point in self.configuration.iteritems():
                    if name not in parser_value[source]:
                        continue
                    cfg_point.set_value(self, value=parser_value[source][name])


# This configuration for the core WA framework
class CoreConfiguration(Configuration):

    name = "WA Configuration"
    parser_attribute_name = "core_config"
    config_points = [
        ConfigurationPoint(
            'user_directory',
            description="""
            Path to the user directory. This is the location WA will look for
            user configuration, additional plugins and plugin dependencies.
            """,
            kind=str,
            default=os.path.join(os.path.expanduser('~'), '.workload_automation'),
        ),
        ConfigurationPoint(
            'plugin_packages',
            kind=list_of_strings,
            default=[
                'wlauto.commands',
                'wlauto.workloads',
                'wlauto.instrumentation',
                'wlauto.result_processors',
                'wlauto.managers',
                'wlauto.resource_getters',
            ],
            description="""
            List of packages that will be scanned for WA plugins.
            """,
        ),
        ConfigurationPoint(
            'plugin_paths',
            kind=list_of_strings,
            default=[
                'workloads',
                'instruments',
                'targets',
                'processors',

                # Legacy
                'managers',
                'result_processors',
            ],
            description="""
            List of paths that will be scanned for WA plugins.
            """,
            merge=True
        ),
        ConfigurationPoint(
            'plugin_ignore_paths',
            kind=list_of_strings,
            default=[],
            description="""
            List of (sub)paths that will be ignored when scanning
            ``plugin_paths`` for WA plugins.
            """,
        ),
        ConfigurationPoint(
            'logging',
            kind=LoggingConfig,
            default=LoggingConfig.defaults,
            description="""
            WA logging configuration. This should be a dict with a subset
            of the following keys::

            :normal_format: Logging format used for console output
            :verbose_format: Logging format used for verbose console output
            :file_format: Logging format used for run.log
            :color: If ``True`` (the default), console logging output will
                    contain bash color escape codes. Set this to ``False`` if
                    console output will be piped somewhere that does not know
                    how to handle those.
            """,
        ),
        ConfigurationPoint(
            'verbosity',
            kind=int,
            default=0,
            description="""
            Verbosity of console output.
            """,
        ),
        ConfigurationPoint(  # TODO: Needs some format for dates ect/ comes from cfg
            'default_output_directory',
            default="wa_output",
            description="""
            The default output directory that will be created if not
            specified when invoking a run.
            """,
        ),
    ]
    configuration = {cp.name: cp for cp in config_points}

    @property
    def dependencies_directory(self):
        return "{}/dependencies/".format(self.user_directory)


# This is generic top-level configuration for WA runs.
class RunConfiguration(Configuration):

    name = "Run Configuration"
    parser_attribute_name = 'run_config'

    # Metadata is separated out because it is not loaded into the auto generated config file
    meta_data = [
        ConfigurationPoint('run_name', kind=str,
                           description='''
                           A string that labels the WA run that is being performed. This would typically
                           be set in the ``config`` section of an agenda (see
                           :ref:`configuration in an agenda <configuration_in_agenda>`) rather than in the config file.

                           .. _old-style format strings: http://docs.python.org/2/library/stdtypes.html#string-formatting-operations
                           .. _log record attributes: http://docs.python.org/2/library/logging.html#logrecord-attributes
                           '''),
        ConfigurationPoint('project', kind=str,
                           description='''
                           A string naming the project for which data is being collected. This may be
                           useful, e.g. when uploading data to a shared database that is populated from
                           multiple projects.
                           '''),
        ConfigurationPoint('project_stage', kind=dict,
                           description='''
                           A dict or a string that allows adding additional identifier. This is may be
                           useful for long-running projects.
                           '''),
    ]
    config_points = [
        ConfigurationPoint('execution_order', kind=str, default='by_iteration',
                           allowed_values=['by_iteration', 'by_spec', 'by_section', 'random'],
                           description='''
                           Defines the order in which the agenda spec will be executed. At the moment,
                           the following execution orders are supported:

                           ``"by_iteration"``
                             The first iteration of each workload spec is executed one after the other,
                             so all workloads are executed before proceeding on to the second iteration.
                             E.g. A1 B1 C1 A2 C2 A3. This is the default if no order is explicitly specified.

                             In case of multiple sections, this will spread them out, such that specs
                             from the same section are further part. E.g. given sections X and Y, global
                             specs A and B, and two iterations, this will run ::

                                             X.A1, Y.A1, X.B1, Y.B1, X.A2, Y.A2, X.B2, Y.B2

                           ``"by_section"``
                             Same  as ``"by_iteration"``, however this will group specs from the same
                             section together, so given sections X and Y, global specs A and B, and two iterations,
                             this will run ::

                                     X.A1, X.B1, Y.A1, Y.B1, X.A2, X.B2, Y.A2, Y.B2

                           ``"by_spec"``
                             All iterations of the first spec are executed before moving on to the next
                             spec. E.g. A1 A2 A3 B1 C1 C2 This may also be specified as ``"classic"``,
                             as this was the way workloads were executed in earlier versions of WA.

                           ``"random"``
                             Execution order is entirely random.
                           '''),
        ConfigurationPoint('reboot_policy', kind=RebootPolicy, default='as_needed',
                           allowed_values=RebootPolicy.valid_policies,
                           description='''
                           This defines when during execution of a run the Device will be rebooted. The
                           possible values are:

                           ``"never"``
                              The device will never be rebooted.
                           ``"initial"``
                              The device will be rebooted when the execution first starts, just before
                              executing the first workload spec.
                           ``"each_spec"``
                              The device will be rebooted before running a new workload spec.
                              Note: this acts the same as each_iteration when execution order is set to by_iteration
                           ``"each_iteration"``
                              The device will be rebooted before each new iteration.
                           '''),
        ConfigurationPoint('device', kind=str, mandatory=True,
                           description='''
                           This setting defines what specific Device subclass will be used to interact
                           the connected device. Obviously, this must match your setup.
                           '''),
        ConfigurationPoint('retry_on_status', kind=status_list,
                           default=['FAILED', 'PARTIAL'],
                           allowed_values=ITERATION_STATUS,
                           description='''
                           This is list of statuses on which a job will be cosidered to have failed and
                           will be automatically retried up to ``max_retries`` times. This defaults to
                           ``["FAILED", "PARTIAL"]`` if not set. Possible values are:

                           ``"OK"``
                           This iteration has completed and no errors have been detected

                           ``"PARTIAL"``
                           One or more instruments have failed (the iteration may still be running).

                           ``"FAILED"``
                           The workload itself has failed.

                           ``"ABORTED"``
                           The user interupted the workload
                           '''),
        ConfigurationPoint('max_retries', kind=int, default=3,
                           description='''
                           The maximum number of times failed jobs will be retried before giving up. If
                           not set, this will default to ``3``.

                           .. note:: this number does not include the original attempt
                           '''),
    ]
    configuration = {cp.name: cp for cp in config_points + meta_data}

    def __init__(self):
        super(RunConfiguration, self).__init__()
        self.device_config = None

    def merge_device_config(self, plugin_cache):
        """
        Merges global device config and validates that it is correct for the
        selected device.
        """
        # pylint: disable=no-member
        self.device_config = plugin_cache.get_plugin_config(self.device,
                                                            generic_name="device_config")

    def to_pod(self):
        pod = super(RunConfiguration, self).to_pod()
        pod['device_config'] = self.device_config
        return pod

    # pylint: disable=no-member
    @classmethod
    def from_pod(cls, pod, plugin_cache):
        try:
            device_config = obj_dict(values=pod.pop("device_config"), not_in_dict=['name'])
        except KeyError as e:
            msg = 'No value specified for mandatory parameter "{}".'
            raise ConfigError(msg.format(e.args[0]))

        instance = super(RunConfiguration, cls).from_pod(pod, plugin_cache)

        device_config.name = "device_config"
        cfg_points = plugin_cache.get_plugin_parameters(instance.device)
        for entry_name in device_config.iterkeys():
            if entry_name not in cfg_points.iterkeys():
                msg = 'Invalid entry "{}" for device "{}".'
                raise ConfigError(msg.format(entry_name, instance.device, cls.name))
            else:
                cfg_points[entry_name].validate(device_config)

        instance.device_config = device_config
        return instance


# This is the configuration for WA jobs
class JobSpec(Configuration):

    name = "Job Spec"

    config_points = [
        ConfigurationPoint('iterations', kind=int, default=1,
                           description='''
                           How many times to repeat this workload spec
                           '''),
        ConfigurationPoint('workload_name', kind=str, mandatory=True,
                           aliases=["name"],
                           description='''
                           The name of the workload to run.
                           '''),
        ConfigurationPoint('label', kind=str,
                           description='''
                           Similar to IDs but do not have the uniqueness restriction.
                           If specified, labels will be used by some result
                           processes instead of (or in addition to) the workload
                           name. For example, the csv result processor will put
                           the label in the "workload" column of the CSV file.
                           '''),
        ConfigurationPoint('instrumentation', kind=toggle_set, merge=True,
                           aliases=["instruments"],
                           description='''
                           The instruments to enable (or disabled using a ~)
                           during this workload spec.
                           '''),
        ConfigurationPoint('flash', kind=dict, merge=True,
                           description='''

                           '''),
        ConfigurationPoint('classifiers', kind=dict, merge=True,
                           description='''
                           Classifiers allow you to tag metrics from this workload
                           spec to help in post processing them. Theses are often
                           used to help identify what runtime_parameters were used
                           for results when post processing.
                           '''),
    ]
    configuration = {cp.name: cp for cp in config_points}

    def __init__(self):
        super(JobSpec, self).__init__()
        self.to_merge = defaultdict(OrderedDict)
        self._sources = []
        self.id = None
        self.workload_parameters = None
        self.runtime_parameters = None
        self.boot_parameters = None

    def update_config(self, source, check_mandatory=True):
        self._sources.append(source)
        values = source.config
        for k, v in values.iteritems():
            if k == "id":
                continue
            elif k in ["workload_parameters", "runtime_parameters", "boot_parameters"]:
                if v:
                    self.to_merge[k][source] = copy(v)
            else:
                try:
                    self.set(k, v, check_mandatory=check_mandatory)
                except ConfigError as e:
                    msg = 'Error in {}:\n\t{}'
                    raise ConfigError(msg.format(source.name, e.message))

    # pylint: disable=no-member
    # Only call after the rest of the JobSpec is merged
    def merge_workload_parameters(self, plugin_cache):
        # merge global generic and specific config
        workload_params = plugin_cache.get_plugin_config(self.workload_name,
                                                         generic_name="workload_parameters")

        # Merge entry "workload_parameters"
        # TODO: Wrap in - "error in [agenda path]"
        cfg_points = plugin_cache.get_plugin_parameters(self.workload_name)
        for source in self._sources:
            if source in self.to_merge["workload_params"]:
                config = self.to_merge["workload_params"][source]
                for name, cfg_point in cfg_points.iteritems():
                    if name in config:
                        value = config.pop(name)
                        cfg_point.set_value(workload_params, value, check_mandatory=False)
                if config:
                    msg = 'conflicting entry(ies) for "{}" in {}: "{}"'
                    msg = msg.format(self.workload_name, source.name,
                                     '", "'.join(workload_params[source]))

        self.workload_parameters = workload_params

    def merge_runtime_parameters(self, plugin_cache, target_manager):

        # Order global runtime parameters
        runtime_parameters = OrderedDict()
        global_runtime_params = plugin_cache.get_plugin_config("runtime_parameters")
        for source in plugin_cache.sources:
            runtime_parameters[source] = global_runtime_params[source]

        # Add runtime parameters from JobSpec
        for source, values in self.to_merge['runtime_parameters'].iteritems():
            runtime_parameters[source] = values

        # Merge
        self.runtime_parameters = target_manager.merge_runtime_parameters(runtime_parameters)

    def finalize(self):
        self.id = "-".join([source.config['id'] for source in self._sources[1:]])  # ignore first id, "global"

    def to_pod(self):
        pod = super(JobSpec, self).to_pod()
        pod['workload_parameters'] = self.workload_parameters
        pod['runtime_parameters'] = self.runtime_parameters
        pod['boot_parameters'] = self.boot_parameters
        return pod

    @classmethod
    def from_pod(cls, pod, plugin_cache):
        try:
            workload_parameters = pod['workload_parameters']
            runtime_parameters = pod['runtime_parameters']
            boot_parameters = pod['boot_parameters']
        except KeyError as e:
            msg = 'No value specified for mandatory parameter "{}}".'
            raise ConfigError(msg.format(e.args[0]))

        instance = super(JobSpec, cls).from_pod(pod, plugin_cache)

        # TODO: validate parameters and construct the rest of the instance


# This is used to construct the list of Jobs WA will run
class JobGenerator(object):

    name = "Jobs Configuration"
    parser_attribute_name = "jobs_config"

    @property
    def enabled_instruments(self):
        self._read_enabled_instruments = True
        return self._enabled_instruments

    def update_enabled_instruments(self, value):
        if self._read_enabled_instruments:
            msg = "'enabled_instruments' cannot be updated after it has been accessed"
            raise RuntimeError(msg)
        self._enabled_instruments.update(value)

    def __init__(self, plugin_cache):
        self.plugin_cache = plugin_cache
        self.ids_to_run = []
        self.sections = []
        self.workloads = []
        self._enabled_instruments = set()
        self._read_enabled_instruments = False
        self.disabled_instruments = []

        self.job_spec_template = obj_dict(not_in_dict=['name'])
        self.job_spec_template.name = "globally specified job spec configuration"
        self.job_spec_template.id = "global"
        # Load defaults
        for cfg_point in JobSpec.configuration.itervalues():
            cfg_point.set_value(self.job_spec_template, check_mandatory=False)

        self.root_node = SectionNode(self.job_spec_template)

    def set_global_value(self, name, value):
        JobSpec.configuration[name].set_value(self.job_spec_template, value,
                                              check_mandatory=False)
        if name == "instrumentation":
            self.update_enabled_instruments(value)

    def add_section(self, section, workloads):
        new_node = self.root_node.add_section(section)
        for workload in workloads:
            new_node.add_workload(workload)

    def add_workload(self, workload):
        self.root_node.add_workload(workload)

    def disable_instruments(self, instruments):
        # TODO: Validate
        self.disabled_instruments = ["~{}".format(i) for i in instruments]

    def only_run_ids(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        self.ids_to_run = ids

    def generate_job_specs(self, target_manager):

        for leaf in self.root_node.leaves():
            # PHASE 1: Gather workload and section entries for this leaf
            workload_entries = leaf.workload_entries
            sections = [leaf]
            for ancestor in leaf.ancestors():
                workload_entries += ancestor.workload_entries
                sections.insert(0, ancestor)

            # PHASE 2: Create job specs for this leaf
            for workload_entry in workload_entries:
                job_spec = JobSpec()  # Loads defaults

                # PHASE 2.1: Merge general job spec configuration
                for section in sections:
                    job_spec.update_config(section, check_mandatory=False)
                job_spec.update_config(workload_entry, check_mandatory=False)

                # PHASE 2.2: Merge global, section and workload entry "workload_parameters"
                job_spec.merge_workload_parameters(self.plugin_cache)
                target_manager.static_runtime_parameter_validation(job_spec.runtime_parameters)

                # TODO: PHASE 2.3: Validate device runtime/boot paramerers
                job_spec.merge_runtime_parameters(self.plugin_cache, target_manager)
                target_manager.validate_runtime_parameters(job_spec.runtime_parameters)

                # PHASE 2.4: Disable globally disabled instrumentation
                job_spec.set("instrumentation", self.disabled_instruments)
                job_spec.finalize()

                # PHASE 2.5: Skip job_spec if part of it's ID is not in self.ids_to_run
                if self.ids_to_run:
                    for job_id in self.ids_to_run:
                        if job_id in job_spec.id:
                            # TODO: logging
                            break
                    else:
                        continue

                # PHASE 2.6: Update list of instruments that need to be setup
                # pylint: disable=no-member
                self.update_enabled_instruments(job_spec.instrumentation.values())

                yield job_spec

core_config = CoreConfiguration()
