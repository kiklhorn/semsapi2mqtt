""""
Home Assistant component for accessing the GoodWe SEMS Portal API.
    Based on https://github.com/bouwew/sems2mqtt, add multiple inverters, multiple sensors, rework mqtt structure.
    Adapted from https://github.com/TimSoethout/goodwe-sems-home-assistant, but altered to use the SEMS API.
    API adaption by hesselonline, heavily inspired by https://github.com/markruys/gw2pvo.
    Adapted furthermore using MQTT messages using HA-discovery to create separate sensors.

Configuration (example):

sems2mqtt:
  broker: mqtt broker IP
  broker_user: mqtt broker login
  broker_pw: mqtt broker password
  username: sems login (email)
  password: sems password
  station_id: your station ID
  client: MQTT cient-id (optional, default is 'semsapi2mqtt')
  mqtt_prefix: Elektrarna # (optional, default is powerplant) mqtt topic root - can be start/other/next
  sn_inverters: True # (optional, default is True) create mqtt inverters topics by its serial numbers
  count_inverters: False # (optional, default is False) create mqtt inverters topics by its index
  scan_interval: 150 (optional, default is 300 seconds, keep to 300 seconds or less!)
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
import requests
import logging
import voluptuous as vol
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

CONF_BROKER = "broker"
CONF_BROKER_USERNAME = "broker_user"
CONF_BROKER_PASSWORD = "broker_pw"
CONF_COUNT_INVERTERS = "count_inverters"
CONF_SN_INVERTERS = "sn_inverters"
CONF_STATION_ID = "station_id"
CONF_CLIENT = "client"
CONF_MQTT_PREFIX = "mqtt_prefix"

DEFAULT_CL = "semsapi2mqtt"
DOMAIN = "semsapi2mqtt"
REGISTERED = 0
SCAN_INTERVAL = timedelta(seconds=300)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_BROKER): cv.string,
                vol.Required(CONF_BROKER_USERNAME): cv.string,
                vol.Required(CONF_BROKER_PASSWORD): cv.string,
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_STATION_ID): cv.string,
                vol.Optional(CONF_CLIENT, default=DEFAULT_CL): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL): cv.time_period,
                vol.Optional(CONF_COUNT_INVERTERS, default=False): cv.boolean,
                vol.Optional(CONF_SN_INVERTERS, default=True): cv.boolean,
                vol.Optional(CONF_COUNT_INVERTERS, default=False): cv.boolean,
                vol.Optional(CONF_MQTT_PREFIX, default="powerplant"): cv.string,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

# bellow are parameters from invertor. When provide name, icon, units - then is used to display on lovelace
# add next yourself if need other
sensors_data_template = {
    "model_type": {"name": "inverter_type", "icon": "mdi:solar-power"},
    "status": {"name": "inverter_status", "icon": "mdi:lan-connect"},
    "pac": {"name": "solar_power", "icon": "mdi:solar-power", "unit_of_meas": "W"},
    "tempperature": {
        "name": "temperature",
        "icon": "mdi:solar-power",
        "unit_of_meas": "°C",
    },
    "eday": {"name": "sems_produced_today", "icon": "mdi:flash", "unit_of_meas": "kWh"},
    "etotal": {
        "name": "sems_produced_total",
        "icon": "mdi:flash",
        "unit_of_meas": "kWh",
    },
    "thismonthetotle": {
        "name": "sems_produced_this_month",
        "icon": "mdi:flash",
        "unit_of_meas": "kWh",
    },
    "vac1": {"name": "grid_voltage", "icon": "mdi:current-ac", "unit_of_meas": "V AC"},
    "iac1": {"name": "grid_current", "icon": "mdi:current-ac", "unit_of_meas": "A AC"},
    "fac1": {
        "name": "grid_frequency",
        "icon": "mdi:current-ac",
        "unit_of_meas": "Hz",
    },
    "vpv1": {
        "name": "string1_voltage",
        "icon": "mdi:current-dc",
        "unit_of_meas": "V DC",
    },
    "ipv1": {
        "name": "string1_current",
        "icon": "mdi:current-dc",
        "unit_of_meas": "A DC",
    },
    "vpv2": {
        "name": "string2_voltage",
        "icon": "mdi:current-dc",
        "unit_of_meas": "V DC",
    },
    "ipv2": {
        "name": "string2_current",
        "icon": "mdi:current-dc",
        "unit_of_meas": "A DC",
    },
    "soc": {"icon": "mdi:battery-charging", "unit_of_meas": "%"},
    "soh": {"icon": "mdi:medical-bag", "unit_of_meas": "%"},
}


async def async_setup(hass, config):
    """Initialize the SEMS MQTT consumer"""
    conf = config[DOMAIN]
    broker = conf.get(CONF_BROKER)
    broker_user = conf.get(CONF_BROKER_USERNAME)
    broker_pw = conf.get(CONF_BROKER_PASSWORD)
    username = conf.get(CONF_USERNAME)
    password = conf.get(CONF_PASSWORD)
    station_id = conf.get(CONF_STATION_ID)
    client = conf.get(CONF_CLIENT)
    scan_interval = conf.get(CONF_SCAN_INTERVAL)
    count_inverters = conf.get(CONF_COUNT_INVERTERS)
    sn_inverters = conf.get(CONF_SN_INVERTERS)
    mqtt_prefix = conf.get(CONF_MQTT_PREFIX)

    auth = {"username": broker_user, "password": broker_pw}
    port = 1883
    # keepalive = 300

    def issue_pub_multiple(msgs, broker, port, auth, client):
        """Helper function for publish.multi."""
        return publish.multiple(
            msgs,
            hostname=broker,
            port=port,
            auth=auth,
            client_id=client,
            protocol=mqtt.MQTTv31,
        )

    async def async_get_sems_data(event_time):
        """Get the topics from the SEMS API and send the corresponding sensor-data to the MQTT Broker."""

        async def getCurrentReadings(station_id):
            """Download the most recent readings from the GoodWe API."""
            status = {-1: "Offline", 0: "Waiting", 1: "Online"}
            payload = {"powerStationId": station_id}
            stationData = await call(
                "v2/PowerStation/GetMonitorDetailByPowerstationId",
                payload,
            )
            inverters = stationData["inverter"]
            data = {}
            count = 0
            for inverter in inverters:
                if sn_inverters:
                    sn = inverter["invert_full"]["sn"]
                    data[sn] = inverter["invert_full"]
                if count_inverters:
                    data[count] = inverter["invert_full"]
                    count += 1
            return data

        def issuePost(url, headers, payload, timeout):
            """Helper function for request.post()."""
            return requests.post(url, headers=headers, data=payload, timeout=timeout)

        def issueException():
            """Helper function for requests.exceptions."""
            return requests.exceptions.RequestException

        async def call(url, payload):
            token = '{"version":"","client":"web","language":"en"}'
            global_url = "https://eu.semsportal.com/api/"
            base_url = global_url
            for i in range(1, 4):
                try:
                    headers = {"Token": token}
                    r = await hass.async_add_executor_job(
                        issuePost,
                        base_url + url,
                        headers,
                        payload,
                        20,
                    )
                    r.raise_for_status()
                    data = r.json()
                    _LOGGER.debug(data)
                    if data["msg"] == "success" and data["data"] is not None:
                        return data["data"]
                    else:
                        loginPayload = {"account": account, "pwd": password}
                        r = await hass.async_add_executor_job(
                            issuePost,
                            global_url + "v2/Common/CrossLogin",
                            headers,
                            loginPayload,
                            20,
                        )
                        r.raise_for_status()
                        data = r.json()
                        base_url = data["api"]
                        token = json.dumps(data["data"])
                except await hass.async_add_executor_job(issueException) as exp:
                    _LOGGER.warning(exp)
                time.sleep((2 * i) ** 2)
            else:
                _LOGGER.error("Failed to obtain data from the SEMS API")
                return {}

        def create_device(model, snumber="test"):
            return {
                "identifiers": snumber,
                "name": "GoodWe Inverter",
                "model": model,
                "manufacturer": "GoodWe",
            }

        def create_conf(model, snumber, state_topic, parameter_name):
            unique_id = (
                "solar_inverter"
                + str(model)
                + "_"
                + str(snumber)
                + "_"
                + str(parameter_name)
                + "_sensor"
            )
            # translator - if exist in sensor_data_template dict - translate/humanize its name and merge options
            if parameter_name in sensors_data_template:
                sensorname = sensors_data_template.get(parameter_name, {}).get(
                    "name", parameter_name
                )
                options = sensors_data_template[parameter_name]
            else:
                sensorname = parameter_name
                options = None
            payload = {
                "name": sensorname + "-" + str(snumber[-2:]),
                "state_topic": state_topic,
                "unique_id": unique_id,
                "device": create_device(model, snumber),
            }
            if options:
                payload = options | payload #add all from options, but sensor name from payload 
            return (
                "homeassistant/sensor/" + unique_id + "/config",
                json.dumps(payload),
                0,
                True,
            )

        # body of async_get_sems_data()
        global REGISTERED
        try:
            account = username
            station = station_id

            data = await getCurrentReadings(station)
            # Return full_invert data for all inverters
            # data[sn or index or both for inverters][full data inverter set]
            msgs = []
            for inverter_sn_or_index in data:
                for parameter_name in data[inverter_sn_or_index]:
                    state_topic = str(
                        mqtt_prefix
                        + "/inverter/"
                        + str(inverter_sn_or_index)
                        + "/"
                        + str(parameter_name)
                    )
                    msg = (
                        state_topic,
                        data[inverter_sn_or_index][
                            parameter_name
                        ],  # value of parameter
                        0,  # QOS
                        True,  # Retain
                    )

                    if not REGISTERED:
                        regmsg = create_conf(
                            data[inverter_sn_or_index]["model_type"],
                            inverter_sn_or_index,
                            state_topic,
                            parameter_name,
                        )
                        msgs.append(regmsg)
                    msgs.append(msg)

        except Exception as exception:
            _LOGGER.error(
                "Unable to fetch data from the SEMS API,"
                + str(exception)
                + "not available"
            )
        else:
            await hass.async_add_executor_job(
                issue_pub_multiple,
                msgs,
                broker,
                port,
                auth,
                client,
            )
            REGISTERED = 1

    async_track_time_interval(hass, async_get_sems_data, scan_interval)

    return True
