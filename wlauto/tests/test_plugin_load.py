#    Copyright 2013-2015 ARM Limited
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
#


# pylint: disable=E0611,R0201
import os
from unittest import TestCase

from nose.tools import assert_equal

from wlauto.core.plugin import PluginLoader
from wlauto.core.plugin import Plugin, Alias
from wlauto.core.configuration.configuration import ConfigurationPoint
from wlauto.exceptions import NotFoundError

EXTDIR = os.path.join(os.path.dirname(__file__), 'data', 'plugins')


class FakePlugin(Plugin):
    name = "fake_plugin"
    parameters = [
        ConfigurationPoint("param1", default=123),
        ConfigurationPoint("param2", default=456),
        ConfigurationPoint("param3"),
    ]

    aliases = [
        Alias("alias1", param1="abc", param3="def")
    ]

class PluginLoaderTest(TestCase):

    def test_plugin_aliases(self):
        plugin_loader = PluginLoader()
        plugin_loader.plugins["fake_plugin"] = FakePlugin

        expected_config = {
            'param1': 123,
            'param2': 456,
            'param3': None,
            'modules': None,
        }
        assert_equal(expected_config, plugin_loader.get_default_config("fake_plugin"))
        with self.assertRaises(NotFoundError):
            plugin_loader.get_default_config("alias1")

        plugin_loader.aliases["alias1"] = FakePlugin.aliases["alias1"]

        expected_alias_config = {
            "param1": "abc",
            "param2": 456,
            "param3": "def",
            "modules": None
        }
        assert_equal(expected_alias_config, plugin_loader.get_default_config("alias1"))
