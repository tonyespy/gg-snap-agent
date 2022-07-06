"""
This is a PoC of a Greengrass v2 snapd device-agent. It supports the same MQTT based
message format as the reference device-agent:

https://github.com/canonical/iot-agent

--------------------------------------------------------------------------------
TODO:
 - [device] figure out enrollment (i.e. howto set enroll.ID and enroll.Organization.Id)
 - [list] implement 'config' (i.e. call snapd config endpoint for each snap)
 - [install] implement
 - [refresh] implement
 - [*] break into separate python modules
 - [*] pub/sub on device-specific topics

"""
import json
import logging
import os
import requests_unixsocket
import sys
import time
import traceback

import awsiot.greengrasscoreipc
import awsiot.greengrasscoreipc.client as client
from awsiot.greengrasscoreipc.model import (
    IoTCoreMessage,
    PublishToIoTCoreRequest,
    QOS,
    SubscribeToIoTCoreRequest
)

"""
// SubscribeAction is the message format for the action topic
type SubscribeAction struct {
        ID     string `json:"id"`
        Action string `json:"action"`
	Snap   string `json:"snap"`
        Data   string `json:"data"`
}

// PublishResponse is the published message showing the result of an action
type PublishResponse struct {
        ID      string      `json:"id"`
        Action  string      `json:"action"`
        Success bool        `json:"success"`
        Message string      `json:"message"`
        Result  interface{} `json:"result"`
}
"""

TIMEOUT = 10
ipc_client = awsiot.greengrasscoreipc.connect()
def serial_from_response(response):
    res = []
    for sub in response.split("\n"):
        if ':' in sub:
            res.append(map(str.strip, sub.split(":", 1)))
    res = dict(res)
    return res

def store_id_from_response(response):
    res = []
    for sub in response.split("\n"):
        if ':' in sub:
            res.append(map(str.strip, sub.split(":", 1)))
    res = dict(res)
    store_id = res.get('store', "")
    if store_id == "":
        store_id = "global"
    return store_id

def snapd_version_from_response(response):
    sys_json = json.loads(response)
    result = sys_json['result']
    version = result['version']
    return version

def snaps_from_response(response):
    snaps_json = json.loads(response)
    snaps = snaps_json['result']
    return snaps

"""
// Device holds the details of a device
type Device struct {
	OrganizationID string        `json:"orgId"`
	DeviceID       string        `json:"deviceId"`
	Brand          string        `json:"brand"`
	Model          string        `json:"model"`
	SerialNumber   string        `json:"serial"`
	StoreID        string        `json:"store"`
	DeviceKey      string        `json:"deviceKey"`
	Version        DeviceVersion `json:"version"`
	Created        time.Time     `json:"created"`
	LastRefresh    time.Time     `json:"lastRefresh"`
}
"""
def device_action(id):
    logging.info("device_action called for id:" + id)

    session = requests_unixsocket.Session()
    rsp = session.get("http+unix://%2Frun%2Fsnapd.socket/v2/assertions/model")
    if rsp.status_code == 200:
        # The response is a stream of assertions separated by double newlines.
        # The X-Ubuntu-Assertions-Count header is set to the number of returned
        # assertions, 0 or more. If more than one model assertion is returned,
        # this code uses information from the first.
        store_id = store_id_from_response(rsp.text)
    else:
        logging.error("REST call to snapd /v2/assertions/model failed; status: " + rsp.status_code + "reason: " + rsp.reason)

    logging.info("device_action getting serial assertion")
    rsp = session.get("http+unix://%2Frun%2Fsnapd.socket/v2/assertions/serial")
    if rsp.status_code == 200:
        # The response is a stream of assertions separated by double newlines.
        # The X-Ubuntu-Assertions-Count header is set to the number of returned
        # assertions, 0 or more. If more than one model assertion is returned,
        # this code uses information from the first.
        serial = serial_from_response(rsp.text)
        logging.info("device_action got serial assertion")
    else:
        logging.error("REST call to snapd /v2/assertions/model failed; status: " + rsp.status_code + "reason: " + rsp.reason)

    version = ""
    rsp = session.get("http+unix://%2Frun%2Fsnapd.socket/v2/system-info")
    if rsp.status_code == 200:
        version = snapd_version_from_response(rsp.text)
        logging.info("device_action got snapd version:" + version)
    else:
        logging.error("REST call to snapd /v2/assertions/system-info failed; status: " + rsp.status_code + "reason: " + rsp.reason)

    logging.info("device_action building response...")

    result = { }
    result['orgId'] = "<enroll.Organization.ID>"
    # should deviceId just be the thing's arn? This
    # won't work for the topic though, perhaps just
    # use the number after the region?
    # arn:aws:iot:us-east-1:084305837490:thing/mything
    result['deviceId'] = "<enroll.ID>"
    result['brand'] = serial['brand-id']
    result['model'] = serial['model']
    result['serial'] = serial['serial']
    result['store'] = store_id
    # FIXME: device-key isn't parsed properly because
    # there's a \n after the header name, and this code
    # isn't using a formal YAML parser
    result['device-key'] = serial['device-key']
    result['version'] = version

    reply = { }
    reply['id'] = id
    reply['action'] = "device"
    reply['success'] = True
    reply['result'] = result

    return reply

"""
// DeviceSnap holds the details of snap on a device
type DeviceSnap struct {
        DeviceID      string    `json:"deviceId"`
        Name          string    `json:"name"`
        InstalledSize int64     `json:"installedSize"`
        InstalledDate time.Time `json:"installedDate"`
        Status        string    `json:"status"`
        Channel       string    `json:"channel"`
        Confinement   string    `json:"confinement"`
        Version       string    `json:"version"`
        Revision      int       `json:"revision"`
        Devmode       bool      `json:"devmode"`
	Config        string    `json:"config"`
}
"""
def list_action(id):
    logging.info("list_action called for id:" + id)

    session = requests_unixsocket.Session()
    rsp = session.get("http+unix://%2Frun%2Fsnapd.socket/v2/snaps")
    if rsp.status_code == 200:
        result = snaps_from_response(rsp.text)
        num_snaps = len(result)
        snap_list = [dict() for x in range(num_snaps)]
        index = 0

        logging.info("list_action NUM_SNAPS:" + str(num_snaps))

        for i in range (0, num_snaps):
            snap_list[i]['deviceId'] = "<enroll.ID>"
            snap_list[i]['name'] = result[i]['name']
            snap_list[i]['installedSize'] = result[i]['installed-size']
            snap_list[i]['installedDate'] = result[i]['install-date']
            snap_list[i]['status'] = result[i]['status']
            snap_list[i]['channel'] = result[i]['channel']
            snap_list[i]['confinement'] = result[i]['confinement']
            snap_list[i]['version'] = result[i]['version']
            snap_list[i]['revision'] = result[i]['revision']
            snap_list[i]['devmode'] = result[i]['devmode']
            snap_list[i]['config'] = "not supported"

    reply = { }
    reply['id'] = id
    reply['action'] = "list"
    reply['success'] = True
    reply['result'] = snap_list

    return reply

class StreamHandler(client.SubscribeToIoTCoreStreamHandler):
    def __init__(self):
        super().__init__()

    def on_stream_event(self, event: IoTCoreMessage) -> None:
        try:
            message = str(event.message.payload, "utf-8")
            topic_name = event.message.topic_name
            # Handle message.
            logging.info("An incoming message was received from AWS IoT Core; topic: " + topic_name)

            subs_action = json.loads(message)
            id = subs_action['id']
            action = subs_action['action']
            logging.info("message id:" + id + " action: " + action)

            if action == "device":
                reply = device_action(id)
            elif action == "list":
                reply = list_action(id)
            elif action == "install":
                logging.error("install NOT SUPPORTED!")
            elif action == "refresh":
                logging.error("refresh NOT SUPPORTED!")
            elif action == "remove":
                logging.error("remove NOT SUPPORTED!")
            elif action == "revert":
                logging.error("revert NOT SUPPORTED!")
            elif action == "enable":
                logging.error("enable NOT SUPPORTED!")
            elif action == "disable":
                logging.error("disable NOT SUPPORTED!")
            elif action == "conf":
                logging.error("conf NOT SUPPORTED!")
            elif action == "setconf":
                logging.error("setconf NOT SUPPORTED!")
            elif action == "info":
                logging.error("info NOT SUPPORTED!")
            elif action == "ack":
                logging.error("info NOT SUPPORTED!")
            elif action == "server":
                logging.error("server NOT SUPPORTED!")
            else:
                logging.error("message action: " + action + " NOT RECOGNIZED!")

            logging.info("on_stream_event: sending reply...")
            reply_json = json.dumps(reply)
            response = PublishToIoTCoreRequest()
            response.topic_name = response_topic
            response.payload = bytes(reply_json, "utf-8")
            response.qos = qos
            response_op = ipc_client.new_publish_to_iot_core()
            response_op.activate(response)

        except:
            traceback.print_exc()
            logging.error("on_stream_event: exception thrown...")

    def on_stream_error(self, error: Exception) -> bool:
        # Handle error.
        logging.error("mqtt.py: on_stream_error called: " + error)
        return True  # Return True to close stream, False to keep stream open.

    def on_stream_closed(self) -> None:
        # Handle close.
        logging.error("mqtt.py: on_stream_closed called")
        pass


logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
logging.info("mqtt.py: started")

# TODO: these topics should be appended with client/deviceID
action_topic = "mydevices/actions"
response_topic = "mydevices/responses"
qos = QOS.AT_MOST_ONCE

snap_common = os.environ['SNAP_COMMON']
path = snap_common + "/device-agent-component.env"
logging.info("mqtt.py: writing env to: " + path)
fd = open(path, "w")
for k, v in os.environ.items():
   fd.write(k + "=" + v + "\n")
fd.close()

request = SubscribeToIoTCoreRequest()
request.topic_name = action_topic
request.qos = qos
handler = StreamHandler()
operation = ipc_client.new_subscribe_to_iot_core(handler)
future = operation.activate(request)
future.result(TIMEOUT)

# Keep the main thread alive, or the process will exit.
while True:
    time.sleep(10)

# To stop subscribing, close the operation stream.
operation.close()
