$(function() {
    function UPSViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0]
        self.loginState = parameters[1];
        
        self.settings = undefined;

        self.ups_battery = $("#ups_battery");
        self.ups_battery_bar = $("#ups_battery_bar");
        self.ups_battery_status = $("#ups_battery_status");

        self.available_upses = ko.observableArray(undefined);

        self.vars = ko.observable({});

        self.vars.subscribe(function(newValue) {
            if (newValue.hasOwnProperty('ups.status')) {
                self.updateBatteryStatus(newValue["ups.status"]);
            }

            if (newValue.hasOwnProperty('battery.charge')) {
                self.updateBatteryBar(parseInt(newValue["battery.charge"]));
            } else {
                self.updateBatteryBar(0);
            }

        });

        self.updateBatteryBar = function(percent) {
            var color = "";

            self.ups_battery_bar.css("width", "calc(" + percent + "% * 0.73)");
            if (percent >= self.settings.plugins.ups.battery_high()) {
                color = "green";
            } else if (percent > self.settings.plugins.ups.battery_low() && percent < self.settings.plugins.ups.battery_high()) {
                color = "orange";
            } else if (percent <= self.settings.plugins.ups.battery_low()) {
                color = "red";
            }

            self.ups_battery_bar.css("background", color);
        };

        self.updateBatteryStatus = function(status) {
            flags = status.split(" ");

            icon = "";
            if (flags.includes("OFFLINE")) {
                icon = "fa-question";
            } else if (flags.includes("CHRG")) {
                icon = "fa-bolt";
            } else if (flags.includes("OL")) {
                icon = "fa-plug";
            } else if (flags.includes("OB")) {
                icon = "";
            } else if (flags.includes("RB")) {
                icon = "fa-exclamation-triangle";
            } else {
                icon = "";
            }

            self.ups_battery_status.attr("class", "fa fa-stack-1x " + icon);
        };

        self.popoverContent = ko.computed(function() {
            var content = "";

            content += `
                <table style="width: 100%;">
                <thead></thead>
                <tbody>
            `;

            if (self.vars().hasOwnProperty('ups.status')) {
                ups_status_flags = self.vars()["ups.status"].split(" ");
                status_text = "";
                if (ups_status_flags.includes("OFFLINE")) {
                    status_text = "Offline";
                } else if (ups_status_flags.includes("CHRG")) {
                    status_text = "Charging";
                } else if (ups_status_flags.includes("OL")) {
                    status_text = "Online";
                } else if (ups_status_flags.includes("OB")) {
                    status_text = "On Battery";
                } else if (ups_status_flags.includes("RB")) {
                    status_text = "Replace Battery";
                } else {
                    status_text = "Unknown";
                }
            } else {
                status_text = "Offline";
            }

            content += "<tr><td>Status</td><td>" + status_text + "</td></tr>"

            if (status_text != "Offline") {
                if (self.vars().hasOwnProperty('battery.charge')) {
                    content += "<tr><td>Charge</td><td>" + parseInt(self.vars()["battery.charge"]) + "%</td></tr>"
                }

                if (self.vars().hasOwnProperty('battery.runtime')) {
                    content += "<tr><td>Runtime</td><td>" + parseInt(self.vars()["battery.runtime"]) / 60 + " min</td></tr>"
                }
            }
/*
            Object.keys(self.vars()).forEach(function (k) {
                content += "<tr><td>" + k + "</td><td>" + self.vars()[k] + "</td></tr>";
            });
*/
            content += `
                </tbody>
                </table>
            `;

            return content;
        });

        self.updateUPSList = function () {
            $.ajax({
                url: API_BASEURL + "plugin/ups",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "listUPS",
                    host: self.settings.plugins.ups.host(),
                    port: self.settings.plugins.ups.port(),
                    auth: self.settings.plugins.ups.auth(),
                    username: self.settings.plugins.ups.username(),
                    password: self.settings.plugins.ups.password()
                }),
                contentType: "application/json; charset=UTF-8"
            }).done(function(data) {
                console.log(data);
                self.available_upses(data.result);
            }).fail(function(data) {
                console.warn("Failed fetching UPS list. Falling back to config value.");
                alert("Unable to fetch UPS list.");

                self.available_upses([self.settings.plugins.ups.ups()]);
            });
        };

        self.onBeforeBinding = function() {
            self.settings = self.settingsViewModel.settings;

            self.available_upses([self.settings.plugins.ups.ups()]);
        };

        self.onDataUpdaterPluginMessage = function(plugin, data) {
            if (plugin != "ups") {
                return;
            }

            if (data.vars !== undefined) {
                self.vars(data.vars);
            }
        };
    }

    ADDITIONAL_VIEWMODELS.push([
        UPSViewModel,
        ["settingsViewModel", "loginStateViewModel"],
        ["#navbar_plugin_ups", "#settings_plugin_ups"]
    ]);
});
