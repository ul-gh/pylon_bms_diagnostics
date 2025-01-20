# Pylon BMS Diagnostics
## Diagnostics tool and MQTT bridge for Pylontech BMS protocol
This command-line tool decodes and displays the CAN frames sent by Li-Ion battery management systems using the Pylontech BMS protocol.

Default mode of operation is to intercept the communication between the battery BMS and a connected inverter.

When the --poll command line option is given, the tool can be used stand-alone without a connected inverter.

When the --push option is given, the BMS state is continuously pushed to an MQTT broker.

```
usage: pylon_bms_diagnostics.py [-h] [--poll [POLL]] [--push] [-t TOPIC] [-b BROKER] [-s] [ifname]

positional arguments:
  ifname                CAN interface to use

optional arguments:
  -h, --help            show this help message and exit
  --poll [POLL]         Send out request frame every n seconds
  --push                Push incoming BMS telegrams to MQTT
  -t TOPIC, --topic TOPIC
                        MQTT topic to push to
  -b BROKER, --broker BROKER
                        MQTT host (broker) to push to
  -s, --silent          Suppress screen text output
```

Example output:
```
    BMS manufacturer string: PYLON
    Number of modules: 5
    
    SOC: 82
    SOH: 100
    
    Requested Charging Voltage: 56.3
    Charge Current Limit: 922.5
    Discharge Current Limit: 922.5
    
    System Current: 9.6
    System Voltage (Average): 53.41
    System Temperature (Average): 15.2
    
    Errors: False
    Warnings: False
    
    Charge Enable: True
    Discharge Enable: True
    
    Force Charge: False
    Force Charge Low Battery: False
    Balancing Charge Request: False
    **********************************************
    
    MQTT connected: True
```
