from __future__ import annotations


class FakeZone:

    def __init__(self, index, name, leds_count, type=1,
                 leds_min=0, leds_max=1024, matrix_width=0, matrix_height=0):
        self.index = index
        self.name = name
        self.leds_count = leds_count
        self.type = type
        self.leds_min = leds_min
        self.leds_max = leds_max
        self.matrix_width = matrix_width
        self.matrix_height = matrix_height


class FakeDevice:

    def __init__(self, index, name, type_name, zones, serial="", location=""):
        self.index = index
        self.name = name
        self.type_name = type_name
        self.serial = serial if serial != "" else "SN%04d" % index
        self.location = location
        self.zones = list(zones)
        self.led_count = sum(z.leds_count for z in self.zones)


def bancada():
    return [
        FakeDevice(0, "Mobo", "Motherboard", [
            FakeZone(0, "ARGB 1", 24),
            FakeZone(1, "ARGB 2", 18),
            FakeZone(2, "Chipset", 1, type=0),
        ]),
        FakeDevice(1, "RAM", "DRAM", [FakeZone(0, "DIMM", 8)]),
        FakeDevice(2, "Cooler", "Cooler", [
            FakeZone(0, "Fan A", 12),
            FakeZone(1, "Fan B", 12),
            FakeZone(2, "Fan C", 12),
        ]),
        FakeDevice(3, "Mouse", "Mouse", [
            FakeZone(0, "Logo", 1, type=0),
            FakeZone(1, "Wheel", 1, type=0),
        ]),
    ]
