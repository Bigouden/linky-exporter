#!/usr/bin/env python3
# coding: utf-8
# pyright: reportMissingImports=false, reportGeneralTypeIssues=false
# pyright: reportMissingModuleSource=false

"""Linky Exporter"""

import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Callable
from wsgiref.simple_server import make_server

import pytz
import serial
from prometheus_client import PLATFORM_COLLECTOR, PROCESS_COLLECTOR
from prometheus_client.core import REGISTRY, CollectorRegistry, Metric
from prometheus_client.exposition import _bake_output, _SilentHandler, parse_qs

LOGFMT = "%(asctime)s - %(levelname)s - %(message)s"
DATEFMT = "%d/%m/%Y %H:%M:%S"

LINKY_EXPORTER_INTERFACE = os.environ.get("LINKY_EXPORTER_INTERFACE", "/dev/ttyUSB0")
LINKY_EXPORTER_LOGLEVEL = os.environ.get("LINKY_EXPORTER_LOGLEVEL", "INFO").upper()
LINKY_EXPORTER_NAME = os.environ.get("LINKY_EXPORTER_NAME", "linky-exporter")
LINKY_EXPORTER_TZ = os.environ.get("TZ", "Europe/Paris")


def make_wsgi_app(
    registry: CollectorRegistry = REGISTRY, disable_compression: bool = False
) -> Callable:
    """Create a WSGI app which serves the metrics from a registry."""

    def prometheus_app(environ, start_response):
        # Prepare parameters
        accept_header = environ.get("HTTP_ACCEPT")
        accept_encoding_header = environ.get("HTTP_ACCEPT_ENCODING")
        params = parse_qs(environ.get("QUERY_STRING", ""))
        headers = [
            ("Server", ""),
            ("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0"),
            ("Pragma", "no-cache"),
            ("Expires", "0"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if environ["PATH_INFO"] == "/":
            status = "301 Moved Permanently"
            headers.append(("Location", "/metrics"))
            output = b""
        elif environ["PATH_INFO"] == "/favicon.ico":
            status = "200 OK"
            output = b""
        elif environ["PATH_INFO"] == "/metrics":
            status, tmp_headers, output = _bake_output(
                registry,
                accept_header,
                accept_encoding_header,
                params,
                disable_compression,
            )
            headers += tmp_headers
        else:
            status = "404 Not Found"
            output = b""
        start_response(status, headers)
        return [output]

    return prometheus_app


def start_wsgi_server(
    port: int,
    addr: str = "0.0.0.0",  # nosec B104
    registry: CollectorRegistry = REGISTRY,
) -> None:
    """Starts a WSGI server for prometheus metrics as a daemon thread."""
    app = make_wsgi_app(registry)
    httpd = make_server(addr, port, app, handler_class=_SilentHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()


start_http_server = start_wsgi_server

# Logging Configuration
try:
    pytz.timezone(LINKY_EXPORTER_TZ)
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone(LINKY_EXPORTER_TZ)
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format=LOGFMT,
        datefmt=DATEFMT,
        level=LINKY_EXPORTER_LOGLEVEL,
    )
except pytz.exceptions.UnknownTimeZoneError:
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone("Europe/Paris")
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format=LOGFMT,
        datefmt=DATEFMT,
        level="INFO",
    )
    logging.error("TZ invalid : %s !", LINKY_EXPORTER_TZ)
    os._exit(1)
except ValueError:
    logging.basicConfig(
        stream=sys.stdout,
        format=LOGFMT,
        datefmt=DATEFMT,
        level="INFO",
    )
    logging.error("LINKY_EXPORTER_LOGLEVEL invalid !")
    os._exit(1)

# Linky Frame Example:
# https://www.enedis.fr/sites/default/files/Enedis-NOI-CPT_54E.pdf
LINKY_FRAME = [
    {
        "name": "ADCO",
        "description": "Adresse du Compteur",
        "type": "constant",
    },
    {
        "name": "OPTARIF",
        "description": "Option Tarifaire Choisie",
        "type": "string",
    },
    {
        "name": "ISOUSC",
        "description": "Intensité Souscrite en A",
        "type": "gauge",
    },
    {
        "name": "BASE",
        "description": "Index Option Base en Wh",
        "type": "counter",
    },
    {
        "name": "HCHC",
        "description": "Index Heure Creuse en Wh",
        "type": "counter",
    },
    {
        "name": "HCHP",
        "description": "Index Heure Pleine en Wh",
        "type": "counter",
    },
    {
        "name": "PTEC",
        "description": "Période Tarifaire En Cours",
        "type": "string",
    },
    {
        "name": "IINST",
        "description": "Intensité Instantanée en A",
        "type": "gauge",
    },
    {
        "name": "IMAX",
        "description": "Intensité Maximale Appelée en A",
        "type": "constant",
    },
    {
        "name": "PAPP",
        "description": "Puissance Apparente en VA",
        "type": "gauge",
    },
    {
        "name": "HHPHC",
        "description": "Horaire Heures Pleines Heures Creuses",
        "type": "unknown",
    },
    {
        "name": "MOTDETAT",
        "description": "Mot d'État du compteur",
        "type": "unknown",
    },
]

LINKY_MODE = [
    {"name": "HISTORIQUE", "baudrate": 1200},
    {"name": "STANDARD", "baudrate": 9600},
]

try:
    LINKY_EXPORTER_PORT = int(os.environ.get("LINKY_EXPORTER_PORT", "8123"))
except ValueError:
    logging.error("LINKY_EXPORTER_PORT must be int !")
    os._exit(1)

try:
    LINKY_FRAME_TIMEOUT = int(os.environ.get("LINKY_FRAME_TIMEOUT", "10"))
except ValueError:
    logging.error("LINKY_FRAME_TIMEOUT must be int !")
    os._exit(1)

LINKY_EXPORTER_MODE = os.environ.get("LINKY_EXPORTER_MODE", "HISTORIQUE")
VALID_MODE = [i["name"] for i in LINKY_MODE]
if LINKY_EXPORTER_MODE not in VALID_MODE:
    logging.error("LINKY_EXPORTER_MODE must be : %s", " or ".join(map(str, VALID_MODE)))
    os._exit(1)

# REGISTRY Configuration
REGISTRY.unregister(PROCESS_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)
REGISTRY.unregister(REGISTRY._names_to_collectors["python_gc_objects_collected_total"])


# Linky Collector Class
class LinkyCollector:
    """Linky Collector Class"""

    def __init__(self):
        self.ser = self._check_for_valid_frame()

    def teleinfo(self):
        """Read Teleinfo And Return Linky Frame Dict"""
        logging.debug("Reading Linky Teleinfo on %s.", LINKY_EXPORTER_INTERFACE)

        with self.ser:
            # Wait For New Linky Frame (Start with 0x02)
            self._wait_for_new_frame()

            # Linky Frame Start
            linky_frame = {}
            while True:
                line = self.ser.readline()
                arr = line.decode().splitlines()[0].split(" ")

                # Specific Case if Checksum == ' '
                if arr[2] == "":
                    arr[2] = " "
                # Skip Line if Invalid Format (Tag, Data, Checksum)
                elif len(arr) != 3:
                    logging.error("Invalid Format (line: %s)", line.decode().strip())
                    self._wait_for_new_frame()
                    linky_frame = {}
                    continue

                # Set Value
                tag = arr[0]
                data = arr[1]
                checksum = arr[2]

                # Debug Value
                logging.debug("%s : %s", tag, data)

                # Verify Checksum
                if not self._verify_checksum(tag, data, checksum):
                    logging.error("Invalid Checksum (line: %s)", line.decode().strip())
                    self._wait_for_new_frame()
                    linky_frame = {}
                    continue

                # Forge Linky Frame Dict
                if tag in [i["name"] for i in LINKY_FRAME]:
                    linky_frame[tag] = data

                # End of Linky Frame (End with 0x03)
                if b"\x03\x02" in line:
                    logging.debug("Linky Frame End")
                    logging.info("Frame : %s ", linky_frame)
                    return linky_frame

    def collect(self):
        """Collect Prometheus Metrics"""
        linky_frame = self.teleinfo()
        labels = {"job": LINKY_EXPORTER_NAME}
        metrics = []
        # Filter Metrics & Labels
        for key, value in linky_frame.items():
            description = [i["description"] for i in LINKY_FRAME if key == i["name"]][0]
            metric_type = [i["type"] for i in LINKY_FRAME if key == i["name"]][0]
            if metric_type in ["counter", "gauge", "histogram", "summary"]:
                metrics.append(
                    {
                        "name": f"linky_{key.lower()}",
                        "value": int(value),
                        "description": description,
                        "type": metric_type,
                    }
                )
            else:
                labels[key.lower()] = value

        # Return Prometheus Metrics
        for metric in metrics:
            prometheus_metric = Metric(
                metric["name"], metric["description"], metric["type"]
            )
            prometheus_metric.add_sample(
                metric["name"], value=metric["value"], labels=labels
            )
            yield prometheus_metric

    def _check_for_valid_frame(self):
        """Check For Valid Frame And Return Serial Object"""
        try:
            ser = serial.Serial(
                port=LINKY_EXPORTER_INTERFACE,
                baudrate=self._select_baudrate(),
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.SEVENBITS,
                dsrdtr=True,
                rtscts=True,
                timeout=1,
            )

            # Read Some Bytes
            init = datetime.now()
            while True:
                if (datetime.now() - init).total_seconds() >= LINKY_FRAME_TIMEOUT:
                    logging.error("Invalid Linky Frame !")
                    os._exit(1)
                line = ser.readline()
                if any(
                    tag in line for tag in [i["name"].encode() for i in LINKY_FRAME]
                ):
                    # Return Serial
                    return ser
        except serial.SerialException:
            logging.error("Unable to read %s.", LINKY_EXPORTER_INTERFACE)
            os._exit(1)

    def _wait_for_new_frame(self):
        line = self.ser.readline()
        init = datetime.now()
        while b"\x02" not in line:
            if (datetime.now() - init).total_seconds() >= LINKY_FRAME_TIMEOUT:
                logging.error("No Linky Frame Received !")
                os._exit(1)
            logging.debug("Wait For New Linky Frame")
            line = self.ser.readline()
        # Start of Linky Frame
        logging.debug("Linky Frame Start")

    @staticmethod
    def _select_baudrate():
        """Select Baud Rate"""
        baudrate = [
            i["baudrate"] for i in LINKY_MODE if LINKY_EXPORTER_MODE == i["name"]
        ][0]
        logging.debug(
            "LINKY_EXPORTER_MODE: %s (Baud Rate: %s).", LINKY_EXPORTER_MODE, baudrate
        )
        return baudrate

    @staticmethod
    def _verify_checksum(tag, data, checksum):
        """Verify Data Checksum"""
        # Checksum= (S1 & 0x3F) + 0x20
        checked_data = [ord(c) for c in tag + " " + data]
        computed_sum = (sum(checked_data) & 0x3F) + 0x20
        return checksum == chr(computed_sum)


if __name__ == "__main__":
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
