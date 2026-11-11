"""Contract tests for the linux_snmp_agent role, evaluated with Ansible's own templating engine.

Every address is from the RFC 5737 documentation ranges and every credential
below is an obviously synthetic placeholder built at run time.
"""

import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/linux_snmp_agent"
CREDENTIAL_TYPE = ROOT / "awx/credential-types/linux-snmp-agent/v1"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
ROLE_VARS = yaml.safe_load((ROLE / "vars/main.yml").read_text(encoding="utf-8"))
ARGUMENT_SPEC = yaml.safe_load((ROLE / "meta/argument_specs.yml").read_text(encoding="utf-8"))[
    "argument_specs"
]["main"]["options"]
init_plugin_loader()

# Synthetic placeholders assembled here so that no credential-shaped literal
# is committed. They satisfy the role's length and character rules.
USER = "example_poller"
AUTH = "-".join(["synthetic", "auth", "placeholder"])
PRIV = "-".join(["synthetic", "priv", "placeholder"])
COMMUNITY = "-".join(["synthetic", "community", "placeholder"])
SECRET_VARIABLES = (
    "linux_snmp_agent_v3_user",
    "linux_snmp_agent_v3_auth_passphrase",
    "linux_snmp_agent_v3_priv_passphrase",
    "linux_snmp_agent_v2c_community",
)
SECRET_ENVIRONMENT = {
    "linux_snmp_agent_v3_user": "SERVICERADAR_SNMP_V3_USER",
    "linux_snmp_agent_v3_auth_passphrase": "SERVICERADAR_SNMP_V3_AUTH_PASSPHRASE",
    "linux_snmp_agent_v3_priv_passphrase": "SERVICERADAR_SNMP_V3_PRIV_PASSPHRASE",
    "linux_snmp_agent_v2c_community": "SERVICERADAR_SNMP_V2C_COMMUNITY",
}
# Anything derived from a secret is itself secret-bearing.
SECRET_DERIVED = SECRET_VARIABLES + (
    "linux_snmp_agent_secret_errors",
    "linux_snmp_agent_v3_user_hex",
    "linux_snmp_agent_v3_user_line_pattern",
)
SECRET_TEMPLATES = ("snmpd.conf.j2", "client-snmp.conf.j2")


def role_variables(**overrides):
    variables = dict(DEFAULTS)
    variables.update(ROLE_VARS)
    variables.update(
        {
            "ansible_facts": {"os_family": "Debian"},
            "linux_snmp_agent_poller_sources": ["192.0.2.10", "198.51.100.0/24"],
            "linux_snmp_agent_v3_user": USER,
            "linux_snmp_agent_v3_auth_passphrase": AUTH,
            "linux_snmp_agent_v3_priv_passphrase": PRIV,
            "linux_snmp_agent_v2c_community": "",
        }
    )
    variables.update(overrides)
    return variables


def evaluate(name, **overrides):
    templar = Templar(loader=DataLoader(), variables=role_variables(**overrides))
    return templar.template("{{ " + name + " }}")


def render(template, **overrides):
    templar = Templar(loader=DataLoader(), variables=role_variables(**overrides))
    return templar.template((ROLE / "templates" / template).read_text(encoding="utf-8"))


def role_tasks():
    """Yield (file, task) for every task in the role, including nested blocks."""

    def walk(path, tasks):
        for task in tasks or []:
            yield path, task
            for section in ("block", "rescue", "always"):
                yield from walk(path, task.get(section))

    for path in sorted((ROLE / "tasks").glob("*.yml")):
        yield from walk(path, yaml.safe_load(path.read_text(encoding="utf-8")))


class PollerSourceTest(unittest.TestCase):
    def test_addresses_and_cidrs_are_normalized_for_every_filter_layer(self):
        sources = ["192.0.2.10", "198.51.100.0/24", "203.0.113.128/25", "192.0.2.10/32"]
        self.assertEqual(evaluate("linux_snmp_agent_input_errors", linux_snmp_agent_poller_sources=sources), [])
        self.assertEqual(
            evaluate("linux_snmp_agent_source_cidrs", linux_snmp_agent_poller_sources=sources),
            ["192.0.2.10/32", "198.51.100.0/24", "203.0.113.128/25"],
        )
        self.assertEqual(
            evaluate("linux_snmp_agent_source_wrappers", linux_snmp_agent_poller_sources=sources),
            ["192.0.2.10", "198.51.100.0/255.255.255.0", "203.0.113.128/255.255.255.128"],
        )

    def test_an_empty_source_list_is_refused_as_answering_any_source(self):
        errors = evaluate("linux_snmp_agent_input_errors", linux_snmp_agent_poller_sources=[])
        self.assertEqual(len(errors), 1)
        self.assertIn("would answer any source", errors[0])

    def test_sources_that_would_answer_any_or_no_poller_are_refused(self):
        cases = {
            "0.0.0.0/0": "broader than /8",
            "0.0.0.0/1": "broader than /8",
            "128.0.0.0/1": "broader than /8",
            "198.0.0.0/7": "broader than /8",
            "0.0.0.0": "not a unicast poller address",
            "127.0.0.1": "not a unicast poller address",
            "224.0.0.1": "not a unicast poller address",
            "192.0.2.10/24": "host bits set",
            "192.0.2.256": "out of range",
            "192.0.2.10/33": "out of range",
            "192.0.02.10": "not an IPv4 address or CIDR",
            "default": "not an IPv4 address or CIDR",
            "host01.example.com": "not an IPv4 address or CIDR",
            "2001:db8::10": "not an IPv4 address or CIDR",
            "192.0.2.10 198.51.100.7": "not an IPv4 address or CIDR",
            "": "not an IPv4 address or CIDR",
        }
        for source, reason in cases.items():
            with self.subTest(source=source):
                errors = evaluate(
                    "linux_snmp_agent_input_errors",
                    linux_snmp_agent_poller_sources=["192.0.2.10", source],
                )
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("Poller source number 2", errors[0])
                self.assertIn(reason, errors[0])
                self.assertEqual(
                    evaluate(
                        "linux_snmp_agent_source_cidrs",
                        linux_snmp_agent_poller_sources=["192.0.2.10", source],
                    ),
                    ["192.0.2.10/32"],
                )

    def test_removal_does_not_need_poller_sources(self):
        self.assertEqual(
            evaluate(
                "linux_snmp_agent_input_errors",
                linux_snmp_agent_state="absent",
                linux_snmp_agent_poller_sources=[],
            ),
            [],
        )


class CredentialValidationTest(unittest.TestCase):
    def assert_no_value_is_repeated(self, errors, *values):
        for value in values:
            if value:
                self.assertNotIn(value, " ".join(errors))

    def test_a_complete_snmpv3_credential_is_accepted(self):
        self.assertEqual(evaluate("linux_snmp_agent_secret_errors"), [])

    def test_snmpv3_requires_every_part_of_the_credential(self):
        for variable in SECRET_VARIABLES[:3]:
            with self.subTest(missing=variable):
                errors = evaluate("linux_snmp_agent_secret_errors", **{variable: ""})
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("missing", errors[0])

    def test_weak_or_unsafe_snmpv3_values_are_refused_without_repeating_them(self):
        cases = {
            "linux_snmp_agent_v3_auth_passphrase": ["too-short", "has a space in it", 'quote"inside-it', "x" * 65],
            "linux_snmp_agent_v3_priv_passphrase": ["too-short", "tab\tinside-value", "back\\slash-value"],
            "linux_snmp_agent_v3_user": ["9starts-with-digit", "has space", "x" * 33, 'quo"te'],
        }
        for variable, values in cases.items():
            for value in values:
                with self.subTest(variable=variable, value=value):
                    errors = evaluate("linux_snmp_agent_secret_errors", **{variable: value})
                    self.assertEqual(len(errors), 1, errors)
                    self.assert_no_value_is_repeated(errors, value)

    def test_identical_authentication_and_privacy_passphrases_are_refused(self):
        errors = evaluate("linux_snmp_agent_secret_errors", linux_snmp_agent_v3_priv_passphrase=AUTH)
        self.assertEqual(errors, ["The SNMPv3 authentication and privacy passphrases must differ."])

    def test_snmpv2c_is_never_configured_without_a_supplied_community(self):
        errors = evaluate("linux_snmp_agent_secret_errors", linux_snmp_agent_mode="v2c")
        self.assertEqual(len(errors), 1)
        self.assertIn("There is no default community", errors[0])

    def test_every_well_known_community_is_refused_in_any_letter_case(self):
        denied = ROLE_VARS["linux_snmp_agent_denied_communities"]
        self.assertIn("public", denied)
        self.assertIn("private", denied)
        for community in denied:
            for spelling in (community, community.upper(), community.capitalize()):
                with self.subTest(community=spelling):
                    errors = evaluate(
                        "linux_snmp_agent_secret_errors",
                        linux_snmp_agent_mode="v2c",
                        linux_snmp_agent_v2c_community=spelling,
                    )
                    self.assertIn(
                        "The SNMPv2c community is a well-known default value and is refused.", errors
                    )

    def test_a_long_generated_community_is_accepted_and_a_short_one_is_not(self):
        self.assertEqual(
            evaluate(
                "linux_snmp_agent_secret_errors",
                linux_snmp_agent_mode="v2c",
                linux_snmp_agent_v2c_community=COMMUNITY,
            ),
            [],
        )
        errors = evaluate(
            "linux_snmp_agent_secret_errors",
            linux_snmp_agent_mode="v2c",
            linux_snmp_agent_v2c_community=COMMUNITY[:15],
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("16-64 characters", errors[0])
        self.assert_no_value_is_repeated(errors, COMMUNITY[:15])

    def test_a_community_in_the_credential_is_ignored_in_the_default_mode(self):
        self.assertEqual(
            evaluate("linux_snmp_agent_secret_errors", linux_snmp_agent_v2c_community="public"), []
        )
        self.assertNotIn("public", render("snmpd.conf.j2", linux_snmp_agent_v2c_community="public"))


class SecretSourceTest(unittest.TestCase):
    def test_secret_defaults_are_only_environment_lookups(self):
        for variable, environment in SECRET_ENVIRONMENT.items():
            self.assertEqual(
                DEFAULTS[variable],
                "{{ lookup('ansible.builtin.env', '" + environment + "') }}",
            )

    def test_secret_defaults_resolve_from_the_injected_environment(self):
        injected = {name: "injected-" + name.lower() for name in SECRET_ENVIRONMENT.values()}
        with patch.dict(os.environ, injected):
            templar = Templar(loader=DataLoader(), variables=dict(DEFAULTS))
            for variable, environment in SECRET_ENVIRONMENT.items():
                self.assertEqual(templar.template("{{ " + variable + " }}"), injected[environment])

    def test_secret_defaults_are_empty_without_a_credential(self):
        cleared = {key: value for key, value in os.environ.items() if key not in SECRET_ENVIRONMENT.values()}
        with patch.dict(os.environ, cleared, clear=True):
            templar = Templar(loader=DataLoader(), variables=dict(DEFAULTS))
            for variable in SECRET_ENVIRONMENT:
                self.assertEqual(templar.template("{{ " + variable + " }}"), "")

    def test_the_awx_credential_type_injects_exactly_those_variables_as_secrets(self):
        inputs = json.loads((CREDENTIAL_TYPE / "inputs.json").read_text(encoding="utf-8"))
        injectors = json.loads((CREDENTIAL_TYPE / "injectors.json").read_text(encoding="utf-8"))
        fields = {field["id"]: field for field in inputs["fields"]}
        self.assertEqual(
            set(fields), {"v3_user", "v3_auth_passphrase", "v3_priv_passphrase", "v2c_community"}
        )
        for field in fields.values():
            self.assertIs(field["secret"], True, field["id"])
            self.assertEqual(field["type"], "string")
            self.assertNotIn("default", field)
        self.assertEqual(
            sorted(inputs["required"]), ["v3_auth_passphrase", "v3_priv_passphrase", "v3_user"]
        )
        self.assertEqual(set(injectors), {"env"})
        self.assertEqual(
            injectors["env"],
            {
                environment: "{{ " + variable.removeprefix("linux_snmp_agent_") + " }}"
                for variable, environment in SECRET_ENVIRONMENT.items()
            },
        )


class ConfigurationTemplateTest(unittest.TestCase):
    def test_the_snmpv3_configuration_holds_no_passphrase_and_no_community_rule(self):
        config = render("snmpd.conf.j2")
        self.assertIn(f"rouser {USER} priv -V serviceradarRo\n", config)
        self.assertNotIn(AUTH, config)
        self.assertNotIn(PRIV, config)
        for directive in ("community", "com2sec", "createUser", "rwuser", "group ", "access "):
            self.assertNotRegex(config, r"(?im)^\s*\S*" + re.escape(directive))

    def test_the_snmpv2c_configuration_maps_only_loopback_and_the_poller_sources(self):
        config = render(
            "snmpd.conf.j2",
            linux_snmp_agent_mode="v2c",
            linux_snmp_agent_v2c_community=COMMUNITY,
        )
        self.assertEqual(
            re.findall(r"(?m)^com2sec (\S+) (\S+) (\S+)$", config),
            [
                ("serviceradarRoSec", "127.0.0.1", COMMUNITY),
                ("serviceradarRoSec", "192.0.2.10/32", COMMUNITY),
                ("serviceradarRoSec", "198.51.100.0/24", COMMUNITY),
            ],
        )
        self.assertEqual(
            re.findall(r"(?m)^(?:group|access) .*$", config),
            [
                "group serviceradarRoGroup v2c serviceradarRoSec",
                'access serviceradarRoGroup "" v2c noauth exact serviceradarRo none none',
            ],
        )
        self.assertNotRegex(config, r"(?im)^\s*(r[ow]community|rouser|rwuser)")
        self.assertNotRegex(config, r"(?m)\bdefault\b")

    def test_a_configuration_without_poller_sources_cannot_be_rendered(self):
        for mode in ("v3", "v2c"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(AnsibleError, "without poller sources"):
                    render(
                        "snmpd.conf.j2",
                        linux_snmp_agent_mode=mode,
                        linux_snmp_agent_v2c_community=COMMUNITY,
                        linux_snmp_agent_poller_sources=[],
                    )

    def test_the_agent_always_listens_on_loopback_for_verification(self):
        self.assertIn("agentaddress udp:0.0.0.0:161\n", render("snmpd.conf.j2"))
        self.assertIn(
            "agentaddress udp:127.0.0.1:1161,udp:192.0.2.20:1161\n",
            render(
                "snmpd.conf.j2",
                linux_snmp_agent_bind_address="192.0.2.20",
                linux_snmp_agent_port=1161,
            ),
        )

    def test_the_view_always_includes_system_and_hides_process_arguments(self):
        config = render(
            "snmpd.conf.j2",
            linux_snmp_agent_view_oids=[".1.3.6.1.2.1.2"],
            linux_snmp_agent_view_extra_oids=[".1.3.6.1.4.1.8072.1.3"],
        )
        self.assertEqual(
            re.findall(r"(?m)^view serviceradarRo (\S+) (\S+)$", config),
            [
                ("included", ".1.3.6.1.2.1.1"),
                ("included", ".1.3.6.1.2.1.2"),
                ("included", ".1.3.6.1.4.1.8072.1.3"),
                ("excluded", ".1.3.6.1.2.1.25.4.2.1.5"),
            ],
        )
        errors = evaluate("linux_snmp_agent_input_errors", linux_snmp_agent_view_extra_oids=[".1"])
        self.assertEqual(len(errors), 1)

    def test_the_systemd_filter_denies_everything_but_loopback_and_the_sources(self):
        unit = render("source-filter.conf.j2")
        self.assertEqual(
            [line for line in unit.splitlines() if not line.startswith("#")],
            [
                "[Service]",
                "IPAddressDeny=any",
                "IPAddressAllow=127.0.0.1/32",
                "IPAddressAllow=192.0.2.10/32",
                "IPAddressAllow=198.51.100.0/24",
            ],
        )

    def test_the_denied_probe_uses_a_loopback_address_outside_the_allow_list(self):
        client = render(
            "client-snmp.conf.j2",
            linux_snmp_agent_client_source=ROLE_VARS["linux_snmp_agent_denied_probe_source"],
        )
        self.assertIn("clientaddr 127.0.0.2\n", client)
        self.assertNotIn("127.0.0.2", render("source-filter.conf.j2"))
        self.assertEqual(render("client-snmp.conf.j2", linux_snmp_agent_client_anonymous=True).count("def"), 0)


class StoredUserTest(unittest.TestCase):
    def line_pattern(self, user):
        return evaluate("linux_snmp_agent_v3_user_line_pattern", linux_snmp_agent_v3_user=user)

    def test_both_net_snmp_encodings_of_the_user_name_are_matched(self):
        quoted = 'usmUser 1 3 0x80001f8880000000000000000000000000 "examplepoller" "examplepoller" NULL .1.3'
        hex_name = "0x" + USER.encode("ascii").hex()
        encoded = f"usmUser 1 3 0x80001f8880000000000000000000000000 {hex_name} {hex_name} NULL .1.3"
        self.assertRegex(quoted, self.line_pattern("examplepoller"))
        self.assertRegex(encoded, self.line_pattern(USER))
        self.assertNotRegex(encoded, self.line_pattern(USER[:-1]))
        self.assertNotRegex(encoded, self.line_pattern("examplepoller"))
        self.assertNotRegex(quoted, self.line_pattern("example"))
        self.assertNotRegex(quoted, self.line_pattern("otherpoller"))


class NoLogContractTest(unittest.TestCase):
    def test_every_task_that_touches_a_secret_is_not_logged(self):
        checked = 0
        for path, task in role_tasks():
            if any(section in task for section in ("block",)):
                continue
            text = yaml.safe_dump(task)
            touches_secret = any(name in text for name in SECRET_DERIVED) or any(
                template in text for template in SECRET_TEMPLATES
            )
            if not touches_secret:
                continue
            checked += 1
            with self.subTest(file=path.name, task=task.get("name")):
                self.assertIs(task.get("no_log"), True)
                if any(
                    module in task
                    for module in (
                        "ansible.builtin.template",
                        "ansible.builtin.copy",
                        "ansible.builtin.lineinfile",
                    )
                ):
                    self.assertIs(task.get("diff"), False)
                self.assertNotIn("loop", task)
        self.assertGreaterEqual(checked, 7)

    def test_the_local_queries_never_put_a_secret_on_a_command_line(self):
        for name in ("linux_snmp_agent_probe_argv",):
            self.assertFalse(any(secret in str(ROLE_VARS[name]) for secret in SECRET_DERIVED))
        for path, task in role_tasks():
            command = task.get("ansible.builtin.command")
            if command is not None:
                with self.subTest(file=path.name, task=task.get("name")):
                    self.assertFalse(any(secret in str(command) for secret in SECRET_DERIVED))
            self.assertNotIn("ansible.builtin.shell", task)

    def test_secret_arguments_are_declared_and_masked(self):
        for variable in SECRET_VARIABLES:
            self.assertEqual(ARGUMENT_SPEC[variable], {"type": "str", "no_log": True})


class ArgumentSpecTest(unittest.TestCase):
    def test_poller_sources_are_required_and_have_no_default(self):
        self.assertEqual(
            ARGUMENT_SPEC["linux_snmp_agent_poller_sources"],
            {"type": "list", "elements": "str", "required": True},
        )
        self.assertNotIn("linux_snmp_agent_poller_sources", DEFAULTS)

    def test_every_input_is_declared_with_a_type(self):
        self.assertEqual(set(ARGUMENT_SPEC), set(DEFAULTS) | {"linux_snmp_agent_poller_sources"})
        for name, option in ARGUMENT_SPEC.items():
            self.assertIn("type", option, name)
            if "default" in option:
                self.assertEqual(option["default"], DEFAULTS[name], name)

    def test_safe_defaults(self):
        self.assertEqual(DEFAULTS["linux_snmp_agent_mode"], "v3")
        self.assertEqual(DEFAULTS["linux_snmp_agent_state"], "present")
        self.assertEqual(ARGUMENT_SPEC["linux_snmp_agent_v3_auth_protocol"]["choices"], ["SHA-256", "SHA-384", "SHA-512"])
        self.assertEqual(ROLE_VARS["linux_snmp_agent_v3_priv_protocol"], "AES")
        self.assertIs(DEFAULTS["linux_snmp_agent_include_dropin_dir"], False)
        self.assertIs(DEFAULTS["linux_snmp_agent_systemd_ip_filter"], True)
        self.assertIs(DEFAULTS["linux_snmp_agent_remove_package"], False)

    def test_drop_ins_cannot_grant_access_or_open_a_transport(self):
        allowed = set(ROLE_VARS["linux_snmp_agent_dropin_allowed_directives"])
        forbidden = {
            "rocommunity", "rwcommunity", "rocommunity6", "rwcommunity6", "rouser", "rwuser",
            "com2sec", "com2sec6", "group", "access", "view", "authcommunity", "authuser",
            "authgroup", "authaccess", "createuser", "agentaddress", "includedir", "includefile",
            "includesearch", "master", "proxy", "trapsink", "trap2sink", "informsink", "trapsess",
            "agentuser", "agentgroup", "engineid", "dlmod", "perl",
        }
        self.assertEqual(allowed & forbidden, set())


if __name__ == "__main__":
    unittest.main()
