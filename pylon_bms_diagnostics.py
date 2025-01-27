#!/usr/bin/env python3
"""
Diagnostics and MQTT bridge for Battery BMS using Pylontech CAN Bus Protocol

By default, listens passively an the bus using (virtual) interface vcan0.
Other CAN interfaces are can be specified using the first positional parameter.

BMS data is pushed to MQTT using the specified topic (tele/bms) in JSON format.

If the --poll option is given, this emulates a connected inverter and
periodically sends out a request frame to trigger the BMS reply.


Version 0.1.2  2025-01-27  Ulrich Lukas
"""
import argparse
import logging
import time
import threading
import json
import can
import paho.mqtt.client as mqtt
from dataclasses import dataclass, asdict
from pipyadc.utils import TextScreen

PROGNAME: str = "pylon_bms_diagnostics.py"

CAN_DEVICE_DEFAULT: str = "vcan0"
MQTT_TOPIC_DEFAULT: str = "tele/bms"
MQTT_BROKER_DEFAULT: str = "localhost"
MQTT_PORT: int = 1883

# Number of CAN frames belonging to one reply data telegram from the BMS
N_BMS_REPLY_FRAMES: int = 6
# CAN ID which marks the start of the data telegram sent from the BMS
ID_BMS_TELEGRAM_START: int = 0x359
# CAN ID which is sent by the inverter to poll the BMS (using 8x 0x00 data)
ID_INVERTER_REQUEST: int = 0x305

parser = argparse.ArgumentParser(prog=PROGNAME, description=__doc__)
parser.add_argument("--poll", type=float, nargs="?", const=1.0,
                    help="Send request frame every n seconds. Default: 1")
parser.add_argument("ifname", type=str, nargs="?", default=CAN_DEVICE_DEFAULT,
                    help="CAN interface to use. Default: vcan0")
parser.add_argument("--push", action="store_true", 
                    help="Push incoming BMS telegrams to MQTT")
parser.add_argument("-t", "--topic", type=str, default=MQTT_TOPIC_DEFAULT,
                    help="MQTT topic to push to. Default: tele/bms")
parser.add_argument("-b", "--broker", type=str, default=MQTT_BROKER_DEFAULT,
                    help="MQTT host (broker) to push to. Default: localhost")
parser.add_argument("-s", "--silent", action="store_true",
                    help="Suppress screen text output")
parser.add_argument("-ss", "--super-silent", action="store_true",
                    help="Suppress text output. Also suppress warnings")

args = parser.parse_args()

logger = logging.Logger(PROGNAME)
logger.setLevel(logging.ERROR if args.super_silent else logging.WARNING)

# Double-Buffered Text Output
screen = TextScreen()


@dataclass
class BmsState:
    """This represents the BMS state as received on the CAN bus"""
    timestamp_last_bms_update: float = 0.0
    timestamp_last_inverter_request: float = 0.0
    n_invalid_data_telegrams: int = 0
    manufacturer: str = ""
    soc: int = 0
    soh: int = 0
    v_charge_cmd: float = 0.0
    i_lim_charge: float = 0.0
    i_lim_discharge: float = 0.0
    v_avg: float = 0.00
    i_total: float = 0.0
    t_avg: float = 0.0
    error_state: bool = True
    warning_state: bool = True
    n_modules: int = 0
    charge_enable: bool = False
    discharge_enable: bool = False
    force_charge_request: bool = False
    force_charge_request_low: bool = False
    balancing_charge_request: bool = False

# Object holding the received BMS state
state = BmsState()

# Periodically sends inverter request/reply frames to the BMS
def fn_thread_poll_bms(interval):
    next_call = time.time()
    while not threads_stop.is_set():
        with can.Bus(args.ifname, "socketcan") as bus:
            msg = can.Message(arbitration_id=ID_INVERTER_REQUEST,
                              data=b"\x00" * 8,
                              is_extended_id=False)
            bus.send(msg)
        next_call += interval
        time.sleep(next_call - time.time())


# Push state to MQTT broker
if args.push:
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.connect(args.broker, MQTT_PORT, 60)
    # This starts a background thread
    mqttc.loop_start()


evenrun: bool = False
def do_text_output():
    global evenrun
    screen.put(f"""\n\n\n\n\n
    BMS manufacturer string: {state.manufacturer}
    Number of modules: {state.n_modules}
    
    SOC: {state.soc}
    SOH: {state.soh}
    
    Requested Charging Voltage: {state.v_charge_cmd:.1f}
    Charge Current Limit: {state.i_lim_charge:.1f}
    Discharge Current Limit: {state.i_lim_discharge:.1f}
    
    System Current: {state.i_total:.1f}
    System Voltage (Average): {state.v_avg:.2f}
    System Temperature (Average): {state.t_avg:.1f}
    
    Errors: {state.error_state}
    Warnings: {state.warning_state}
    
    Charge Enable: {state.charge_enable}
    Discharge Enable: {state.discharge_enable}
    
    Force Charge: {state.force_charge_request}
    Force Charge Low Battery: {state.force_charge_request_low}
    Balancing Charge Request: {state.balancing_charge_request}
    {'**********************************************' if evenrun else ''}
    """)
    if args.push:
        screen.put(f"    MQTT connected: {mqttc.is_connected()}")
    screen.refresh()
    evenrun = not evenrun


def bms_decode(frames):
    try:
        # CAN ID 0x351
        state.v_charge_cmd = 0.1 * int.from_bytes(frames[0x351][0:2], "little")
        state.i_lim_charge = 0.1 * int.from_bytes(frames[0x351][2:4], "little", signed=True)
        state.i_lim_discharge = 0.1 * int.from_bytes(frames[0x351][4:6], "little", signed=True)
        # CAN ID 0x355
        state.soc = int.from_bytes(frames[0x355][0:2], "little")
        state.soh = int.from_bytes(frames[0x355][2:4], "little")
        # CAN ID 0x356
        state.v_avg = 0.01 * int.from_bytes(frames[0x356][0:2], "little", signed=True)
        state.i_total = 0.1 * int.from_bytes(frames[0x356][2:4], "little", signed=True)
        state.t_avg = 0.1 * int.from_bytes(frames[0x356][4:6], "little", signed=True)
        # CAN ID 0x359
        state.error_state = bool(frames[0x359][0] or frames[0x359][1])
        state.warning_state = bool(frames[0x359][2] or frames[0x359][3])
        state.n_modules = frames[0x359][4]
        # CAN ID 0x35C
        state.charge_enable = bool(frames[0x35C][0] & 1<<7)
        state.discharge_enable = bool(frames[0x35C][0] & 1<<6)
        state.force_charge_request = bool(frames[0x35C][0] & 1<<5)
        state.force_charge_request_low = bool(frames[0x35C][0] & 1<<4)
        state.balancing_charge_request = bool(frames[0x35C][0] & 1<<3)
        # CAN ID 0x35E
        state.manufacturer: str = frames[0x35E].decode().rstrip("\x00")
    # Operator "<=" tests if left set is a subset of the set on the right side
    #if not {0x351, 0x355, 0x356, 0x359, 0x35C, 0x35E} <= frames.keys():
    except KeyError as e:
        logger.warning(f"Incomplete set of data frames received. ID: {hex(e.args[0])}")
        state.n_invalid_data_telegrams += 1
        return
    except (IndexError, ValueError, UnicodeDecodeError) as e:
        logger.warning(f"Invalid data received. Details: {e.args[0]}")
        state.n_invalid_data_telegrams += 1
        return
    state.timestamp_last_bms_update = time.time()
    if args.push:
        # Faster but does not behave as dataclass is intended to behave
        # mqttc.publish(args.topic, json.dumps(vars(state)))
        mqttc.publish(args.topic, json.dumps(asdict(state)))
    if not (args.silent or args.super_silent):
        do_text_output()


def receive_data_loop():
    bms_reply_frames: dict = {}
    framecounter: int = 0
    with can.Bus(args.ifname, "socketcan") as bus:
        # This is an endless loop reading the CAN bus.
        for frame in bus:
            # Fill in BMS reply frames into dictionary
            bms_reply_frames[frame.arbitration_id] = frame.data
            # Inverter request or acknowledge is inverleaved with BMS reply.
            # The inverter frame contains no data and only timestamp is logged
            if frame.arbitration_id == ID_INVERTER_REQUEST:
                state.timestamp_last_inverter_request = time.time()
            elif frame.arbitration_id == ID_BMS_TELEGRAM_START:
                if framecounter >= N_BMS_REPLY_FRAMES:
                    bms_decode(bms_reply_frames)
                framecounter = 1
            else:
                framecounter += 1


thread_poll_bms = None
# Terminate running background threads if this is set
threads_stop = threading.Event()

# If specified on the command line, start sending out request frames periodically
if args.poll is not None:
    if args.poll < 0.2:
        raise argparse.ArgumentError("Poll interval must be larger than 0.2 s")
    thread_poll_bms = threading.Thread(
        target=fn_thread_poll_bms,
        args=(args.poll, )
        )
    thread_poll_bms.start()


try:
    receive_data_loop()
except KeyboardInterrupt:
    pass
finally:
    if args.push:
        mqttc.loop_stop()
    threads_stop.set()
    if thread_poll_bms is not None:
        thread_poll_bms.join()
