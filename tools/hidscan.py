import ctypes
from ctypes import wintypes

setupapi = ctypes.WinDLL("setupapi")
hid = ctypes.WinDLL("hid")
kernel32 = ctypes.WinDLL("kernel32")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.POINTER(wintypes.ULONG))]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", wintypes.WCHAR * 1)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
for _fn in ("HidD_GetManufacturerString", "HidD_GetProductString",
            "HidD_GetSerialNumberString"):
    f = getattr(hid, _fn)
    f.restype = wintypes.BOOLEAN
    f.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
FILE_SHARE_RW = 0x03
OPEN_EXISTING = 3
INVALID = wintypes.HANDLE(-1).value


def hid_guid():
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    return g


def _string(fn, handle):
    buf = ctypes.create_unicode_buffer(256)
    if fn(handle, buf, ctypes.sizeof(buf)):
        return buf.value.strip()
    return ""


def scan():
    guid = hid_guid()
    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    found = {}
    i = 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid),
                                                    i, ctypes.byref(did)):
            break
        i += 1
        need = wintypes.DWORD()
        setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0,
                                                  ctypes.byref(need), None)
        if not need.value:
            continue
        buf = ctypes.create_string_buffer(need.value)
        detail = ctypes.cast(buf, ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W))
        detail.contents.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), buf, need.value,
                ctypes.byref(need), None):
            continue
        path = ctypes.wstring_at(ctypes.addressof(buf) + 4)

        h = kernel32.CreateFileW(path, GENERIC_READ, FILE_SHARE_RW, None,
                                 OPEN_EXISTING, 0, None)
        if h == INVALID:
            h = kernel32.CreateFileW(path, 0, FILE_SHARE_RW, None,
                                     OPEN_EXISTING, 0, None)
            if h == INVALID:
                continue
        try:
            attr = HIDD_ATTRIBUTES()
            attr.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
            if not hid.HidD_GetAttributes(h, ctypes.byref(attr)):
                continue
            key = (attr.VendorID, attr.ProductID)
            if key in found:
                continue
            found[key] = {
                "vid": attr.VendorID, "pid": attr.ProductID,
                "version": attr.VersionNumber,
                "manufacturer": _string(hid.HidD_GetManufacturerString, h),
                "product": _string(hid.HidD_GetProductString, h),
                "serial": _string(hid.HidD_GetSerialNumberString, h),
            }
        finally:
            kernel32.CloseHandle(h)
    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return found


if __name__ == "__main__":
    devs = scan()
    print(f"{len(devs)} dispositivos HID distintos\n")
    for (vid, pid), d in sorted(devs.items()):
        nome = d["product"] or "(sem nome)"
        fab = d["manufacturer"] or "(sem fabricante)"
        print(f"  {vid:04X}:{pid:04X}  {nome}")
        print(f"              fabricante: {fab}"
              + (f"   serial: {d['serial']}" if d["serial"] else ""))
