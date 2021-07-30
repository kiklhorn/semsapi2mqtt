# Last update:
Added multiple inverters capability, create full sensors set for every inverter and publish it as structuralized MQTT data.
Add all to mqtt HA discovery, with some translations posibility (name, units, maybe sensor device class...) - sensors in HA is created automaticaly.

Created sensor names form is - "name-sn" 
where 
- name is from api readings or from sensors_data_template dictionary if is there. (__init.py__)
- sn is last two chars from inverter serial number

Icons, units - from sensors_data_template too.

Some artifical values maybe I add later (charge,discharge in string form, total produced energy included actual day, etc...)

Minimal Python version - 3.9 (I think all 2021 HA vertsions +)

-------------------------------------------------------------------------------------------------------------------------------

# GoodWe SEMS Portal MQTT Component for Home Assistant
Home Assistant component for accessing the GoodWe SEMS Portal API.
Adapted from https://github.com/TimSoethout/goodwe-sems-home-assistant but altered to use the SEMS API.
API adaption by hesselonline, heavily inspired by https://github.com/markruys/gw2pvo.
Adapted furthermore by bouwew, using MQTT messages using HA-discovery to create separate sensors.

NOTE: this component requires an MQTT-broker to be present in your network.
There is one available in the Hassio Official Add-ons.

Installation of this component is done by copying the files `__init__.py` and `manifest.json` to the
`[homeassistant_config]/custom_components/sems2mqtt` folder.

In configuration.yaml add the custom_component as follows:
```
sems2mqtt:
  broker: 192.168.1.10          mqtt broker IP
  broker_user: username         mqtt broker login
  broker_pw: password1          mqtt broker password
  username: john.doe@gmail.com  sems login (full email-address*)
  password: password2           sems password
  station_id: your-station-ID   see remark below
  client: sems2mqtt             (optional, MQTT cient-id, default is 'sems2mqtt')
  scan_interval: 150            (optional, default is 300 seconds, keep to 300 seconds or less!)
```
* If you are using the SEMS Portal app on Android or IOS, it is strongly suggested to create a Visitor account with a different email address and use the credentials of the Visitor account for this custom_component. In the Adroid app, a visitor account can be added on the 'Modify Plant Info' page, scroll down to the bottom of the page to find the 'add visitor'-button.

This component use MQTT-disovery to find the sensors. The various parameters collected from the API will be shown as separate sensors, not as one sensor with several attributes. When you have performed the MQTT discovery, via Configuration --> Integrations --> configure the new MQTT-item on the top of the page (if you have other MQTT-integrations and the new sensors do not show up, delete the existing MQTT-integrations, restart HA and perform the MQTT-integration again), you will need to restart HA once more for the new sensors to show up.

<br>
Station ID can be found by logging on to the SEMS portal (part of URL after https://www.semsportal.com/PowerStation/PowerStatusSnMin/).

