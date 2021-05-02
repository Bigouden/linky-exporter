#!/usr/bin/env python3
#coding: utf-8

'''Linky Exporter'''

import logging
import os
import sys
import time
import serial
from prometheus_client.core import REGISTRY, Metric
from prometheus_client import start_http_server, PROCESS_COLLECTOR, PLATFORM_COLLECTOR

LINKY_EXPORTER_INTERFACE = os.environ.get('LINKY_EXPORTER_INTERFACE', '/dev/ttyUSB0')
LINKY_EXPORTER_LOGLEVEL = os.environ.get('LINKY_EXPORTER_LOGLEVEL', 'INFO').upper()
LINKY_EXPORTER_NAME = os.environ.get('LINKY_EXPORTER_NAME', 'linky-exporter')

# Logging Configuration
try:
    logging.basicConfig(stream=sys.stdout,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level=LINKY_EXPORTER_LOGLEVEL)
except ValueError:
    logging.basicConfig(stream=sys.stdout,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level='INFO')
    logging.error("LINKY_EXPORTER_LOGLEVEL invalid !")
    sys.exit(1)

# Linky Frame Example:
# https://www.enedis.fr/sites/default/files/Enedis-NOI-CPT_54E.pdf
LINKY_FRAME = [
    {'name': 'ADCO', 'value': '000000000000', 'description': 'Adresse du Compteur'},
    {'name': 'OPTARIF', 'value': 'HC..', 'description': 'Option Tarifaire Choisie'},
    {'name': 'ISOUSC', 'value': '12', 'description': 'Intensité Souscrite en A'},
    {'name': 'BASE', 'value': '123456789', 'description': 'Index Option Base en Wh'},
    {'name': 'HCHC', 'value': '123456789', 'description': 'Index Heure Creuse en Wh'},
    {'name': 'HCHP', 'value': '123456789', 'description': 'Index Heure Pleine en Wh'},
    {'name': 'PTEC', 'value': 'HP..', 'description': 'Période Tarifaire En Cours'},
    {'name': 'IINST', 'value': '123', 'description': 'Intensité Instantanée en A'},
    {'name': 'IMAX', 'value': '123', 'description': 'Intensité Maximale Appelée en A'},
    {'name': 'PAPP', 'value': '12345', 'description': 'Puissance Apparente en VA'},
    {'name': 'HHPHC', 'value': 'A', 'description': 'Horaire Heures Pleines Heures Creuses'},
    {'name': 'MOTDETAT', 'value': '000000', 'description': 'Mot d\'État du compteur'}
]
LINKY_MODE = [
    {'name': 'HISTORIQUE', 'baudrate': '1200'},
    {'name': 'STANDARD', 'baudrate': '9600'}
]

INT_KEYS = ['ADCO', 'ISOUSC', 'BASE', 'IINST', 'IMAX', 'PAPP']

try:
    LINKY_EXPORTER_PORT = int(os.environ.get('LINKY_EXPORTER_PORT', '8123'))
except ValueError:
    logging.error("LINKY_EXPORTER_PORT must be int !")
    sys.exit(1)

LINKY_EXPORTER_MODE = os.environ.get('LINKY_EXPORTER_MODE', 'HISTORIQUE')
VALID_MODE = [i['name'] for i in LINKY_MODE]
if not LINKY_EXPORTER_MODE in VALID_MODE:
    logging.error("LINKY_EXPORTER_MODE must be : %s", ' or '.join(VALID_MODE))
    sys.exit(1)

# REGISTRY Configuration
REGISTRY.unregister(PROCESS_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)
REGISTRY.unregister(REGISTRY._names_to_collectors['python_gc_objects_collected_total'])

# Linky Collector Class
class LinkyCollector():
    '''Linky Collector Class'''
    def __init__(self):
        self.ser = self._check_for_valid_frame()

    def teleinfo(self):
        '''Read Teleinfo And Return Linky Frame Dict'''
        logging.debug("Reading Linky Teleinfo on %s.", LINKY_EXPORTER_INTERFACE)

        with self.ser:
            # Wait For New Linky Frame (Start with 0x02)
            self._wait_for_new_frame()

            # Linky Frame Start
            linky_frame = {}
            while True:
                line = self.ser.readline()
                arr = line.decode().splitlines()[0].split(' ')

                # Specific Case if Checksum == ' '
                if arr[2] == '':
                    arr[2] = ' '
                # Skip Line if Invalid Format (Tag, Data, Checksum)
                elif len(arr) != 3:
                    logging.error("Invalid Format (line: %s)", line.decode())
                    self._wait_for_new_frame()
                    linky_frame = {}
                    continue

                # Set Value
                tag = arr[0]
                data = arr[1]
                checksum = arr[2]

                # Debug Valeu
                logging.debug("%s : %s", tag, data)

                # Verify Checksum
                if not self._verify_checksum(tag, data, checksum):
                    logging.error("Invalid Checksum (line: %s)", line.decode())
                    self._wait_for_new_frame()
                    linky_frame = {}
                    continue

                # Forge Linky Frame Dict
                if tag in INT_KEYS:
                    linky_frame[tag] = int(data)

                # End of Linky Frame (End with 0x03)
                if b'\x03\x02' in line:
                    logging.debug("Linky Frame End")
                    logging.info("Frame : %s ", linky_frame)
                    return linky_frame

    def collect(self):
        '''Collect Prometheus Metrics'''
        linky_frame = self.teleinfo()
        for key, value in linky_frame.items():
            description = [i['description'] for i in LINKY_FRAME if key == i['name']][0]
            key = "linky_%s" % key.lower()
            metric = Metric(key, description, 'counter')
            metric.add_sample(key, value=value, labels={'service': LINKY_EXPORTER_NAME})
            yield metric

    def _check_for_valid_frame(self):
        '''Check For Valid Frame And Return Serial Object'''
        try:
            ser = serial.Serial(port=LINKY_EXPORTER_INTERFACE,
                                baudrate=self._select_baudrate(),
                                parity=serial.PARITY_EVEN,
                                stopbits=serial.STOPBITS_ONE,
                                bytesize=serial.SEVENBITS,
                                timeout=1)

            # Read Some Bytes
            line = ser.read(9600)
            if not any(key in line.decode() for key in INT_KEYS):
                logging.error("Invalid Linky Frame !")
                sys.exit(1)

            # Return Serial
            return ser
        except serial.serialutil.SerialException:
            logging.error("Unable to read %s.", LINKY_EXPORTER_INTERFACE)
            sys.exit(1)

    def _wait_for_new_frame(self):
        line = self.ser.readline()
        while b'\x02' not in line:
            logging.debug("Wait For New Linky Frame")
            line = self.ser.readline()
        # Start of Linky Frame
        logging.debug("Linky Frame Start")

    @staticmethod
    def _select_baudrate():
        '''Select Baud Rate'''
        baudrate = [i['baudrate'] for i in LINKY_MODE if LINKY_EXPORTER_MODE == i['name']][0]
        logging.debug("LINKY_EXPORTER_MODE: %s (Baud Rate: %s).", LINKY_EXPORTER_MODE, baudrate)
        return baudrate

    @staticmethod
    def _verify_checksum(tag, data, checksum):
        '''Verify Data Checksum'''
        # Checksum= (S1 & 0x3F) + 0x20
        checked_data = [ord(c) for c in tag + ' ' + data]
        computed_sum = (sum(checked_data) & 0x3F) + 0x20
        return checksum == chr(computed_sum)

if __name__ == '__main__':
    logging.info("Starting Linky Exporter on port %s.", LINKY_EXPORTER_PORT)
    logging.debug("LINKY_EXPORTER_PORT: %s.", LINKY_EXPORTER_PORT)
    logging.debug("LINKY_EXPORTER_INTERFACE: %s.", LINKY_EXPORTER_INTERFACE)
    logging.debug("LINKY_EXPORTER_NAME: %s.", LINKY_EXPORTER_NAME)
    # Start Prometheus HTTP Server
    start_http_server(LINKY_EXPORTER_PORT)
    # Init LinkyCollector
    REGISTRY.register(LinkyCollector())
    # Loop Infinity
    while True:
        time.sleep(1)
