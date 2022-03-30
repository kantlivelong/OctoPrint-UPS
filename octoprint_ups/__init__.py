# coding=utf-8
from __future__ import absolute_import

__author__ = "Shawn Bruce <kantlivelong@gmail.com>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2021 Shawn Bruce - Released under terms of the AGPLv3 License"

import octoprint.plugin
from octoprint.events import Events
import time
import threading
from flask import make_response, jsonify
import nut2

try:
    from octoprint.access.permissions import Permissions
except Exception:
    from octoprint.server import user_permission

class UPS(octoprint.plugin.StartupPlugin,
          octoprint.plugin.TemplatePlugin,
          octoprint.plugin.AssetPlugin,
          octoprint.plugin.SettingsPlugin,
          octoprint.plugin.SimpleApiPlugin,
          octoprint.plugin.EventHandlerPlugin):

    def __init__(self):
        self.config = dict()
        self.ups = None
        self.vars = dict()

        self._pause_event = threading.Event()


    def get_settings_defaults(self):
        return dict(
            host = 'localhost',
            port = 3493,
            auth = False,
            username = '',
            password = '',
            ups = '',
            battery_high = 70,
            battery_low = 25,
            pause = False,
            pause_threshold = 50
        )


    def on_settings_initialized(self):
        self.reload_settings()


    def on_after_startup(self):
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()


    def reload_settings(self):
        for k, v in self.get_settings_defaults().items():
            if type(v) == str:
                v = self._settings.get([k])
            elif type(v) == int:
                v = self._settings.get_int([k])
            elif type(v) == float:
                v = self._settings.get_float([k])
            elif type(v) == bool:
                v = self._settings.get_boolean([k])

            self.config[k] = v
            self._logger.debug("{}: {}".format(k, v))


    def check_connection(self):
        if self.ups is None:
            self._logger.info("Connecting...")
        else:
            try:
                self.ups.ver()
                return True
            except (NameError, AttributeError):
                pass
            except (EOFError, BrokenPipeError, ConnectionAbortedError):
                self._logger.warning("Connection lost. Reconnecting...")

        try:
            self.ups = self.connect(self.config["host"], self.config["port"], self.config["auth"], self.config["username"], self.config["password"])
            self.ups.ver()
            self._logger.info("Connected!")
            return True
        except Exception:
            self._logger.error("Unable to connect")
            return False


    def connect(self, host, port, auth, username, password):
        if not auth or username == "":
            username = None

        if not auth or password == "":
            password = None

        return nut2.PyNUTClient(host=host, port=port, login=username, password=password)


    def _loop(self):
        logged_not_connected = False

        vars = dict()

        first_run = True
        while True:
            vars_prev = vars

            if first_run:
                first_run = False
            else:
                time.sleep(1)

            if not self.check_connection():
                if not logged_not_connected:
                    logged_not_connected = True

                self._plugin_manager.send_plugin_message(self._identifier, dict(vars={'ups.status': 'OFFLINE'}))
                continue
            else:
                if logged_not_connected:
                    logged_not_connected = False

            try:
                vars = self.ups.list_vars(ups=self.config['ups'])
            except nut2.PyNUTError as e:
                msg = str(e)
                if msg == "ERR DATA-STALE":
                    # Basically seems like an unable to fetch / refresh data error.
                    self._plugin_manager.send_plugin_message(self._identifier, dict(vars={'ups.status': 'OFFLINE'}))
                    self._logger.warning(msg)
                    continue
                elif msg == "ERR DRIVER-NOT-CONNECTED":
                    # Occurs when nut-driver is not running.
                    self._plugin_manager.send_plugin_message(self._identifier, dict(vars={'ups.status': 'OFFLINE'}))
                    self._logger.warning(msg)
                    continue
                else:
                    self._logger.exception("A PyNUTError exception occurred while getting vars info")
            except Exception:
                self._logger.exception("An exception occurred while getting vars info")
                continue

            self._logger.debug(vars)

            status_flags = vars.get('ups.status', "").split(" ")
            status_flags_prev = vars_prev.get('ups.status', "").split(" ")

            ob = "OB" in status_flags
            ob_prev = "OB" in status_flags_prev

            if ob:
                if not ob_prev:
                    self._logger.info("Power lost. Running on battery.")

                if (not ob_prev or
                    vars.get('battery.charge') != vars_prev.get('battery.charge')):
                    self._logger.info("Battery remaining {}%".format(vars['battery.charge']))

                    if (self.config["pause"] and
                        self._printer.is_printing() and
                        float(vars.get('battery.charge')) < self.config["pause_threshold"] and
                        not (self._printer.is_paused() or self._printer.is_pausing())):

                        self._logger.info("Battery below threshold. Pausing job.")

                        self._pause_event.set()

                        tags = {"source:plugin", "plugin:ups"}
                        self._printer.pause_print(tag=tags)
            elif ob_prev:
                    self._logger.info("Power restored.")

            if vars.get('ups.status') != self.vars.get('ups.status'):
                event = Events.PLUGIN_UPS_STATUS_CHANGED
                self._event_bus.fire(event, payload=dict(vars=vars))

            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=vars))
            self.vars = vars


    def _hook_comm_protocol_scripts(self, comm_instance, script_type, script_name, *args, **kwargs):
        if not script_type == "gcode":
            return None

        if script_name in ['afterPrintPaused', 'beforePrintResumed']:
            d = dict(initiated_pause=self._pause_event.is_set())
        else:
            return None

        if script_name == "beforePrintResumed":
            self._pause_event.clear()

        return (None, None, d)


    def on_event(self, event, payload):
        if event == Events.CLIENT_OPENED:
            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=self.vars))
            return


    def get_api_commands(self):
        return dict(
            getUPSVars=[],
            listUPS=['host', 'port', 'auth', 'username', 'password']
        )


    def on_api_get(self, request):
        return self.on_api_command("getUPSVars", [])


    def on_api_command(self, command, data):
        if command in ['getUPSVars', 'listUPS']:
            try:
                if not Permissions.STATUS.can():
                    return make_response("Insufficient rights", 403)
            except:
                if not user_permission.can():
                    return make_response("Insufficient rights", 403)

        if command == 'getUPSVars':
            return jsonify(vars=self.vars)
        elif command == 'listUPS':
            try:
                ups = self.connect(host=str(data['host']), port=int(data['port']),
                                   auth=data["auth"], username=data["username"], password=data["password"])
                res = ups.list_ups()
                return jsonify(result=list(res.keys()))
            except:
                return make_response("Error getting UPS list", 500)


    def on_settings_save(self, data):
        old_config = self.config.copy()

        if ((data.get('host') and data['host'] != old_config['host']) or
            (data.get('port') and data['host'] != old_config['host']) or
            (data.get('auth') and data['auth'] != old_config['auth']) or
            (data.get('username') and data['username'] != old_config['username']) or
            (data.get('password') and data['password'] != old_config['password']) or
            (data.get('ups') and data['ups'] != old_config['ups'])):
            self._logger.info("Connection information changed.")
            self.ups = None

        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()


    def get_settings_version(self):
        return 1


    def on_settings_migrate(self, target, current=None):
        if current is None:
            current = 0


    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True)
        ]


    def get_assets(self):
        return {
            "js": ["js/ups.js"],
            "less": ["less/ups.less"],
            "css": ["css/ups.min.css"]
        } 


    def get_update_information(self):
        return dict(
            ups=dict(
                displayName="UPS",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="kantlivelong",
                repo="OctoPrint-UPS",
                current=self._plugin_version,

                # update method: pip w/ dependency links
                pip="https://github.com/kantlivelong/OctoPrint-UPS/archive/{target_version}.zip"
            )
        )


    def _hook_events_register_custom_events(self):
        return ["status_changed"]


__plugin_name__ = "UPS"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = UPS()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.events.register_custom_events": __plugin_implementation__._hook_events_register_custom_events,
        "octoprint.comm.protocol.scripts": __plugin_implementation__._hook_comm_protocol_scripts
    }
